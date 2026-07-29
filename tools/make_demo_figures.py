"""Generate placeholder figures so the app runs before you supply an image.

    python tools/make_demo_figures.py

Writes simple full-body cartoon characters to ``assets/pets/demo_*/base.png``
in exactly the format ``extract_figures.py`` produces, so the rest of the
pipeline can be exercised end to end.  Replace them with your own extracted
figures whenever you are ready -- just delete the ``demo_*`` folders, or remove
them from the Character Manager inside the app.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from desktop_pet.pipeline import demo  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(ROOT / "assets" / "pets"))
    args = ap.parse_args()

    for folder in demo.write_demo_figures(Path(args.out)):
        print(f"  {folder / 'base.png'}")

    print("\nnext:  python tools/make_frames.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
