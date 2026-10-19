"""N-way comparison: scan every folder, reconcile by relative path, group values per field."""

from __future__ import annotations

import os
import threading
import time
from collections import defaultdict
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from . import hashing
from .model import (
    ALL_FIELDS, CONTENT_FIELDS, TIME_FIELDS, Entry, Kind, Mode, Options, Row, ScanError, Status, label,
)
from .scanner import Cancelled, scan_folder

ProgressFn = Callable[[str, int, int], None]  # (phase, done, total); total 0 = unknown


@dataclass
class Comparison:
    roots: list[str]
    options: Options
    rows: list[Row]
    errors: list[ScanError]
    elapsed: float

    @property
    def labels(self) -> list[str]:
        return [label(i) for i in range(len(self.roots))]

    @property
    def all_identical(self) -> bool:
        return not self.errors and all(r.status is Status.IDENTICAL for r in self.rows)

    def differences(self) -> list[Row]:
        return [r for r in self.rows if r.status is not Status.IDENTICAL]

    def summary(self) -> dict[str, int]:
        out = {s.value: 0 for s in Status}
        for r in self.rows:
            out[r.status.value] += 1
        out["total"] = len(self.rows)
        return out

    def distance_matrix(self) -> list[list[int]]:
        """m[i][j] = number of paths where folders i and j disagree (presence or any compared field)."""
        n = len(self.roots)
        m = [[0] * n for _ in range(n)]
        for r in self.rows:
            ov = r.overall
            if r.status is Status.IDENTICAL:
                continue
            for i in range(n):
                for j in range(i + 1, n):
                    if ov[i] != ov[j]:
                        m[i][j] += 1
                        m[j][i] += 1
        return m


class _Progress:
    """Thread-safe, throttled progress reporter."""

    def __init__(self, fn: ProgressFn | None):
        self.fn = fn
        self.lock = threading.Lock()
        self.phase, self.done, self.total, self.last = "", 0, 0, 0.0

    def start(self, phase: str, total: int = 0) -> None:
        with self.lock:
            self.phase, self.done, self.total = phase, 0, total
        self._emit(force=True)

    def tick(self, n: int = 1) -> None:
        with self.lock:
            self.done += n
        self._emit()

    def _emit(self, force: bool = False) -> None:
        if self.fn is None:
            return
        now = time.monotonic()
        if force or now - self.last >= 0.1:
            self.last = now
            self.fn(self.phase, self.done, self.total)


def compare(
    roots: list[str],
    options: Options | None = None,
    progress: ProgressFn | None = None,
    cancel: threading.Event | None = None,
) -> Comparison:
    opts = options or Options()
    if len(roots) < 2:
        raise ValueError("need at least two folders to compare")
    roots = [os.path.abspath(r) for r in roots]
    for r in roots:
        if not os.path.isdir(r):
            raise ValueError(f"not a directory: {r}")
    threads = opts.threads or min(32, os.cpu_count() or 4)
    started = time.monotonic()
    prog = _Progress(progress)

    maps, errors = _scan_all(roots, opts, cancel, prog)
    rows = _reconcile(maps)
    _hash(rows, roots, opts, threads, cancel, prog)

    prog.start("diff", len(rows))
    tol = opts.tolerance_ns()
    for row in rows:
        _diff(row, opts, tol)
    if opts.detect_moves and opts.mode is not Mode.QUICK:
        _detect_moves(rows)
    prog.tick(len(rows))

    errors.sort(key=lambda e: (e.folder, e.rel))
    return Comparison(roots, opts, rows, errors, time.monotonic() - started)


# --- scanning -----------------------------------------------------------------

def _scan_all(roots, opts, cancel, prog):
    """Scan folders in parallel, but folders on the same device one after another
    (parallel reads on one spinning disk are slower than sequential ones)."""
    by_dev: dict[int, list[int]] = defaultdict(list)
    for i, r in enumerate(roots):
        by_dev[os.stat(r).st_dev].append(i)

    maps: list[dict[str, Entry]] = [{} for _ in roots]
    errors: list[ScanError] = []
    prog.start("scan")

    def scan_group(indices: list[int]) -> None:
        for i in indices:
            m, errs = scan_folder(i, roots[i], opts, cancel, prog.tick)
            maps[i] = m
            errors.extend(errs)

    with ThreadPoolExecutor(max_workers=len(by_dev)) as pool:
        for f in [pool.submit(scan_group, g) for g in by_dev.values()]:
            f.result()
    return maps, errors


def _reconcile(maps: list[dict[str, Entry]]) -> list[Row]:
    keys = set().union(*maps)
    rows = []
    for key in sorted(keys, key=lambda k: k.split("/")):
        entries = [m.get(key) for m in maps]
        rel = next(e.rel for e in entries if e is not None)
        rows.append(Row(key=key, rel=rel, entries=entries))
    return rows


# --- hashing ------------------------------------------------------------------

def _path(root: str, e: Entry) -> str:
    return os.path.join(root, *e.rel.split("/"))


def _hash(rows, roots, opts, threads, cancel, prog) -> None:
    if opts.mode is Mode.QUICK:
        return

    def files(row: Row):
        for i, e in enumerate(row.entries):
            if e is not None and e.kind is Kind.FILE and not e.error and e.size > 0:
                yield i, e

    if opts.mode is Mode.DEEP:
        items = [(_path(roots[i], e), e) for row in rows for i, e in files(row)]
        prog.start("hash", len(items))
        hashing.hash_all(items, threads, cancel, prog.tick)
        return

    # Standard: hash only entries that share a size with something they're compared to.
    chosen: dict[int, tuple[str, Entry]] = {}  # id(entry) -> item, dedup across reasons
    n = len(roots)
    orphans: dict[int, list[tuple[int, Entry]]] = defaultdict(list)  # size -> files in partial rows
    for row in rows:
        fs = list(files(row))
        by_size: dict[int, list[tuple[int, Entry]]] = defaultdict(list)
        for i, e in fs:
            by_size[e.size].append((i, e))
        for group in by_size.values():
            if len(group) > 1:
                for i, e in group:
                    chosen[id(e)] = (_path(roots[i], e), e)
        if opts.detect_moves and sum(e is not None for e in row.entries) < n:
            for i, e in fs:
                orphans[e.size].append((i, e))
    for group in orphans.values():
        if len({i for i, _ in group}) > 1:
            for i, e in group:
                chosen[id(e)] = (_path(roots[i], e), e)

    buckets: dict[int, list[tuple[str, Entry]]] = defaultdict(list)
    for item in chosen.values():
        buckets[item[1].size].append(item)
    prog.start("hash", len(chosen))
    hashing.resolve(list(buckets.values()), threads, cancel, prog.tick)


# --- grouping -----------------------------------------------------------------

def _value(field: str, e: Entry):
    k = e.kind
    if field == "kind":
        return k.value
    if field == "size":
        return e.size if k is Kind.FILE else None
    if field == "content":
        if k is not Kind.FILE:
            return None
        if e.error:
            return ("error", id(e))  # never equal to anything
        if e.size == 0:
            return "empty"
        return e.hash or ("size", e.size)
    if field == "mtime":
        return e.mtime_ns if k is Kind.FILE else None
    if field == "birth":
        return e.birth_ns
    if field == "ctime":
        return e.ctime_ns
    if field == "atime":
        return e.atime_ns
    if field == "mode":
        return None if k is Kind.SYMLINK else e.mode
    if field == "owner":
        return None if e.uid is None else (e.uid, e.gid)
    if field == "attrs":
        return e.attrs
    if field == "link_target":
        return e.link_target if k is Kind.SYMLINK else None
    if field == "xattrs":
        return None if e.xattrs is None else tuple(sorted(e.xattrs.items()))
    raise KeyError(field)


def _group_exact(values: list[tuple[int, object]]) -> list[list[int]]:
    groups: dict[object, list[int]] = {}
    for i, v in values:
        groups.setdefault(v, []).append(i)
    return list(groups.values())


def _group_time(values: list[tuple[int, int | None]], tol: int) -> list[list[int]]:
    """Cluster timestamps: a new group starts when a value is more than `tol` past
    the first value of the current group. Bounded width keeps it from chaining
    A≈B≈C into one group when A and C are far apart."""
    groups: list[list[int]] = []
    missing = [i for i, v in values if v is None]
    start = None
    for i, v in sorted(((i, v) for i, v in values if v is not None), key=lambda x: x[1]):
        if start is None or v - start > tol:
            groups.append([])
            start = v
        groups[-1].append(i)
    if missing:
        groups.append(missing)
    for g in groups:
        g.sort()
    groups.sort(key=lambda g: g[0])
    return groups


def _diff(row: Row, opts: Options, tol: int) -> None:
    present = [(i, e) for i, e in enumerate(row.entries) if e is not None]
    for f in ALL_FIELDS:
        vals = [(i, _value(f, e)) for i, e in present]
        row.groups[f] = _group_time(vals, tol) if f in TIME_FIELDS else _group_exact(vals)

    compared = opts.fields()
    row.differing = [f for f in compared if len(row.groups[f]) > 1]

    member = {f: {i: gi for gi, g in enumerate(row.groups[f]) for i in g} for f in compared}
    ids: dict[tuple, int] = {}
    row.overall = [None] * len(row.entries)
    for i, _ in present:
        sig = tuple(member[f][i] for f in compared)
        row.overall[i] = ids.setdefault(sig, len(ids))

    if any(e.error for _, e in present):
        row.status = Status.ERROR
    elif len(present) < len(row.entries):
        row.status = Status.PARTIAL
    elif any(f in CONTENT_FIELDS for f in row.differing):
        row.status = Status.CONTENT_DIFFERS
    elif row.differing:
        row.status = Status.METADATA_DIFFERS
    else:
        row.status = Status.IDENTICAL


def _detect_moves(rows: list[Row]) -> None:
    """A path missing from folder X counts as moved there if X holds a file with the
    same full hash under another path."""
    where: dict[str, dict[int, str]] = defaultdict(dict)  # hash -> folder -> rel
    for row in rows:
        for i, e in enumerate(row.entries):
            if e is not None and e.kind is Kind.FILE and e.hash and e.hash.startswith("f:"):
                where[e.hash].setdefault(i, e.rel)

    for row in rows:
        if row.status is not Status.PARTIAL:
            continue
        hashes = {e.hash for e in row.entries if e is not None and e.hash and e.hash.startswith("f:")}
        if not hashes:
            continue
        for i, e in enumerate(row.entries):
            if e is not None:
                continue
            for h in hashes:
                if i in where[h]:
                    row.moved[i] = where[h][i]
                    break
        if len(row.moved) == row.entries.count(None):
            row.status = Status.MOVED


__all__ = ["Comparison", "compare", "Cancelled"]
