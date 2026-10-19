"""Content hashing: cheap head+tail hash first, full BLAKE2b only where needed."""

from __future__ import annotations

import hashlib
import os
import threading
from collections import defaultdict
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

from .model import Entry
from .scanner import Cancelled

PARTIAL_THRESHOLD = 1 << 20  # files larger than this get a head+tail pre-hash
PARTIAL_CHUNK = 64 << 10
READ_CHUNK = 1 << 20

Item = tuple[str, Entry]  # (absolute path, entry)


def full_hash(path: str, cancel: threading.Event | None = None) -> str:
    h = hashlib.blake2b(digest_size=20)
    with open(path, "rb") as f:
        while chunk := f.read(READ_CHUNK):
            if cancel is not None and cancel.is_set():
                raise Cancelled
            h.update(chunk)
    return "f:" + h.hexdigest()


def partial_hash(path: str, size: int) -> str:
    h = hashlib.blake2b(digest_size=20)
    with open(path, "rb") as f:
        h.update(f.read(PARTIAL_CHUNK))
        f.seek(max(size - PARTIAL_CHUNK, 0), os.SEEK_SET)
        h.update(f.read(PARTIAL_CHUNK))
    return "p:" + h.hexdigest()


def _run(fn: Callable[[Item], None], items: list[Item], threads: int,
         cancel: threading.Event | None, tick: Callable[[int], None] | None) -> None:
    def work(item: Item) -> None:
        if cancel is not None and cancel.is_set():
            raise Cancelled
        try:
            fn(item)
        except OSError as exc:
            item[1].hash = None
            item[1].error = f"read failed: {exc.strerror or exc}"
        if tick is not None:
            tick(1)

    with ThreadPoolExecutor(max_workers=threads) as pool:
        for _ in pool.map(work, items):
            pass


def hash_all(items: list[Item], threads: int, cancel=None, tick=None) -> None:
    """Full hash of every item (deep mode)."""
    todo = [it for it in items if not (it[1].hash or "").startswith("f:")]

    def do(item: Item) -> None:
        item[1].hash = full_hash(item[0], cancel)

    _run(do, todo, threads, cancel, tick)


def resolve(buckets: list[list[Item]], threads: int, cancel=None, tick=None) -> None:
    """Give every entry in each same-size bucket a hash good enough to tell them apart.

    Entries whose head+tail hash is unique within the bucket keep that partial hash
    (it already proves they differ); the rest get a full hash.
    """
    big = [it for b in buckets for it in b if it[1].size > PARTIAL_THRESHOLD and not it[1].hash]

    def do_partial(item: Item) -> None:
        item[1].hash = partial_hash(item[0], item[1].size)

    _run(do_partial, big, threads, cancel, tick)

    need_full: list[Item] = []
    for bucket in buckets:
        by_partial: dict[str | None, list[Item]] = defaultdict(list)
        for it in bucket:
            if it[1].error:
                continue
            h = it[1].hash
            by_partial[h if h and h.startswith("p:") else None].append(it)
        for h, group in by_partial.items():
            if h is None or len(group) > 1:
                need_full.extend(it for it in group if not (it[1].hash or "").startswith("f:"))

    def do_full(item: Item) -> None:
        item[1].hash = full_hash(item[0], cancel)

    _run(do_full, need_full, threads, cancel, tick)
