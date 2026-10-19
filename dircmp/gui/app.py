"""GUI entry point: `dircmp-gui [FOLDER ...]` or `python -m dircmp`."""

from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:
        print("dircmp-gui needs PySide6: pip install 'dircmp[gui]'", file=sys.stderr)
        return 2
    from .main_window import MainWindow

    argv = sys.argv if argv is None else argv
    app = QApplication(argv)
    app.setOrganizationName("kapo-Toolkits")
    app.setApplicationName("dircmp")
    folders = [a for a in argv[1:] if not a.startswith("-")]
    window = MainWindow(folders)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
