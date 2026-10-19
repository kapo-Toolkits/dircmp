"""Data model shared by the scanner, the diff engine, reports and the GUI."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Kind(str, Enum):
    FILE = "file"
    DIR = "dir"
    SYMLINK = "symlink"
    OTHER = "other"


class Status(str, Enum):
    IDENTICAL = "identical"
    CONTENT_DIFFERS = "content_differs"
    METADATA_DIFFERS = "metadata_differs"
    PARTIAL = "partial"  # missing from at least one folder
    MOVED = "moved"  # missing somewhere, but the same content exists there under another path
    ERROR = "error"


class Mode(str, Enum):
    QUICK = "quick"  # kind + size + mtime (1 s), no hashing
    STANDARD = "standard"  # + content hash where sizes match, permissions, birth time
    DEEP = "deep"  # + full hash of every file, xattrs


# Every field the engine knows how to group by, in display order.
ALL_FIELDS = (
    "kind", "size", "content", "mtime", "birth", "ctime", "atime",
    "mode", "owner", "attrs", "link_target", "xattrs",
)
TIME_FIELDS = frozenset({"mtime", "birth", "ctime", "atime"})
# Fields whose difference means the data itself differs (vs. only metadata).
CONTENT_FIELDS = frozenset({"kind", "size", "content", "link_target"})

# Fields that decide a row's status. atime/ctime/birth/owner are still grouped
# and shown, but copies almost always differ there, so they don't count by default.
DEFAULT_COMPARE = {
    Mode.QUICK: ("kind", "size", "mtime", "link_target"),
    Mode.STANDARD: ("kind", "size", "content", "mtime", "mode", "attrs", "link_target"),
    Mode.DEEP: ("kind", "size", "content", "mtime", "mode", "attrs", "link_target", "xattrs"),
}


def label(i: int) -> str:
    """Folder label: A..Z, then AA, AB, ... (spreadsheet style, unbounded)."""
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


@dataclass(slots=True)
class Entry:
    """One filesystem object inside one of the compared folders."""

    rel: str  # path relative to its root, '/'-separated, original spelling
    kind: Kind
    size: int = 0
    mtime_ns: int | None = None
    atime_ns: int | None = None
    ctime_ns: int | None = None  # inode change time (Unix only)
    birth_ns: int | None = None  # creation time, None when the OS/FS can't tell
    mode: int | None = None  # permission bits
    uid: int | None = None
    gid: int | None = None
    nlink: int = 1
    dev: int = 0
    ino: int = 0
    attrs: int | None = None  # Windows file attributes
    link_target: str | None = None
    xattrs: dict[str, str] | None = None  # name -> digest of value
    hash: str | None = None  # "f:<hex>" full, "p:<hex>" partial (only proves inequality)
    error: str | None = None

    @property
    def name(self) -> str:
        return self.rel.rsplit("/", 1)[-1]


@dataclass(slots=True)
class ScanError:
    folder: int
    rel: str
    message: str


@dataclass(slots=True)
class Row:
    """One relative path, seen across all N folders."""

    key: str  # matching key (normalized / case-folded)
    rel: str  # display path, from the first folder that has it
    entries: list[Entry | None]
    status: Status = Status.IDENTICAL
    # field -> groups of folder indices with equal values, e.g. [[0, 2], [1]]
    groups: dict[str, list[list[int]]] = field(default_factory=dict)
    differing: list[str] = field(default_factory=list)  # compared fields with >1 group
    # per folder: overall group number (0-based) over all compared fields, None if absent
    overall: list[int | None] = field(default_factory=list)
    moved: dict[int, str] = field(default_factory=dict)  # folder -> path holding same content

    @property
    def presence(self) -> list[bool]:
        return [e is not None for e in self.entries]

    @property
    def kind(self) -> Kind | None:
        kinds = {e.kind for e in self.entries if e is not None}
        return kinds.pop() if len(kinds) == 1 else None

    @property
    def name(self) -> str:
        return self.rel.rsplit("/", 1)[-1]


@dataclass(slots=True)
class Options:
    mode: Mode = Mode.STANDARD
    ignore: list[str] = field(default_factory=list)  # glob patterns, matched on name and rel path
    exclude_hidden: bool = False
    follow_symlinks: bool = False
    case_insensitive: bool = False
    normalize_unicode: bool = True  # NFC, so macOS NFD names match Linux/Windows NFC names
    time_tolerance: float = 0.0  # seconds
    threads: int = 0  # 0 = auto
    compare_fields: tuple[str, ...] | None = None  # None = DEFAULT_COMPARE[mode]
    detect_moves: bool = True

    def fields(self) -> tuple[str, ...]:
        return self.compare_fields or DEFAULT_COMPARE[self.mode]

    def tolerance_ns(self) -> int:
        tol = self.time_tolerance
        if self.mode is Mode.QUICK:
            tol = max(tol, 1.0)
        return int(tol * 1_000_000_000)
