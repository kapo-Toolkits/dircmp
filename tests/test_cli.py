import csv
import io
import json

from dircmp.cli import main


def test_exit_codes(make, capsys):
    a = make({"f": "x"})
    b = make({"f": "x"})
    c = make({"f": "y"})
    assert main([a, b]) == 0
    assert main([a, b, c]) == 1
    assert main([a, "/nonexistent/dircmp"]) == 2
    out = capsys.readouterr()
    assert "A=B ≠ C" in out.out
    assert "error" in out.err


def test_text_verbose_and_matrix(make, capsys):
    a, b, c = make({"f": "x"}), make({"f": "y"}), make({"f": "x"})
    main([a, b, c, "-v", "--color", "never"])
    out = capsys.readouterr().out
    assert "შიგთავსი (ჰეში): A,C = " in out
    assert "მატრიცა" in out


def test_json(make, tmp_path):
    a = make({"f": "x", "g": "1"})
    b = make({"f": "y"})
    out = tmp_path / "r.json"
    assert main([a, b, "-f", "json", "-o", str(out)]) == 1
    data = json.loads(out.read_text(encoding="utf-8"))
    assert [f["label"] for f in data["folders"]] == ["A", "B"]
    paths = {r["path"]: r for r in data["rows"]}
    assert paths["f"]["groups"]["content"] == [["A"], ["B"]]
    assert paths["g"]["entries"][1] is None
    assert data["summary"]["total"] == 2

    main([a, b, "-f", "json", "-o", str(out), "--all"])
    assert len(json.loads(out.read_text(encoding="utf-8"))["rows"]) == 2


def test_csv(make, capsys):
    a, b, c = make({"f": "x"}), make({"f": "x"}), make({"f": "zz"})
    main([a, b, c, "-f", "csv"])
    rows = list(csv.DictReader(io.StringIO(capsys.readouterr().out)))
    assert rows[0]["path"] == "f"
    assert rows[0]["groups"] == "A=B ≠ C"
    assert rows[0]["C_size"] == "2"


def test_fields_option(make, capsys):
    a = make({"f": "x"}, mtime=1_000_000_000)
    b = make({"f": "x"}, mtime=1_500_000_000)
    assert main([a, b]) == 1
    assert main([a, b, "--fields", "kind,size,content"]) == 0
    assert main([a, b, "--fields", "bogus"]) == 2
