"""Step 1 of the pipeline: pull each person out of a source image.

    python tools/extract_figures.py assets/input/source.png

Produces ``assets/pets/<figure>/base.png`` -- one transparent cutout per
person, with the background and other distractions dropped.

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
from collections import deque
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))


# --------------------------------------------------------------------------
# background removal
# --------------------------------------------------------------------------

def remove_background(img: Image.Image, force_fallback: bool = False,
                      tolerance: int = 18) -> Image.Image:
    """Return an RGBA image whose alpha keeps only the subject(s)."""
    if img.mode == "RGBA" and np.asarray(img)[..., 3].min() < 250:
        print("  source already has transparency, using it as-is")
        return img

    if not force_fallback:
        try:
            import rembg  # type: ignore

            print("  running rembg (u2net) ...")
            return rembg.remove(img.convert("RGBA"))
        except ImportError:
            print("  rembg not installed -- falling back to border flood fill")
            print("  (pip install rembg onnxruntime  gives far cleaner cutouts)")

    return _flood_fill_background(img.convert("RGB"), tolerance)


def _flood_fill_background(img: Image.Image, tolerance: int = 18) -> Image.Image:
    """Flood fill inward from the border, treating similar colours as background."""
    arr = np.asarray(img).astype(np.int16)
    h, w = arr.shape[:2]
    bg = np.zeros((h, w), dtype=bool)

    seeds = deque()
    for x in range(w):
        seeds.append((0, x))
        seeds.append((h - 1, x))
    for y in range(h):
        seeds.append((y, 0))
        seeds.append((y, w - 1))

    border = np.concatenate([arr[0], arr[-1], arr[:, 0], arr[:, -1]])
    ref = np.median(border, axis=0)

    close = (np.abs(arr - ref).sum(axis=2) <= tolerance * 3)

    while seeds:
        y, x = seeds.popleft()
        if bg[y, x] or not close[y, x]:
            continue
        bg[y, x] = True
        if y > 0:
            seeds.append((y - 1, x))
        if y < h - 1:
            seeds.append((y + 1, x))
        if x > 0:
            seeds.append((y, x - 1))
        if x < w - 1:
            seeds.append((y, x + 1))

    out = Image.fromarray(np.dstack([arr.astype(np.uint8),
                                     np.where(bg, 0, 255).astype(np.uint8)]), "RGBA")
    return out


# --------------------------------------------------------------------------
# splitting the mask into separate people
# --------------------------------------------------------------------------

def label_components(mask: np.ndarray, max_side: int = 480):
    """Label connected blobs.  Works on a downscaled mask, then upsamples."""
    h, w = mask.shape
    scale = max(1.0, max(h, w) / max_side)
    sh, sw = max(1, int(h / scale)), max(1, int(w / scale))
    small = np.asarray(Image.fromarray(mask.astype(np.uint8) * 255)
                       .resize((sw, sh), Image.BILINEAR)) > 127

    labels = np.zeros((sh, sw), dtype=np.int32)
    current = 0
    for y0 in range(sh):
        for x0 in range(sw):
            if not small[y0, x0] or labels[y0, x0]:
                continue
            current += 1
            q = deque([(y0, x0)])
            labels[y0, x0] = current
            while q:
                y, x = q.popleft()
                for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1),
                               (1, 1), (1, -1), (-1, 1), (-1, -1)):
                    ny, nx = y + dy, x + dx
                    if 0 <= ny < sh and 0 <= nx < sw and small[ny, nx] and not labels[ny, nx]:
                        labels[ny, nx] = current
                        q.append((ny, nx))

    big = np.asarray(Image.fromarray(labels.astype(np.uint8))
                     .resize((w, h), Image.NEAREST)).astype(np.int32)
    big[~mask] = 0
    return big, current


def figure_boxes(rgba: Image.Image, max_figures: int, min_area_frac: float):
    """Bounding boxes of the plausible human blobs, left to right."""
    alpha = np.asarray(rgba)[..., 3]
    mask = alpha > 32
    labels, count = label_components(mask)

    total = mask.shape[0] * mask.shape[1]
    blobs = []
    for i in range(1, count + 1):
        sel = labels == i
        area = int(sel.sum())
        if area < total * min_area_frac:
            continue  # a distraction: prop, watermark, speckle
        ys, xs = np.nonzero(sel)
        x0, x1 = int(xs.min()), int(xs.max()) + 1
        y0, y1 = int(ys.min()), int(ys.max()) + 1
        h = y1 - y0
        w = x1 - x0
        if h < w * 0.6:
            continue  # too wide to be a standing person: furniture, text banner
        blobs.append((area, (x0, y0, x1, y1)))

    blobs.sort(key=lambda b: -b[0])
    blobs = blobs[:max_figures]
    blobs.sort(key=lambda b: b[1][0])
    return [b[1] for b in blobs]


def crop_figure(rgba: Image.Image, box, pad_frac: float = 0.04) -> Image.Image:
    x0, y0, x1, y1 = box
    pad = int(max(x1 - x0, y1 - y0) * pad_frac)
    x0, y0 = max(0, x0 - pad), max(0, y0 - pad)
    x1, y1 = min(rgba.width, x1 + pad), min(rgba.height, y1 + pad)

    piece = rgba.crop((x0, y0, x1, y1)).copy()

    # drop anything in this crop that is not connected to the main blob, so a
    # neighbour's elbow or a background prop does not ride along.
    arr = np.asarray(piece)
    labels, count = label_components(arr[..., 3] > 32)
    if count > 1:
        sizes = [(int((labels == i).sum()), i) for i in range(1, count + 1)]
        keep = max(sizes)[1]
        cleaned = arr.copy()
        cleaned[..., 3] = np.where(labels == keep, cleaned[..., 3], 0)
        piece = Image.fromarray(cleaned, "RGBA")

    bbox = piece.getbbox()
    return piece.crop(bbox) if bbox else piece


def normalize_height(img: Image.Image, target_h: int) -> Image.Image:
    if img.height == target_h:
        return img
    scale = target_h / img.height
    return img.resize((max(1, int(img.width * scale)), target_h), Image.LANCZOS)


# --------------------------------------------------------------------------

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
    ap.add_argument("--tolerance", type=int, default=18,
                    help="flood-fill colour tolerance; raise it if background "
                         "survives, lower it if parts of the figure are eaten")
    args = ap.parse_args()

    src = Path(args.image)
    if not src.exists():
        print(f"error: {src} not found", file=sys.stderr)
        return 1

    print(f"reading {src}")
    img = Image.open(src)
    img = img.convert("RGBA") if img.mode != "RGBA" else img

    rgba = remove_background(img, force_fallback=args.no_rembg,
                             tolerance=args.tolerance)

    if args.boxes:
        boxes = []
        for spec in args.boxes:
            nums = [int(v) for v in spec.split(",")]
            if len(nums) != 4:
                print(f"error: bad box {spec!r}, expected x0,y0,x1,y1", file=sys.stderr)
                return 1
            boxes.append(tuple(nums))
    else:
        boxes = figure_boxes(rgba, args.max_figures, args.min_area)

    if not boxes:
        print("error: no figures found. Try --no-rembg, a lower --min-area, "
              "or pass --boxes by hand.", file=sys.stderr)
        return 1

    out_root = Path(args.out)
    out_root.mkdir(parents=True, exist_ok=True)

    print(f"found {len(boxes)} figure(s)")
    for i, box in enumerate(boxes, start=1):
        piece = normalize_height(crop_figure(rgba, box), args.height)
        folder = out_root / f"figure_{i:02d}"
        folder.mkdir(parents=True, exist_ok=True)
        dest = folder / "base.png"
        piece.save(dest)
        try:
            shown = dest.relative_to(ROOT)
        except ValueError:
            shown = dest  # --out pointed somewhere outside the project
        print(f"  {shown}  ({piece.width}x{piece.height})")

        # a standing person is a tall, sparse silhouette; anything else usually
        # means the background removal ate the legs or kept a slab of backdrop
        ratio = piece.height / max(1, piece.width)
        fill = float((np.asarray(piece)[..., 3] > 32).mean())
        if ratio < 1.6:
            print(f"    warning: this cutout is short and wide (h/w={ratio:.1f}). "
                  f"Legs may have been cut off -- try a lower --tolerance, "
                  f"or install rembg.")
        if fill > 0.85:
            print(f"    warning: {fill:.0%} of the crop is opaque, so background "
                  f"probably survived -- try a higher --tolerance.")

    print("\nnext:  python tools/make_frames.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
