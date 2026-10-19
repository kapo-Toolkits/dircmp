import os
import sys
import unicodedata

import pytest

from dircmp.core import Mode, Options, Status, compare, label
from dircmp.core import hashing
from dircmp.core.fields import group_notation

SPEC = {"a.txt": "alpha", "sub": {"b.txt": "beta", "deep": {"c.bin": b"\x00\x01"}}}


def row(comp, rel):
    return next(r for r in comp.rows if r.rel == rel)


def test_labels_unbounded():
    assert [label(i) for i in (0, 1, 25, 26, 27, 701, 702)] == ["A", "B", "Z", "AA", "AB", "ZZ", "AAA"]


def test_needs_two_folders(make):
    with pytest.raises(ValueError):
        compare([make(SPEC)])
    with pytest.raises(ValueError):
        compare([make(SPEC), "/nonexistent/dircmp-test"])


def test_identical_two(make):
    comp = compare([make(SPEC), make(SPEC)])
    assert comp.all_identical
    assert comp.summary()["total"] == 5
    assert [r.rel for r in comp.rows] == ["a.txt", "sub", "sub/b.txt", "sub/deep", "sub/deep/c.bin"]


def test_many_identical_folders(make):
    roots = [make(SPEC) for _ in range(6)]
    comp = compare(roots)
    assert comp.all_identical
    assert all(r.overall == [0] * 6 for r in comp.rows)


def test_three_way_groups(make):
    a = make({"f.txt": "one"})
    b = make({"f.txt": "two"})  # same size, different content
    c = make({"f.txt": "one"})
    r = row(compare([a, b, c]), "f.txt")
    assert r.status is Status.CONTENT_DIFFERS
    assert r.groups["content"] == [[0, 2], [1]]
    assert r.groups["size"] == [[0, 1, 2]]
    assert r.overall == [0, 1, 0]
    assert group_notation(r.overall, ["A", "B", "C"]) == "A=C ≠ B"


def test_four_way_partial(make):
    a = make({"x": "1", "only_ac": "z"})
    b = make({"x": "1"})
    c = make({"x": "1", "only_ac": "z"})
    d = make({"x": "1"})
    comp = compare([a, b, c, d])
    r = row(comp, "only_ac")
    assert r.status is Status.PARTIAL
    assert r.presence == [True, False, True, False]
    assert r.overall == [0, None, 0, None]
    assert group_notation(r.overall, list("ABCD")) == "A=C  ∅ B,D"
    m = comp.distance_matrix()
    assert m[0][2] == 0 and m[0][1] == 1 and m[1][3] == 0


def test_size_difference_without_hashing(make):
    r = row(compare([make({"f": "short"}), make({"f": "much longer"})]), "f")
    assert r.status is Status.CONTENT_DIFFERS
    assert "size" in r.differing
    assert all(e.hash is None for e in r.entries)  # unique sizes need no hash


def test_metadata_only_and_tolerance(make):
    a = make({"f": "same"}, mtime=1_700_000_000)
    b = make({"f": "same"}, mtime=1_700_000_001)
    assert row(compare([a, b]), "f").status is Status.METADATA_DIFFERS
    assert row(compare([a, b], Options(time_tolerance=2)), "f").status is Status.IDENTICAL


def test_time_groups_do_not_chain(make):
    roots = [make({"f": "x"}, mtime=t) for t in (100, 101, 102)]
    r = row(compare(roots, Options(time_tolerance=1.5)), "f")
    # 100 and 101 are within 1.5 s, 102 is 2 s from the group start -> new group
    assert r.groups["mtime"] == [[0, 1], [2]]


def test_kind_change(make):
    a = make({"thing": "file"})
    b = make({"thing": {"inner": "x"}})
    comp = compare([a, b])
    assert row(comp, "thing").status is Status.CONTENT_DIFFERS
    assert row(comp, "thing").differing[0] == "kind"
    assert row(comp, "thing/inner").status is Status.PARTIAL


def test_moved_file(make):
    a = make({"old": {"report.pdf": "PDFDATA-1234"}})
    b = make({"old": {"report.pdf": "PDFDATA-1234"}})
    c = make({"old": {}, "new": {"renamed.pdf": "PDFDATA-1234"}})
    comp = compare([a, b, c])
    src = row(comp, "old/report.pdf")
    assert src.status is Status.MOVED
    assert src.moved == {2: "new/renamed.pdf"}
    dst = row(comp, "new/renamed.pdf")
    assert dst.status is Status.MOVED
    assert dst.moved == {0: "old/report.pdf", 1: "old/report.pdf"}


def test_moves_can_be_disabled(make):
    a = make({"p": "content!"})
    b = make({"q": "content!"})
    comp = compare([a, b], Options(detect_moves=False))
    assert {r.status for r in comp.rows} == {Status.PARTIAL}


def test_empty_files_are_not_moves(make):
    comp = compare([make({"e1": ""}), make({"e2": ""})])
    assert {r.status for r in comp.rows} == {Status.PARTIAL}


def test_quick_mode_skips_content(make):
    a = make({"f": "aaaa"})
    b = make({"f": "bbbb"})
    assert row(compare([a, b], Options(mode=Mode.QUICK)), "f").status is Status.IDENTICAL
    assert row(compare([a, b]), "f").status is Status.CONTENT_DIFFERS


def test_deep_mode_hashes_everything(make):
    comp = compare([make({"f": "x", "g": "longer"}), make({"f": "y"})], Options(mode=Mode.DEEP))
    assert all(e.hash.startswith("f:") for r in comp.rows for e in r.entries if e is not None)


def test_partial_hash_path(make, monkeypatch):
    monkeypatch.setattr(hashing, "PARTIAL_THRESHOLD", 100)
    monkeypatch.setattr(hashing, "PARTIAL_CHUNK", 16)
    body = b"x" * 200
    a = make({"big": body, "diffhead": b"A" + body})
    b = make({"big": body[:100] + b"Y" + body[101:], "diffhead": b"B" + body})
    comp = compare([a, b])
    r_mid = row(comp, "big")  # head/tail equal -> needs full hash
    assert r_mid.status is Status.CONTENT_DIFFERS
    assert all(e.hash.startswith("f:") for e in r_mid.entries)
    r_head = row(comp, "diffhead")  # partial hash alone proves the difference
    assert r_head.status is Status.CONTENT_DIFFERS
    assert all(e.hash.startswith("p:") for e in r_head.entries)


def test_ignore_patterns(make):
    a = make({"keep.txt": "1", "skip.log": "a", "build": {"out.o": "x"}, "src": {"tmp": {"t": "1"}}})
    b = make({"keep.txt": "1", "skip.log": "b", "build": {"out.o": "y"}, "src": {}})
    comp = compare([a, b], Options(ignore=["*.log", "build", "src/tmp"]))
    assert comp.all_identical, [(r.rel, r.status) for r in comp.differences()]


def test_hidden(make):
    a = make({".hidden": "1", "v": "x"})
    b = make({"v": "x"})
    assert not compare([a, b]).all_identical
    assert compare([a, b], Options(exclude_hidden=True)).all_identical


def test_case_insensitive(make):
    a = make({"README.md": "x"})
    b = make({"readme.md": "x"})
    if os.path.exists(os.path.join(a, "readme.md")):
        pytest.skip("case-insensitive filesystem")
    assert not compare([a, b]).all_identical
    comp = compare([a, b], Options(case_insensitive=True))
    assert comp.all_identical and comp.rows[0].rel == "README.md"


@pytest.mark.skipif(sys.platform == "darwin", reason="APFS normalizes names itself")
def test_unicode_normalization(make):
    nfc = unicodedata.normalize("NFC", "café.txt")
    nfd = unicodedata.normalize("NFD", "café.txt")
    a = make({nfc: "x"})
    b = make({nfd: "x"})
    assert compare([a, b]).all_identical
    assert not compare([a, b], Options(normalize_unicode=False)).all_identical


@pytest.mark.skipif(os.name == "nt", reason="symlinks need privileges on Windows")
def test_symlinks(make):
    a = make({"target1": "x", "target2": "y", "d": {"f": "z"}})
    b = make({"target1": "x", "target2": "y", "d": {"f": "z"}})
    os.symlink("target1", os.path.join(a, "link"))
    os.symlink("target2", os.path.join(b, "link"))
    os.symlink("..", os.path.join(a, "d", "loop"))
    os.symlink("..", os.path.join(b, "d", "loop"))
    comp = compare([a, b])
    r = row(comp, "link")
    assert r.status is Status.CONTENT_DIFFERS and r.differing == ["link_target"]
    assert row(comp, "d/loop").status is Status.IDENTICAL
    # following links must terminate despite the loop
    followed = compare([a, b], Options(follow_symlinks=True))
    assert row(followed, "link").status is Status.CONTENT_DIFFERS  # x vs y content
    assert any("already visited" in e.message for e in followed.errors)


@pytest.mark.skipif(os.name == "nt" or (hasattr(os, "geteuid") and os.geteuid() == 0),
                    reason="needs POSIX permissions and a non-root user")
def test_unreadable_file(make):
    a = make({"secret": "1234", "ok": "x"})
    b = make({"secret": "5678", "ok": "x"})
    os.chmod(os.path.join(a, "secret"), 0)
    try:
        comp = compare([a, b])
    finally:
        os.chmod(os.path.join(a, "secret"), 0o644)
    r = row(comp, "secret")
    assert r.status is Status.ERROR
    assert "read failed" in r.entries[0].error
    assert row(comp, "ok").status is Status.IDENTICAL


@pytest.mark.skipif(os.name == "nt", reason="POSIX permissions")
def test_permissions(make):
    a = make({"f": "x"})
    b = make({"f": "x"})
    os.chmod(os.path.join(b, "f"), 0o600)
    os.chmod(os.path.join(a, "f"), 0o644)
    r = row(compare([a, b]), "f")
    assert r.status is Status.METADATA_DIFFERS and r.differing == ["mode"]


def test_birth_time_is_int_or_unavailable(make):
    comp = compare([make({"f": "x"}), make({"f": "x"})])
    for e in comp.rows[0].entries:
        assert e.birth_ns is None or isinstance(e.birth_ns, int)


def test_progress_and_cancel(make):
    import threading
    from dircmp.core import Cancelled

    roots = [make(SPEC), make(SPEC)]
    phases = []
    compare(roots, progress=lambda p, d, t: phases.append(p))
    assert {"scan", "hash", "diff"} <= set(phases)

    ev = threading.Event()
    ev.set()
    with pytest.raises(Cancelled):
        compare(roots, cancel=ev)
