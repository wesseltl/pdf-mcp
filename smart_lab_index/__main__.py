"""Legacy entry point for LabOverlay via ``python -m smart_lab_index``."""

import multiprocessing

from smart_lab_index.cli import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    raise SystemExit(main())
