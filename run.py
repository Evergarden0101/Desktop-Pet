#!/usr/bin/env python3
"""Developer launcher: run the desktop pet straight from a source checkout.

    python run.py                 # run the pet
    python run.py list            # list characters
    python run.py extract art.png # make a character pack

Equivalent to ``python -m desktop_pet`` but doesn't require the package to be
installed (it puts ``src`` on the path first).
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from desktop_pet.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
