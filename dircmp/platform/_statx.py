"""Linux creation time via statx(2), called through ctypes (glibc >= 2.28)."""

from __future__ import annotations

import ctypes
import os
import struct

AT_FDCWD = -100
AT_SYMLINK_NOFOLLOW = 0x100
STATX_BTIME = 0x800
_BTIME_OFFSET = 80  # offsetof(struct statx, stx_btime)
_BUF_SIZE = 256  # sizeof(struct statx)

try:
    _statx = ctypes.CDLL(None, use_errno=True).statx
    _statx.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_uint, ctypes.c_void_p]
    _statx.restype = ctypes.c_int
except (OSError, AttributeError):  # musl without statx, very old glibc
    _statx = None


def birth_ns(path: str, follow_symlinks: bool) -> int | None:
    if _statx is None:
        return None
    buf = ctypes.create_string_buffer(_BUF_SIZE)
    flags = 0 if follow_symlinks else AT_SYMLINK_NOFOLLOW
    if _statx(AT_FDCWD, os.fsencode(path), flags, STATX_BTIME, buf) != 0:
        return None
    (mask,) = struct.unpack_from("I", buf, 0)
    if not mask & STATX_BTIME:  # kernel or filesystem doesn't record it
        return None
    sec, nsec = struct.unpack_from("qI", buf, _BTIME_OFFSET)
    return sec * 1_000_000_000 + nsec
