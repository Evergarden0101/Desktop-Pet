"""Generate placeholder figures so the app runs before you supply an image.

    python tools/make_demo_figures.py

Writes simple full-body cartoon characters to ``assets/pets/demo_*/base.png``
in exactly the format ``extract_figures.py`` produces, so the rest of the
pipeline can be exercised end to end.  Replace them with your own extracted
figures whenever you are ready -- just delete the ``demo_*`` folders.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent

PALETTES = [
    # name,        skin,            hair,            dress,           shoe
    ("demo_01", (245, 214, 190), (72, 48, 44), (226, 118, 148), (92, 74, 96)),
    ("demo_02", (238, 200, 172), (124, 88, 52), (118, 158, 220), (78, 84, 104)),
]


def draw_figure(skin, hair, dress, shoe) -> Image.Image:
    W, H = 260, 448
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    cx = W // 2

    # legs (drawn first so the hem overlaps them)
    for x0 in (cx - 26, cx + 4):
        d.rounded_rectangle([x0, 292, x0 + 22, 424], radius=10, fill=skin)
        d.rounded_rectangle([x0 - 2, 410, x0 + 24, 436], radius=9, fill=shoe)

    # dress: shoulders -> waist -> hem
    d.polygon([(cx - 38, 104), (cx + 38, 104), (cx + 26, 212),
               (cx + 44, 302), (cx - 44, 302), (cx - 26, 212)], fill=dress)
    # collar
    d.polygon([(cx - 16, 104), (cx + 16, 104), (cx, 126)], fill=tuple(
        max(0, c - 30) for c in dress))

    # neck
    d.rectangle([cx - 10, 88, cx + 10, 108], fill=skin)

    # head
    d.ellipse([cx - 40, 12, cx + 40, 100], fill=skin)
    # hair: cap plus two side locks
    d.chord([cx - 44, 4, cx + 44, 84], 180, 360, fill=hair)
    d.ellipse([cx - 46, 26, cx - 26, 120], fill=hair)
    d.ellipse([cx + 26, 26, cx + 46, 120], fill=hair)

    # face
    for ex in (cx - 16, cx + 16):
        d.ellipse([ex - 5, 54, ex + 5, 66], fill=(48, 40, 44))
    d.arc([cx - 10, 68, cx + 10, 82], 200, 340, fill=(180, 96, 104), width=3)

    return img


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(ROOT / "assets" / "pets"))
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    for name, skin, hair, dress, shoe in PALETTES:
        folder = out / name
        folder.mkdir(exist_ok=True)
        img = draw_figure(skin, hair, dress, shoe)
        bbox = img.getbbox()
        img.crop(bbox).save(folder / "base.png")
        print(f"  {folder / 'base.png'}")

    print("\nnext:  python tools/make_frames.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
