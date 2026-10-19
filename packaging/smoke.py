"""Smoke-test the binaries built by build.py (run with QT_QPA_PLATFORM=offscreen)."""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

DIST = Path(__file__).resolve().parent.parent / "dist"


def main() -> int:
    exe = ".exe" if sys.platform == "win32" else ""
    cli = DIST / f"dircmp{exe}"
    out = subprocess.run([str(cli), "--version"], capture_output=True, text=True, check=True)
    print(out.stdout.strip())
    rc = subprocess.run([str(cli), str(DIST), str(DIST)], capture_output=True).returncode
    assert rc == 0, f"identical-dir compare returned {rc}"

    if sys.platform == "darwin":
        gui = DIST / "gui" / "dircmp.app" / "Contents" / "MacOS" / "dircmp"
    else:
        gui = DIST / f"dircmp-gui{exe}"
    proc = subprocess.Popen([str(gui)])
    time.sleep(10)  # onefile unpacks first; it must still be running afterwards
    rc = proc.poll()
    proc.kill()
    proc.wait()
    assert rc is None, f"GUI exited early with code {rc}"
    print("GUI started OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
