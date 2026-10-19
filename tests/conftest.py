import os
from pathlib import Path

import pytest

BASE_TIME = 1_700_000_000  # fixed mtime so copies match unless a test changes it


def build(root: Path, spec: dict, mtime: int = BASE_TIME) -> Path:
    """Create a tree from {name: str|bytes|dict}; str/bytes are file contents."""
    root.mkdir(parents=True, exist_ok=True)
    for name, value in spec.items():
        path = root / name
        if isinstance(value, dict):
            build(path, value, mtime)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            data = value.encode() if isinstance(value, str) else value
            path.write_bytes(data)
            os.utime(path, (mtime, mtime))
    return root


@pytest.fixture
def make(tmp_path):
    counter = iter(range(1000))

    def _make(spec: dict, mtime: int = BASE_TIME) -> str:
        return str(build(tmp_path / f"d{next(counter)}", spec, mtime))

    return _make
