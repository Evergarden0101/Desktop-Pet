"""Step 1 of the pipeline: pull each person out of a source image.

    python tools/extract_figures.py assets/input/source.png

Produces ``assets/pets/<figure>/base.png`` -- one transparent cutout per
person, with the background and other distractions dropped.

The same code runs inside the app: open the Character Manager (right-click a
pet) and use Import image, which adds a live preview of the cutout.

Background removal uses ``rembg`` when it is installed (much better on real
photos).  Without it we fall back to a border flood fill, which is fine for
images that already have a flat or transparent background.

If two people touch each other the automatic split will merge them; pass
explicit boxes to separate them by hand:

    python tools/extract_figures.py photo.jpg --boxes 10,20,300,900 320,40,610,900
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from desktop_pet.pipeline import extract  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("image", help="source image containing the figures")
    ap.add_argument("--out", default=str(ROOT / "assets" / "pets"),
                    help="output directory (default: assets/pets)")
    ap.add_argument("--max-figures", type=int, default=6)
    ap.add_argument("--min-area", type=float, default=0.004,
                    help="ignore blobs smaller than this fraction of the image")
    ap.add_argument("--height", type=int, default=420,
                    help="normalised cutout height in pixels")
    ap.add_argument("--boxes", nargs="*", default=None,
                    help="manual x0,y0,x1,y1 boxes instead of auto detection")
    ap.add_argument("--no-rembg", action="store_true",
                    help="skip rembg even if installed")
    ap.add_argument("--tolerance", type=int, default=extract.DEFAULT_TOLERANCE,
                    help="flood-fill colour tolerance; raise it if background "
                         "survives, lower it if parts of the figure are eaten")
    args = ap.parse_args()

    src = Path(args.image)
    if not src.exists():
        print(f"error: {src} not found", file=sys.stderr)
        return 1

    boxes = []
    for spec in args.boxes or []:
        nums = [int(v) for v in spec.split(",")]
        if len(nums) != 4:
            print(f"error: bad box {spec!r}, expected x0,y0,x1,y1", file=sys.stderr)
            return 1
        boxes.append(tuple(nums))

    opts = extract.ExtractOptions(
        tolerance=args.tolerance, max_figures=args.max_figures,
        min_area=args.min_area, height=args.height,
        use_rembg=not args.no_rembg, boxes=boxes)

    if not args.no_rembg and not extract.rembg_available():
        print("  rembg not installed -- falling back to border flood fill")
        print("  (pip install rembg onnxruntime  gives far cleaner cutouts)")

    print(f"reading {src}")
    try:
        folders = extract.extract_to_folders(
            Image.open(src), Path(args.out), opts,
            progress=lambda f, m: print(f"  [{f:>4.0%}] {m}"))
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"\nwrote {len(folders)} figure(s)")
    for folder in folders:
        piece = Image.open(folder / "base.png")
        try:
            shown = folder.relative_to(ROOT)
        except ValueError:
            shown = folder  # --out pointed somewhere outside the project
        print(f"  {shown}/base.png  ({piece.width}x{piece.height})")
        for note in extract.cutout_warnings(piece):
            print(f"    warning: {note}")

    print("\nnext:  python tools/make_frames.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
