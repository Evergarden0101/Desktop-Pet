#!/usr/bin/env python3
"""Generate a simple textured mascot PNG to demonstrate body-part extraction.

This draws a friendly humanoid on a transparent canvas with each body region in
a distinct colour, so the extractor (and the resulting rig) are easy to see.
Run it, then turn the PNG into a character pack::

    python tools/make_sample_character.py --out mascot.png
    desktop-pet extract mascot.png --name Mascot

Requires Pillow (``pip install Pillow``).
"""

from __future__ import annotations

import argparse

from PIL import Image, ImageDraw


def draw_mascot(width: int = 260, height: int = 520) -> Image.Image:
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    cx = width // 2

    skin = (255, 217, 160, 255)
    shirt = (79, 140, 255, 255)
    pants = (47, 53, 80, 255)
    shoe = (31, 34, 51, 255)
    outline = (43, 43, 58, 255)

    def limb(box, fill):
        d.rounded_rectangle(box, radius=18, fill=fill, outline=outline, width=3)

    # Head
    d.ellipse([cx - 46, 12, cx + 46, 104], fill=skin, outline=outline, width=3)
    d.ellipse([cx - 20, 48, cx - 8, 64], fill=outline)   # eyes
    d.ellipse([cx + 8, 48, cx + 20, 64], fill=outline)
    d.arc([cx - 18, 60, cx + 18, 88], start=20, end=160, fill=outline, width=3)  # smile

    # Torso + hips
    limb([cx - 48, 104, cx + 48, 250], shirt)
    limb([cx - 46, 236, cx + 46, 292], pants)

    # Arms (down the sides)
    limb([cx - 84, 116, cx - 48, 232], skin)   # left arm
    limb([cx + 48, 116, cx + 84, 232], skin)   # right arm

    # Legs
    limb([cx - 44, 288, cx - 6, 470], pants)   # left leg
    limb([cx + 6, 288, cx + 44, 470], pants)   # right leg

    # Feet
    limb([cx - 52, 456, cx - 2, 500], shoe)
    limb([cx + 2, 456, cx + 52, 500], shoe)
    return img


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="mascot.png", help="Output PNG path.")
    parser.add_argument("--width", type=int, default=260)
    parser.add_argument("--height", type=int, default=520)
    args = parser.parse_args()

    img = draw_mascot(args.width, args.height)
    img.save(args.out)
    print(f"Wrote {args.out} ({img.width}x{img.height})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
