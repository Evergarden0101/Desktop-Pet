"""Step 2 of the pipeline: turn each static cutout into animation frames.

    python tools/make_frames.py

For every ``assets/pets/<name>/base.png`` this builds an 8 frame crawl cycle,
a 6 frame play cycle, and a ``meta.json`` holding the frame list, the fps and
the head anchor per frame.

The Character Manager inside the app runs the same code whenever you import an
image or press Rebuild.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from desktop_pet.pipeline import frames  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pets", default=str(ROOT / "assets" / "pets"))
    ap.add_argument("--only", default=None, help="build a single figure folder")
    args = ap.parse_args()

    root = Path(args.pets)
    folders = sorted(p for p in root.iterdir()
                     if p.is_dir() and (p / "base.png").exists()) if root.exists() else []
    if args.only:
        folders = [p for p in folders if p.name == args.only]

    if not folders:
        print(f"no figures with base.png under {root}\n"
              f"run tools/extract_figures.py first, or tools/make_demo_figures.py "
              f"for placeholders", file=sys.stderr)
        return 1

    print(f"building {len(folders)} figure(s)")
    built = frames.build_all(folders, verbose=True)

    if len(built) < len(folders):
        failed = {f.name for f in folders} - {f.name for f in built}
        print(f"\nfailed: {', '.join(sorted(failed))}", file=sys.stderr)

    print("\nnext:  python run.py")
    return 0 if built else 1


if __name__ == "__main__":
    raise SystemExit(main())
