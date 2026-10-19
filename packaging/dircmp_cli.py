"""PyInstaller entry point for the `dircmp` CLI binary."""

import sys

from dircmp.cli import main

sys.exit(main())
