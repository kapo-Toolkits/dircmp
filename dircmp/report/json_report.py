"""Machine-readable JSON report."""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import IO

from ..core.compare import Comparison
from ..core.fields import iso_time
from ..core.model import Entry

FORMAT_VERSION = 1


def _entry(e: Entry | None) -> dict | None:
    if e is None:
        return None
    d = asdict(e)
    d["kind"] = e.kind.value
    for f in ("mtime", "atime", "ctime", "birth"):
        d[f] = iso_time(d[f + "_ns"])
    return d


def to_dict(comp: Comparison, *, all_rows: bool = False) -> dict:
    labels = comp.labels
    opts = asdict(comp.options)
    opts["mode"] = comp.options.mode.value
    opts["compare_fields"] = list(comp.options.fields())
    rows = comp.rows if all_rows else comp.differences()
    return {
        "format_version": FORMAT_VERSION,
        "folders": [{"label": lab, "path": p} for lab, p in zip(labels, comp.roots)],
        "options": opts,
        "elapsed_seconds": round(comp.elapsed, 3),
        "summary": comp.summary(),
        "distance_matrix": comp.distance_matrix(),
        "rows": [
            {
                "path": r.rel,
                "status": r.status.value,
                "presence": r.presence,
                "overall_group": r.overall,
                "differing": r.differing,
                "groups": {f: [[labels[i] for i in g] for g in gs] for f, gs in r.groups.items()},
                "moved": {labels[i]: p for i, p in sorted(r.moved.items())},
                "entries": [_entry(e) for e in r.entries],
            }
            for r in rows
        ],
        "errors": [{"folder": labels[e.folder], "path": e.rel, "message": e.message} for e in comp.errors],
    }


def write_json(comp: Comparison, fp: IO[str], *, all_rows: bool = False) -> None:
    json.dump(to_dict(comp, all_rows=all_rows), fp, ensure_ascii=False, indent=2)
    fp.write("\n")
