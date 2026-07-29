"""Pull each person out of a source image.

Background removal uses ``rembg`` when it is importable (much better on real
photos).  Without it we fall back to a border flood fill, which is fine for
images that already have a flat or transparent background -- and which the
Character Manager lets you tune with a live preview.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image

DEFAULT_TOLERANCE = 18


@dataclass
class ExtractOptions:
    tolerance: int = DEFAULT_TOLERANCE
    max_figures: int = 6
    min_area: float = 0.004
    height: int = 420
    use_rembg: bool = True
    boxes: list[tuple[int, int, int, int]] = field(default_factory=list)


def rembg_available() -> bool:
    try:
        import rembg  # noqa: F401
    except Exception:
        return False
    return True


# --------------------------------------------------------------------------
# background removal
# --------------------------------------------------------------------------

def remove_background(img: Image.Image, use_rembg: bool = True,
                      tolerance: int = DEFAULT_TOLERANCE) -> Image.Image:
    """Return an RGBA image whose alpha keeps only the subject(s)."""
    img = img.convert("RGBA") if img.mode != "RGBA" else img

    if np.asarray(img)[..., 3].min() < 250:
        return img  # already has transparency, trust it

    if use_rembg:
        try:
            import rembg  # type: ignore

            return rembg.remove(img)
        except Exception:
            pass  # not installed, or no model available -- fall through

    return flood_fill_background(img.convert("RGB"), tolerance)


def flood_fill_background(img: Image.Image,
                          tolerance: int = DEFAULT_TOLERANCE) -> Image.Image:
    """Flood fill inward from the border, treating similar colours as background."""
    arr = np.asarray(img).astype(np.int16)
    h, w = arr.shape[:2]
    bg = np.zeros((h, w), dtype=bool)

    border = np.concatenate([arr[0], arr[-1], arr[:, 0], arr[:, -1]])
    ref = np.median(border, axis=0)
    close = np.abs(arr - ref).sum(axis=2) <= tolerance * 3

    seeds: deque = deque()
    for x in range(w):
        seeds.append((0, x))
        seeds.append((h - 1, x))
    for y in range(h):
        seeds.append((y, 0))
        seeds.append((y, w - 1))

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

    return Image.fromarray(
        np.dstack([arr.astype(np.uint8), np.where(bg, 0, 255).astype(np.uint8)]),
        "RGBA")


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


def detect_figures(rgba: Image.Image, max_figures: int = 6,
                   min_area: float = 0.004) -> list[tuple[int, int, int, int]]:
    """Bounding boxes of the plausible human blobs, left to right."""
    alpha = np.asarray(rgba)[..., 3]
    mask = alpha > 32
    labels, count = label_components(mask)

    total = mask.shape[0] * mask.shape[1]
    blobs = []
    for i in range(1, count + 1):
        sel = labels == i
        area = int(sel.sum())
        if area < total * min_area:
            continue  # a distraction: prop, watermark, speckle
        ys, xs = np.nonzero(sel)
        x0, x1 = int(xs.min()), int(xs.max()) + 1
        y0, y1 = int(ys.min()), int(ys.max()) + 1
        if (y1 - y0) < (x1 - x0) * 0.6:
            continue  # too wide to be a standing person
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
    if img.height == target_h or img.height == 0:
        return img
    scale = target_h / img.height
    return img.resize((max(1, int(img.width * scale)), target_h), Image.LANCZOS)


def cutout_warnings(piece: Image.Image) -> list[str]:
    """Sanity checks that catch the two ways background removal goes wrong."""
    notes = []
    ratio = piece.height / max(1, piece.width)
    fill = float((np.asarray(piece)[..., 3] > 32).mean())
    if ratio < 1.6:
        notes.append(f"short and wide (h/w={ratio:.1f}) -- legs may have been cut "
                     f"off; try a lower tolerance")
    if fill > 0.85:
        notes.append(f"{fill:.0%} of the crop is opaque -- background probably "
                     f"survived; try a higher tolerance")
    return notes


# --------------------------------------------------------------------------

def prepare(img: Image.Image, opts: ExtractOptions):
    """Remove the background and find the figures.  Returns (rgba, boxes)."""
    rgba = remove_background(img, opts.use_rembg, opts.tolerance)
    boxes = opts.boxes or detect_figures(rgba, opts.max_figures, opts.min_area)
    return rgba, boxes


def extract_to_folders(img: Image.Image, out_root: Path, opts: ExtractOptions,
                       prefix: str = "figure", progress=None) -> list[Path]:
    """Write one ``<out_root>/<prefix>_NN/base.png`` per figure.

    ``progress`` is called as ``progress(fraction, message)`` if given.
    """
    def report(frac, msg):
        if progress:
            progress(frac, msg)

    report(0.05, "removing background")
    rgba, boxes = prepare(img, opts)
    if not boxes:
        raise ValueError("No figures found. Try a different tolerance, a lower "
                         "minimum area, or draw the boxes by hand.")

    out_root.mkdir(parents=True, exist_ok=True)
    folders = []
    for i, box in enumerate(boxes, start=1):
        report(0.15 + 0.5 * i / len(boxes), f"cutting out figure {i}")
        piece = normalize_height(crop_figure(rgba, box), opts.height)

        folder = out_root / _unique_name(out_root, prefix, i)
        folder.mkdir(parents=True, exist_ok=True)
        piece.save(folder / "base.png")
        folders.append(folder)
    return folders


def _unique_name(root: Path, prefix: str, index: int) -> str:
    name = f"{prefix}_{index:02d}"
    n = index
    while (root / name).exists():
        n += 1
        name = f"{prefix}_{n:02d}"
    return name
