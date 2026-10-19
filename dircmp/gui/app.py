"""GUI entry point: `dircmp-gui [FOLDER ...]` or `python -m dircmp`."""

from __future__ import annotations

import sys
from pathlib import Path

DESKTOP_ID = "io.github.kapo_toolkits.dircmp"
ICON_PATH = Path(__file__).with_name("resources") / "dircmp.svg"


def main(argv: list[str] | None = None) -> int:
    try:
        from PySide6.QtGui import QIcon
        from PySide6.QtWidgets import QApplication
    except ImportError:
        print("dircmp-gui needs PySide6: pip install 'dircmp[gui]'", file=sys.stderr)
        return 2
    from .main_window import MainWindow

    argv = sys.argv if argv is None else argv
    app = QApplication(argv)
    app.setOrganizationName("kapo-Toolkits")
    app.setApplicationName("dircmp")
    app.setDesktopFileName(DESKTOP_ID)  # lets the taskbar match the window to its launcher
    app.setWindowIcon(QIcon(str(ICON_PATH)))
    folders = [a for a in argv[1:] if not a.startswith("-")]
    window = MainWindow(folders)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
