"""Entry point of the packaged desktop program (see opticore/desktop.py)."""

import multiprocessing
import sys

if __name__ == "__main__":
    # the process pool starts its workers through this executable: they must not start the program again
    multiprocessing.freeze_support()
    from opticore.desktop import main

    sys.exit(main())
