"""Wide CSV report: one line per path, a block of columns per folder."""

from __future__ import annotations

import csv
from typing import IO

from ..core.compare import Comparison
from ..core.fields import group_notation, iso_time

PER_FOLDER = ("present", "group", "kind", "size", "mtime", "birth", "mode", "hash", "error")


def write_csv(comp: Comparison, fp: IO[str], *, all_rows: bool = False) -> None:
    labels = comp.labels
    w = csv.writer(fp)
    w.writerow(["path", "status", "groups", "differing", "moved"]
               + [f"{lab}_{col}" for lab in labels for col in PER_FOLDER])
    for r in (comp.rows if all_rows else comp.differences()):
        line = [
            r.rel,
            r.status.value,
            group_notation(r.overall, labels),
            ";".join(r.differing),
            ";".join(f"{labels[i]}:{p}" for i, p in sorted(r.moved.items())),
        ]
        for e, g in zip(r.entries, r.overall):
            if e is None:
                line += [0] + [""] * (len(PER_FOLDER) - 1)
                continue
            line += [
                1, g + 1, e.kind.value, e.size, iso_time(e.mtime_ns) or "", iso_time(e.birth_ns) or "",
                "" if e.mode is None else f"{e.mode:04o}", e.hash or "", e.error or "",
            ]
        w.writerow(line)
