"""Shared rigging helpers.

Turns a single static RGBA cutout of a person into a small set of body-part
layers plus sampled colours, so the frame generator can pose the figure
without ever needing a second drawing of it.

Nothing here is machine learning: it is geometry over the alpha mask.  That
keeps the figure's own pixels -- face, hairstyle, clothing -- completely
untouched.  Only the limbs we have to invent (arms and hands) are drawn, and
they are drawn in colours lifted from the figure itself.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, asdict
from typing import Iterable, Sequence

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

ALPHA_CUTOFF = 32


# --------------------------------------------------------------------------
# geometry helpers
# --------------------------------------------------------------------------

def rotate_about(img: Image.Image, pivot: tuple[float, float], angle_deg: float):
    """Rotate ``img`` around ``pivot`` and report where the pivot ended up.

    PIL rotates counter-clockwise about the image centre, so we rotate the
    pivot's offset from the centre by the same amount to track it.
    """
    if abs(angle_deg) < 1e-6:
        return img, (float(pivot[0]), float(pivot[1]))

    rot = img.rotate(angle_deg, resample=Image.BICUBIC, expand=True)
    cx, cy = img.width / 2.0, img.height / 2.0
    dx, dy = pivot[0] - cx, pivot[1] - cy
    a = math.radians(angle_deg)
    ndx = math.cos(a) * dx + math.sin(a) * dy
    ndy = -math.sin(a) * dx + math.cos(a) * dy
    return rot, (rot.width / 2.0 + ndx, rot.height / 2.0 + ndy)


def blit(canvas: Image.Image, img: Image.Image, topleft) -> Image.Image:
    """Alpha-composite ``img`` onto ``canvas`` at ``topleft`` (may be negative)."""
    layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    layer.paste(img, (int(round(topleft[0])), int(round(topleft[1]))))
    return Image.alpha_composite(canvas, layer)


def blit_pivot(canvas: Image.Image, img: Image.Image, pivot, dest) -> Image.Image:
    return blit(canvas, img, (dest[0] - pivot[0], dest[1] - pivot[1]))


def paste_rotated(canvas, img, pivot, angle_deg, dest):
    rot, new_pivot = rotate_about(img, pivot, angle_deg)
    return blit_pivot(canvas, rot, new_pivot, dest)


def shade(rgb: Sequence[int], factor: float) -> tuple[int, int, int]:
    return tuple(max(0, min(255, int(c * factor))) for c in rgb[:3])


# --------------------------------------------------------------------------
# limb drawing (the "add hands naturally" part)
# --------------------------------------------------------------------------

def draw_tapered(draw: ImageDraw.ImageDraw, p0, p1, w0: float, w1: float, color):
    """A capsule that tapers from width w0 at p0 to w1 at p1."""
    x0, y0 = p0
    x1, y1 = p1
    dx, dy = x1 - x0, y1 - y0
    length = math.hypot(dx, dy)
    if length < 1e-3:
        return
    nx, ny = -dy / length, dx / length
    quad = [
        (x0 + nx * w0 / 2, y0 + ny * w0 / 2),
        (x1 + nx * w1 / 2, y1 + ny * w1 / 2),
        (x1 - nx * w1 / 2, y1 - ny * w1 / 2),
        (x0 - nx * w0 / 2, y0 - ny * w0 / 2),
    ]
    draw.polygon(quad, fill=color)
    draw.ellipse([x0 - w0 / 2, y0 - w0 / 2, x0 + w0 / 2, y0 + w0 / 2], fill=color)
    draw.ellipse([x1 - w1 / 2, y1 - w1 / 2, x1 + w1 / 2, y1 + w1 / 2], fill=color)


def joint(origin, angle_deg: float, length: float):
    a = math.radians(angle_deg)
    return (origin[0] + math.cos(a) * length, origin[1] + math.sin(a) * length)


def draw_arm(canvas: Image.Image, shoulder, upper_angle: float, fore_angle: float,
             upper_len: float, fore_len: float, thickness: float,
             sleeve_rgb, skin_rgb, dim: float = 1.0) -> Image.Image:
    """Draw one arm ending in a hand.

    ``dim`` < 1 darkens the whole limb so the far-side arm reads as being
    behind the body.
    """
    layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)

    elbow = joint(shoulder, upper_angle, upper_len)
    wrist = joint(elbow, fore_angle, fore_len)

    sleeve = shade(sleeve_rgb, dim)
    skin = shade(skin_rgb, dim)
    skin_dark = shade(skin_rgb, dim * 0.86)

    # upper arm keeps the clothing colour, forearm and hand are skin
    draw_tapered(d, shoulder, elbow, thickness * 1.15, thickness * 0.92, sleeve + (255,))
    draw_tapered(d, elbow, wrist, thickness * 0.86, thickness * 0.72, skin + (255,))

    # hand: a small palm planted flat, with a hint of fingers
    hand_r = thickness * 0.62
    d.ellipse([wrist[0] - hand_r, wrist[1] - hand_r * 0.85,
               wrist[0] + hand_r, wrist[1] + hand_r * 0.95], fill=skin + (255,))
    finger = joint(wrist, fore_angle, hand_r * 0.9)
    draw_tapered(d, wrist, finger, thickness * 0.5, thickness * 0.34, skin_dark + (255,))

    layer = layer.filter(ImageFilter.SMOOTH)
    return Image.alpha_composite(canvas, layer)


def draw_shadow(canvas: Image.Image, center, rx: float, ry: float, alpha: int = 70):
    layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    d.ellipse([center[0] - rx, center[1] - ry, center[0] + rx, center[1] + ry],
              fill=(0, 0, 0, alpha))
    layer = layer.filter(ImageFilter.GaussianBlur(max(1.0, rx * 0.18)))
    return Image.alpha_composite(canvas, layer)


# --------------------------------------------------------------------------
# figure analysis
# --------------------------------------------------------------------------

@dataclass
class Rig:
    """Landmarks and colours measured from one cutout, in cutout pixels."""
    width: int
    height: int
    top: int
    bottom: int
    neck_y: int
    shoulder_y: int
    hip_y: int
    knee_y: int
    head_cx: float
    shoulder_cx: float
    hip_cx: float
    body_width: float
    skin: tuple
    cloth: tuple

    def to_json(self) -> dict:
        return asdict(self)


def _row_spans(mask: np.ndarray):
    """For each row: (count, first_col, last_col, centroid) ignoring empty rows."""
    counts = mask.sum(axis=1)
    return counts


def _band_centroid(mask: np.ndarray, y0: int, y1: int) -> float:
    band = mask[max(0, y0):max(y0 + 1, y1)]
    ys, xs = np.nonzero(band)
    if xs.size == 0:
        return mask.shape[1] / 2.0
    return float(xs.mean())


def _median_color(rgb: np.ndarray, mask: np.ndarray, y0, y1, x0, x1,
                  min_value: int = 0, max_value: int = 256) -> tuple:
    sub_mask = np.zeros_like(mask)
    sub_mask[y0:y1, x0:x1] = mask[y0:y1, x0:x1]
    px = rgb[sub_mask]
    if px.size == 0:
        return (210, 180, 160)
    value = px.max(axis=1)
    keep = (value >= min_value) & (value < max_value)
    if keep.sum() > 20:
        px = px[keep]
    return tuple(int(v) for v in np.median(px, axis=0))


def analyze(img: Image.Image) -> Rig:
    """Locate neck / shoulders / hips / knees and sample skin + clothing colour."""
    img = img.convert("RGBA")
    arr = np.asarray(img)
    rgb = arr[..., :3].astype(np.int16)
    mask = arr[..., 3] > ALPHA_CUTOFF

    ys, xs = np.nonzero(mask)
    if ys.size == 0:
        raise ValueError("cutout is empty")
    top, bottom = int(ys.min()), int(ys.max())
    h = max(1, bottom - top)

    counts = _row_spans(mask)

    def narrowest(a: float, b: float, prior: float, pull: float = 0.6) -> int:
        """The narrowest row between ``a`` and ``b``, biased toward ``prior``.

        Raw ``argmin`` is useless here: the width profile of a torso is almost
        flat, so a resample of the same figure moves the winning row by tens of
        pixels.  Smoothing plus a pull toward where the joint anatomically
        belongs makes the answer stable.
        """
        y0 = max(top, int(top + h * a))
        y1 = min(bottom, max(y0 + 1, int(top + h * b)))
        window = counts[y0:y1].astype(float)
        if window.size == 0 or window.max() <= 0:
            return int(top + h * prior)

        k = max(1, int(h * 0.02) | 1)
        padded = np.pad(window, k // 2, mode="edge")
        smooth = np.convolve(padded, np.ones(k) / k, mode="valid")[:window.size]
        smooth[window == 0] = smooth.max()  # empty rows are never a joint

        span = max(1.0, h * (b - a) / 2.0)
        offset = np.abs(np.arange(y0, y1) - (top + h * prior)) / span
        score = smooth / max(1e-6, smooth.max()) + pull * offset
        return int(y0 + int(np.argmin(score)))

    # the neck is the narrowest row in the upper third, the waist the
    # narrowest row around the middle.
    neck_y = narrowest(0.10, 0.34, 0.22)
    hip_y = narrowest(0.46, 0.68, 0.56)
    if hip_y <= neck_y:
        hip_y = int(neck_y + h * 0.3)
    shoulder_y = int(min(hip_y - 1, neck_y + h * 0.07))
    knee_y = int(hip_y + (bottom - hip_y) * 0.52)

    head_cx = _band_centroid(mask, top, neck_y)
    shoulder_cx = _band_centroid(mask, shoulder_y, shoulder_y + max(2, int(h * 0.05)))
    hip_cx = _band_centroid(mask, hip_y, hip_y + max(2, int(h * 0.05)))

    torso_rows = counts[shoulder_y:hip_y]
    body_width = float(np.median(torso_rows[torso_rows > 0])) if np.any(torso_rows > 0) else h * 0.25

    # skin: lower-central part of the head (cheeks / chin), skipping dark hair
    head_h = max(4, neck_y - top)
    hx0 = int(head_cx - head_h * 0.32)
    hx1 = int(head_cx + head_h * 0.32)
    skin = _median_color(rgb, mask, neck_y - int(head_h * 0.55), neck_y,
                         max(0, hx0), min(mask.shape[1], hx1), min_value=70)

    # clothing: central torso just under the shoulders
    tx0 = int(shoulder_cx - body_width * 0.3)
    tx1 = int(shoulder_cx + body_width * 0.3)
    cloth = _median_color(rgb, mask, shoulder_y, int(shoulder_y + (hip_y - shoulder_y) * 0.6),
                          max(0, tx0), min(mask.shape[1], tx1))

    return Rig(width=img.width, height=img.height, top=top, bottom=bottom,
               neck_y=neck_y, shoulder_y=shoulder_y, hip_y=hip_y, knee_y=knee_y,
               head_cx=head_cx, shoulder_cx=shoulder_cx, hip_cx=hip_cx,
               body_width=body_width, skin=tuple(skin), cloth=tuple(cloth))


# --------------------------------------------------------------------------
# slicing the cutout into poseable layers
# --------------------------------------------------------------------------

def _soft_slice(img: Image.Image, y0: int, y1: int, x0: int | None = None,
                x1: int | None = None, feather: float = 1.5):
    """Cut a rectangular band out of the cutout.

    A short feather along the cut hides the seam once the pieces are rotated
    away from each other.  Returns ``(piece, bbox)`` where bbox is the piece's
    position in the original cutout.
    """
    w, h = img.size
    m = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(m)
    d.rectangle([0 if x0 is None else x0, y0,
                 (w if x1 is None else x1) - 1, y1 - 1], fill=255)
    if feather > 0:
        m = m.filter(ImageFilter.GaussianBlur(feather))
    out = img.copy()
    out.putalpha(Image.fromarray(
        (np.asarray(img.getchannel("A"), dtype=np.float32) *
         (np.asarray(m, dtype=np.float32) / 255.0)).astype(np.uint8)))
    box = out.getbbox() or (0, 0, 1, 1)
    return out.crop(box), box


def slice_parts(img: Image.Image, rig: Rig) -> dict:
    """Split the cutout into head / torso / four leg segments.

    Each entry is ``(image, origin)`` where ``origin`` is the piece's top-left
    corner in the original cutout's coordinates, so landmarks stay usable.
    """
    parts: dict[str, tuple[Image.Image, tuple[int, int]]] = {}

    def take(name, y0, y1, x0=None, x1=None, feather=1.5):
        piece, box = _soft_slice(img, max(0, y0), min(img.height, y1), x0, x1, feather)
        parts[name] = (piece, (box[0], box[1]))

    mid = int(rig.hip_cx)
    take("head", 0, rig.neck_y + 3, feather=1.2)
    take("torso", rig.neck_y - 2, rig.hip_y + 3, feather=1.5)
    take("leg_far_upper", rig.hip_y - 2, rig.knee_y + 3, None, mid + 2)
    take("leg_far_lower", rig.knee_y - 2, rig.height, None, mid + 2)
    take("leg_near_upper", rig.hip_y - 2, rig.knee_y + 3, mid - 2, None)
    take("leg_near_lower", rig.knee_y - 2, rig.height, mid - 2, None)
    return parts


def part_pivot(parts: dict, name: str, point: tuple[float, float]) -> tuple[float, float]:
    """Convert a point in cutout coordinates into a pivot inside a part image."""
    _, origin = parts[name]
    return (point[0] - origin[0], point[1] - origin[1])


def save_meta(path, data: dict) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
