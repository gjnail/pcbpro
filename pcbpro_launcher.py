"""Entry point used by the Windows executable build (PyInstaller) and the Start menu shortcut."""
import multiprocessing
import sys

from pcbpro.app import main

if __name__ == "__main__":
    multiprocessing.freeze_support()  # the simulation runs in a worker process
    sys.exit(main())
