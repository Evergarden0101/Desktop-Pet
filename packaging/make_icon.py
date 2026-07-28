#!/usr/bin/env python3
"""Generate app.ico / app.png for the executable, installer and README.

Draws the same little mascot face the in-app tray icon uses. Run from the repo
root::

    python packaging/make_icon.py
"""

from __future__ import annotations

import os

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))


def draw_icon(size: int = 256) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    s = size

    # Rounded blue badge.
    pad = int(s * 0.06)
    d.rounded_rectangle(
        [pad, pad, s - pad, s - pad],
        radius=int(s * 0.28),
        fill=(79, 140, 255, 255),
    )

    cx = cy = s / 2
    face_r = s * 0.26
    d.ellipse(
        [cx - face_r, cy - face_r * 1.05, cx + face_r, cy + face_r * 0.95],
        fill=(255, 217, 160, 255),
        outline=(43, 43, 58, 255),
        width=max(2, int(s * 0.012)),
    )

    eye_dx = s * 0.10
    eye_w = s * 0.032
    eye_h = eye_w * 1.4
    for sign in (-1, 1):
        ex = cx + sign * eye_dx
        d.ellipse([ex - eye_w, cy - eye_h, ex + eye_w, cy + eye_h], fill=(43, 43, 58, 255))

    # Cheeks.
    for sign in (-1, 1):
        chx = cx + sign * eye_dx * 1.7
        d.ellipse(
            [chx - eye_w, cy + s * 0.03, chx + eye_w, cy + s * 0.03 + eye_w * 1.4],
            fill=(255, 158, 158, 255),
        )
    return img


def main() -> int:
    base = draw_icon(256)
    png_path = os.path.join(HERE, "app.png")
    ico_path = os.path.join(HERE, "app.ico")
    base.save(png_path)
    base.save(
        ico_path,
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    print(f"Wrote {png_path} and {ico_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
