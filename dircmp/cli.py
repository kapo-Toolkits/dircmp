"""Command-line interface. Exit codes: 0 identical, 1 differences, 2 error."""

from __future__ import annotations

import argparse
import os
import sys

from . import __version__
from .core import ALL_FIELDS, Mode, Options, compare
from .report import render_text, write_csv, write_json

EXIT_SAME, EXIT_DIFF, EXIT_ERROR = 0, 1, 2


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="dircmp",
        description="Deep, read-only comparison of two or more directories.",
        epilog="Exit codes: 0 = all identical, 1 = differences found, 2 = error.",
    )
    p.add_argument("folders", nargs="+", metavar="FOLDER", help="two or more folders (labelled A, B, C, ...)")
    p.add_argument("-m", "--mode", choices=[m.value for m in Mode], default=Mode.STANDARD.value,
                   help="quick: size+mtime; standard (default): + content hash, permissions; deep: + full hashes, xattrs")
    p.add_argument("-i", "--ignore", action="append", default=[], metavar="GLOB",
                   help="ignore names/paths matching GLOB (repeatable; patterns with '/' match the relative path)")
    p.add_argument("--exclude-hidden", action="store_true", help="skip dotfiles and Windows hidden files")
    p.add_argument("--follow-symlinks", action="store_true", help="follow symlinks/junctions (cycle-safe)")
    p.add_argument("--case-insensitive", action="store_true", help="match paths ignoring case")
    p.add_argument("--no-unicode-normalize", action="store_true", help="don't treat NFC/NFD spellings as equal")
    p.add_argument("-t", "--time-tolerance", type=float, default=0.0, metavar="SEC",
                   help="timestamps within SEC seconds count as equal (e.g. 2 for FAT)")
    p.add_argument("--fields", metavar="LIST",
                   help=f"comma-separated fields that decide status; available: {','.join(ALL_FIELDS)}")
    p.add_argument("--no-moves", action="store_true", help="don't detect moved/renamed files")
    p.add_argument("-j", "--threads", type=int, default=0, metavar="N", help="hashing threads (default: auto)")
    p.add_argument("-f", "--format", choices=["text", "json", "csv"], default="text")
    p.add_argument("-o", "--output", metavar="FILE", help="write report to FILE instead of stdout")
    p.add_argument("-a", "--all", action="store_true", help="include identical entries in the report")
    p.add_argument("-v", "--verbose", action="store_true", help="text: show differing values per folder")
    p.add_argument("--color", choices=["auto", "always", "never"], default="auto")
    p.add_argument("--version", action="version", version=f"dircmp {__version__}")
    return p


def options_from_args(a: argparse.Namespace) -> Options:
    fields = None
    if a.fields:
        fields = tuple(f.strip() for f in a.fields.split(",") if f.strip())
        unknown = [f for f in fields if f not in ALL_FIELDS]
        if unknown:
            raise ValueError(f"unknown field(s): {', '.join(unknown)}")
    return Options(
        mode=Mode(a.mode),
        ignore=a.ignore,
        exclude_hidden=a.exclude_hidden,
        follow_symlinks=a.follow_symlinks,
        case_insensitive=a.case_insensitive,
        normalize_unicode=not a.no_unicode_normalize,
        time_tolerance=a.time_tolerance,
        threads=a.threads,
        compare_fields=fields,
        detect_moves=not a.no_moves,
    )


def _progress(phase: str, done: int, total: int) -> None:
    text = f"{phase}: {done}" + (f"/{total}" if total else "")
    sys.stderr.write(f"\r\033[K{text}")
    sys.stderr.flush()


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    a = parser.parse_args(argv)
    if len(a.folders) < 2:
        parser.error("need at least two folders")
    try:
        opts = options_from_args(a)
        show_progress = sys.stderr.isatty()
        comp = compare(a.folders, opts, progress=_progress if show_progress else None)
        if show_progress:
            sys.stderr.write("\r\033[K")
    except KeyboardInterrupt:
        return EXIT_ERROR
    except (ValueError, OSError) as exc:
        print(f"dircmp: error: {exc}", file=sys.stderr)
        return EXIT_ERROR

    out = open(a.output, "w", encoding="utf-8", newline="") if a.output else sys.stdout
    try:
        if a.format == "json":
            write_json(comp, out, all_rows=a.all)
        elif a.format == "csv":
            write_csv(comp, out, all_rows=a.all)
        else:
            color = a.color == "always" or (a.color == "auto" and out.isatty() and "NO_COLOR" not in os.environ)
            out.write(render_text(comp, all_rows=a.all, verbose=a.verbose, color=color))
    finally:
        if out is not sys.stdout:
            out.close()

    if comp.errors:
        return EXIT_ERROR
    return EXIT_SAME if comp.all_identical else EXIT_DIFF


if __name__ == "__main__":
    sys.exit(main())
