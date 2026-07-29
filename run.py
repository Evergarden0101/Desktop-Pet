#!/usr/bin/env python3
"""Run the desktop pet straight from the source tree."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from desktop_pet.app import main  # noqa: E402

raise SystemExit(main())
