"""Human-readable field names and values, shared by reports and the GUI."""

from __future__ import annotations

import stat
from datetime import datetime, timezone

from .model import Entry, Kind, Status

FIELD_NAMES = {
    "kind": "ტიპი",
    "size": "ზომა",
    "content": "შიგთავსი (ჰეში)",
    "mtime": "შეცვლის დრო",
    "birth": "შექმნის დრო",
    "ctime": "ctime",
    "atime": "წვდომის დრო",
    "mode": "უფლებები",
    "owner": "მფლობელი",
    "attrs": "ატრიბუტები",
    "link_target": "ბმულის სამიზნე",
    "xattrs": "xattr",
}

STATUS_NAMES = {
    Status.IDENTICAL: "იდენტური",
    Status.CONTENT_DIFFERS: "შიგთავსი განსხვავდება",
    Status.METADATA_DIFFERS: "მეტამონაცემები განსხვავდება",
    Status.PARTIAL: "ზოგან აკლია",
    Status.MOVED: "გადატანილი",
    Status.ERROR: "შეცდომა",
}

KIND_NAMES = {Kind.FILE: "ფაილი", Kind.DIR: "საქაღალდე", Kind.SYMLINK: "symlink", Kind.OTHER: "სხვა"}

UNAVAILABLE = "მიუწვდომელია"


def fmt_time(ns: int | None) -> str:
    if ns is None:
        return UNAVAILABLE
    dt = datetime.fromtimestamp(ns / 1e9, tz=timezone.utc).astimezone()
    frac = ns % 1_000_000_000
    return dt.strftime("%Y-%m-%d %H:%M:%S") + (f".{frac:09d}".rstrip("0") if frac else "")


def iso_time(ns: int | None) -> str | None:
    if ns is None:
        return None
    return datetime.fromtimestamp(ns / 1e9, tz=timezone.utc).isoformat()


def fmt_size(n: int) -> str:
    units = ["B", "KiB", "MiB", "GiB", "TiB"]
    v = float(n)
    for u in units:
        if v < 1024 or u == units[-1]:
            return f"{n} B" if u == "B" else f"{v:.1f} {u} ({n} B)"
        v /= 1024
    return f"{n} B"


def fmt_hash(h: str | None) -> str:
    if not h:
        return "—"
    kind, digest = h.split(":", 1)
    return digest[:16] + ("…" if kind == "f" else " (ნაწილობრივი)")


def value_text(field: str, e: Entry | None) -> str:
    if e is None:
        return "∅"
    k = e.kind
    match field:
        case "kind":
            return KIND_NAMES[k]
        case "size":
            return fmt_size(e.size) if k is Kind.FILE else "—"
        case "content":
            if k is not Kind.FILE:
                return "—"
            if e.error:
                return f"⚠ {e.error}"
            if e.size == 0:
                return "(ცარიელი)"
            return fmt_hash(e.hash) if e.hash else "(არ დაჰეშილა)"
        case "mtime":
            return fmt_time(e.mtime_ns)
        case "birth":
            return fmt_time(e.birth_ns)
        case "ctime":
            return fmt_time(e.ctime_ns)
        case "atime":
            return fmt_time(e.atime_ns)
        case "mode":
            return "—" if e.mode is None or k is Kind.SYMLINK else f"{stat.filemode(e.mode)[1:]} ({e.mode:04o})"
        case "owner":
            return "—" if e.uid is None else f"{e.uid}:{e.gid}"
        case "attrs":
            if e.attrs is None:
                return "—"
            flags = [n for bit, n in ((1, "readonly"), (2, "hidden"), (4, "system")) if e.attrs & bit]
            return ", ".join(flags) or "(არცერთი)"
        case "link_target":
            return e.link_target or "—"
        case "xattrs":
            if e.xattrs is None:
                return "—"
            return ", ".join(e.xattrs) or "(არცერთი)"
    raise KeyError(field)


def group_notation(overall: list[int | None], labels: list[str]) -> str:
    """e.g. overall [0, 1, 0, None] -> 'A=C ≠ B  ∅ D'."""
    groups: dict[int, list[str]] = {}
    missing = []
    for lab, g in zip(labels, overall):
        if g is None:
            missing.append(lab)
        else:
            groups.setdefault(g, []).append(lab)
    text = " ≠ ".join("=".join(g) for g in groups.values())
    if missing:
        text += ("  " if text else "") + "∅ " + ",".join(missing)
    return text
