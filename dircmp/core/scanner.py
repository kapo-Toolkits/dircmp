"""Recursive, read-only directory scanner producing normalized Entry objects."""

from __future__ import annotations

import fnmatch
import os
import stat
import threading
import unicodedata
from collections.abc import Callable

from .. import platform as plat
from .model import Entry, Kind, Mode, Options, ScanError


class Cancelled(Exception):
    pass


def make_key(rel: str, opts: Options) -> str:
    if opts.normalize_unicode:
        rel = unicodedata.normalize("NFC", rel)
    if opts.case_insensitive:
        rel = rel.casefold()
    return rel


def _ignored(name: str, rel: str, patterns: list[str]) -> bool:
    for p in patterns:
        target = rel if "/" in p else name
        if fnmatch.fnmatchcase(target, p.strip("/")):
            return True
    return False


def _kind(st: os.stat_result) -> Kind:
    if stat.S_ISREG(st.st_mode):
        return Kind.FILE
    if stat.S_ISDIR(st.st_mode):
        return Kind.DIR
    if stat.S_ISLNK(st.st_mode):
        return Kind.SYMLINK
    return Kind.OTHER


def _entry(path: str, rel: str, st: os.stat_result, kind: Kind, opts: Options) -> Entry:
    uid, gid = plat.owner(st)
    e = Entry(
        rel=rel,
        kind=kind,
        size=st.st_size if kind is Kind.FILE else 0,
        mtime_ns=st.st_mtime_ns,
        atime_ns=st.st_atime_ns,
        ctime_ns=plat.ctime_ns(st),
        mode=stat.S_IMODE(st.st_mode),
        uid=uid,
        gid=gid,
        nlink=st.st_nlink,
        dev=st.st_dev,
        ino=st.st_ino,
        attrs=plat.win_attrs(st),
    )
    if kind is Kind.SYMLINK:
        try:
            e.link_target = os.readlink(path)
        except OSError as exc:
            e.error = f"readlink: {exc.strerror or exc}"
    if opts.mode is not Mode.QUICK:
        e.birth_ns = plat.birth_ns(path, st, opts.follow_symlinks)
    if opts.mode is Mode.DEEP:
        e.xattrs = plat.xattrs(path, opts.follow_symlinks)
    return e


def scan_folder(
    index: int,
    root: str,
    opts: Options,
    cancel: threading.Event | None = None,
    tick: Callable[[int], None] | None = None,
) -> tuple[dict[str, Entry], list[ScanError]]:
    """Walk `root` and return {key: Entry} for everything below it (root itself excluded)."""
    entries: dict[str, Entry] = {}
    errors: list[ScanError] = []
    root_st = os.stat(root)
    visited = {(root_st.st_dev, root_st.st_ino)}  # only used when following symlinks
    stack: list[tuple[str, str]] = [(root, "")]
    pending = 0

    def fail(rel: str, msg: str) -> None:
        errors.append(ScanError(index, rel, msg))

    while stack:
        if cancel is not None and cancel.is_set():
            raise Cancelled
        abs_dir, prefix = stack.pop()
        try:
            it = os.scandir(abs_dir)
        except OSError as exc:
            msg = f"cannot list directory: {exc.strerror or exc}"
            fail(prefix.rstrip("/") or ".", msg)
            if prefix and (parent := entries.get(make_key(prefix.rstrip("/"), opts))):
                parent.error = msg
            continue
        with it:
            for de in it:
                name = de.name
                rel = prefix + name
                if opts.ignore and _ignored(name, rel, opts.ignore):
                    continue
                path = de.path
                try:
                    is_link = de.is_symlink() or getattr(de, "is_junction", lambda: False)()
                    try:
                        st = de.stat(follow_symlinks=opts.follow_symlinks)
                    except FileNotFoundError:
                        if not is_link:
                            raise
                        st = de.stat(follow_symlinks=False)  # dangling link
                        is_link, kind = True, Kind.SYMLINK
                    else:
                        kind = Kind.SYMLINK if is_link and not opts.follow_symlinks else _kind(st)
                except OSError as exc:
                    fail(rel, f"stat failed: {exc.strerror or exc}")
                    entries.setdefault(make_key(rel, opts), Entry(rel=rel, kind=Kind.OTHER, error=str(exc)))
                    continue

                if opts.exclude_hidden and plat.is_hidden(name, st):
                    continue

                entry = _entry(path, rel, st, kind, opts)
                key = make_key(rel, opts)
                if key in entries:
                    fail(rel, f"name collides with '{entries[key].rel}' after normalization; skipped")
                    continue
                entries[key] = entry

                if kind is Kind.DIR:
                    if opts.follow_symlinks:  # guard against cycles through links/junctions
                        ident = (st.st_dev, st.st_ino)
                        if ident in visited:
                            entry.error = "directory already visited (symlink cycle?); not descended"
                            fail(rel, entry.error)
                            continue
                        visited.add(ident)
                    stack.append((path, rel + "/"))

                pending += 1
                if tick is not None and pending >= 256:
                    tick(pending)
                    pending = 0
    if tick is not None and pending:
        tick(pending)
    return entries, errors
