"""Build standalone release binaries with PyInstaller.

    pip install -e ".[gui]" pyinstaller
    python packaging/build.py

Outputs go to dist/release/:
    dircmp-<ver>-<os>-<arch>[.exe]          CLI, single file
    dircmp-gui-<ver>-<os>-<arch>[.exe]      GUI, single file (Linux, Windows)
    dircmp-gui-<ver>-macos-<arch>.zip       GUI, zipped dircmp.app (macOS)
"""

from __future__ import annotations

import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HERE = ROOT / "packaging"
BUILD = ROOT / "build" / "pyinstaller"
DIST = ROOT / "dist"
RELEASE = DIST / "release"

sys.path.insert(0, str(ROOT))
from dircmp import __version__  # noqa: E402


def os_tag() -> str:
    return {"win32": "windows", "darwin": "macos"}.get(sys.platform, "linux")


def arch_tag() -> str:
    m = platform.machine().lower()
    return {"amd64": "x86_64", "aarch64": "arm64"}.get(m, m)


def pyinstaller(name: str, script: str, *extra: str) -> None:
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean",
        "--name", name,
        "--distpath", str(DIST),
        "--workpath", str(BUILD),
        "--specpath", str(BUILD),
        "--paths", str(ROOT),
        *extra,
        str(HERE / script),
    ]
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True)


def main() -> int:
    exe = ".exe" if sys.platform == "win32" else ""
    suffix = f"{__version__}-{os_tag()}-{arch_tag()}"
    RELEASE.mkdir(parents=True, exist_ok=True)

    pyinstaller("dircmp", "dircmp_cli.py", "--onefile", "--console",
                "--exclude-module", "PySide6")
    shutil.copy2(DIST / f"dircmp{exe}", RELEASE / f"dircmp-{suffix}{exe}")

    if sys.platform == "darwin":
        # A onefile .app is deprecated by PyInstaller; ship the bundle zipped.
        pyinstaller("dircmp", "dircmp_gui.py", "--windowed",
                    "--osx-bundle-identifier", "io.github.kapo-toolkits.dircmp",
                    "--distpath", str(DIST / "gui"))
        out = RELEASE / f"dircmp-gui-{suffix}.zip"
        subprocess.run(["ditto", "-c", "-k", "--sequesterRsrc", "--keepParent",
                        str(DIST / "gui" / "dircmp.app"), str(out)], check=True)
    else:
        pyinstaller("dircmp-gui", "dircmp_gui.py", "--onefile", "--windowed")
        shutil.copy2(DIST / f"dircmp-gui{exe}", RELEASE / f"dircmp-gui-{suffix}{exe}")

    for f in sorted(RELEASE.iterdir()):
        print(f"{f.stat().st_size / 1e6:8.1f} MB  {f.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
