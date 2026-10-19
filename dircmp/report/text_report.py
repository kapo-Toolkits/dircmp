"""Plain/ANSI terminal report."""

from __future__ import annotations

from ..core.compare import Comparison
from ..core.fields import FIELD_NAMES, STATUS_NAMES, group_notation, value_text
from ..core.model import Kind, Status

_COLORS = {
    Status.IDENTICAL: "32",
    Status.CONTENT_DIFFERS: "31",
    Status.METADATA_DIFFERS: "33",
    Status.PARTIAL: "36",
    Status.MOVED: "35",
    Status.ERROR: "1;31",
}


def render_text(comp: Comparison, *, all_rows: bool = False, verbose: bool = False,
                color: bool = False) -> str:
    def c(text: str, code: str) -> str:
        return f"\033[{code}m{text}\033[0m" if color else text

    labels = comp.labels
    out = [f"dircmp — {len(comp.roots)} საქაღალდე, {len(comp.rows)} ჩანაწერი, "
           f"რეჟიმი: {comp.options.mode.value}, {comp.elapsed:.2f} წმ"]
    for lab, root in zip(labels, comp.roots):
        out.append(f"  {c(lab, '1')}  {root}")

    out.append("")
    out.append("შეჯამება:")
    summary = comp.summary()
    width = max(len(n) for n in STATUS_NAMES.values())
    for status, name in STATUS_NAMES.items():
        n = summary[status.value]
        line = f"  {name:<{width}}  {n:>8}"
        out.append(c(line, _COLORS[status]) if n and status is not Status.IDENTICAL else line)

    rows = comp.rows if all_rows else comp.differences()
    if rows:
        out.append("")
        out.append("ყველა ჩანაწერი:" if all_rows else "განსხვავებები:")
    for r in rows:
        path = r.rel + ("/" if r.kind is Kind.DIR else "")
        detail = group_notation(r.overall, labels)
        if r.differing:
            detail += "   (" + ", ".join(r.differing) + ")"
        out.append(f"  {c(f'[{STATUS_NAMES[r.status]}]', _COLORS[r.status])} {path}   {detail}")
        for i, target in sorted(r.moved.items()):
            out.append(f"      → {labels[i]}: {target}")
        if verbose:
            for f in r.differing:
                parts = []
                for g in r.groups[f]:
                    parts.append(",".join(labels[i] for i in g) + " = " + value_text(f, r.entries[g[0]]))
                out.append(f"      {FIELD_NAMES[f]}: " + " | ".join(parts))
            for i, e in enumerate(r.entries):
                if e is not None and e.error:
                    out.append(f"      {labels[i]}: ⚠ {e.error}")

    if comp.errors:
        out.append("")
        out.append(c(f"შეცდომები ({len(comp.errors)}):", "1;31"))
        for e in comp.errors:
            out.append(f"  {labels[e.folder]}: {e.rel}: {e.message}")

    if len(comp.roots) > 2:
        out.append("")
        out.append("განსხვავებების მატრიცა (რამდენ გზაზე არ ემთხვევა ერთმანეთს):")
        m = comp.distance_matrix()
        w = max(4, *(len(str(v)) for row in m for v in row))
        out.append("    " + "".join(f"{lab:>{w + 1}}" for lab in labels))
        for lab, row in zip(labels, m):
            out.append(f"  {lab:>2}" + "".join(f"{v:>{w + 1}}" for v in row))
    return "\n".join(out) + "\n"
