"""OS-specific metadata: creation time, Windows attributes, extended attributes."""

from __future__ import annotations

import hashlib
import os
import sys

IS_WINDOWS = os.name == "nt"
IS_LINUX = sys.platform.startswith("linux")

# Windows attributes worth comparing; ARCHIVE etc. flip on every backup.
WIN_ATTR_MASK = 0x1 | 0x2 | 0x4  # READONLY | HIDDEN | SYSTEM
WIN_ATTR_HIDDEN = 0x2

if IS_LINUX:
    from ._statx import birth_ns as _linux_birth_ns
else:  # pragma: no cover - platform specific
    _linux_birth_ns = None


def birth_ns(path: str, st: os.stat_result, follow_symlinks: bool) -> int | None:
    """Creation time in ns, or None when the platform/filesystem doesn't record it."""
    ns = getattr(st, "st_birthtime_ns", None)
    if ns is not None:
        return ns
    t = getattr(st, "st_birthtime", None)
    if t is not None:  # macOS / BSD expose only the float
        return int(t * 1_000_000_000)
    if _linux_birth_ns is not None:
        return _linux_birth_ns(path, follow_symlinks)
    return None


def ctime_ns(st: os.stat_result) -> int | None:
    # On Windows st_ctime historically meant creation time; that's covered by birth_ns.
    return None if IS_WINDOWS else st.st_ctime_ns


def owner(st: os.stat_result) -> tuple[int | None, int | None]:
    return (None, None) if IS_WINDOWS else (st.st_uid, st.st_gid)


def win_attrs(st: os.stat_result) -> int | None:
    a = getattr(st, "st_file_attributes", None)
    return None if a is None else a & WIN_ATTR_MASK


def is_hidden(name: str, st: os.stat_result | None) -> bool:
    if name.startswith("."):
        return True
    a = getattr(st, "st_file_attributes", None) if st is not None else None
    return bool(a and a & WIN_ATTR_HIDDEN)


def xattrs(path: str, follow_symlinks: bool) -> dict[str, str] | None:
    """Extended attribute name -> short digest of its value. None if unsupported."""
    if not hasattr(os, "listxattr"):  # Linux only in CPython
        return None
    try:
        out = {}
        for name in sorted(os.listxattr(path, follow_symlinks=follow_symlinks)):
            value = os.getxattr(path, name, follow_symlinks=follow_symlinks)
            out[name] = hashlib.blake2b(value, digest_size=8).hexdigest()
        return out
    except OSError:
        return None
