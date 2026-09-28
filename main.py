"""Run the 3W Real Instances Viewer without installing it: ``uv run main.py [--raw-dir PATH]``."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from overlap_viewer.app import main

if __name__ == "__main__":
    sys.exit(main())
