"""Content-aware silhouette analysis for body-part extraction.

The naive way to cut a character into body parts is to slice fixed fractions of
the bounding box ("the head is the top 13%"). That only works if the drawing
happens to match those proportions - which real art rarely does, so heads get
sliced through the chin and arms end up in the torso.

This module instead *reads the shape*. It binarises the alpha mask and measures
the figure row by row:

* the **width profile** (how wide the character is at each height) reveals the
  neck (a narrow waist under a wide head), the shoulders (a sharp widening) and
  the hips;
* the **run structure** of a row (how many separate opaque spans it contains)
  reveals where the legs split apart, and where arms are held away from the
  body;
* the **left/right extents** track the body's centre line as it leans.

From those landmarks :func:`analyze` returns a :class:`Silhouette` that the
extractor turns into part rectangles. Everything is derived from the picture, so
a chibi mascot, a tall human and a four-legged critter all get sensible cuts.

Pure Pillow - no numpy - and fast enough for a 1200px image because the per-row
work is done with ``bytes`` operations rather than Python loops over pixels.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple

#: Alpha value at or above which a pixel counts as part of the character.
ALPHA_THRESHOLD = 32


@dataclass
class RowInfo:
    """Measurements for one scanline of the figure."""

    y: int
    left: int
    right: int
    count: int
    runs: List[Tuple[int, int]] = field(default_factory=list)

    @property
    def width(self) -> int:
        return max(0, self.right - self.left + 1)

    @property
    def center(self) -> float:
        return (self.left + self.right) / 2.0


@dataclass
class Silhouette:
    """Landmarks describing where the parts of a figure are."""

    box: Tuple[int, int, int, int]          # content bbox (x0, y0, x1, y1)
    rows: List[RowInfo]
    head_top: int
    neck_y: int
    shoulder_y: int
    waist_y: int
    hip_y: int
    crotch_y: int
    foot_top: int
    bottom: int
    #: Column that separates the two legs (used to split left/right).
    leg_split_x: float
    #: True when the arms were detected as separate runs beside the torso.
    arms_detached: bool
    #: Per-side arm column range in the torso band, if detached.
    arm_bounds: Optional[Tuple[Tuple[int, int], Tuple[int, int]]] = None
    #: Whether analysis found a believable humanoid; False -> caller falls back.
    confident: bool = True

    def row_at(self, y: int) -> Optional[RowInfo]:
        index = y - self.box[1]
        if 0 <= index < len(self.rows):
            return self.rows[index]
        return None

    def center_at(self, y: int) -> float:
        row = self.row_at(y)
        if row is None or row.count == 0:
            return (self.box[0] + self.box[2]) / 2.0
        return row.center

    def span_at(self, y: int) -> Tuple[int, int]:
        row = self.row_at(y)
        if row is None or row.count == 0:
            return self.box[0], self.box[2]
        return row.left, row.right


# --------------------------------------------------------------------- scan
def _binary_mask(image) -> Tuple[bytes, int, int, Tuple[int, int, int, int]]:
    """Return (mask bytes of 0/1, width, height, content box) for ``image``."""
    from PIL import Image, ImageChops

    if image.mode in ("RGBA", "LA") or (
        image.mode == "P" and "transparency" in image.info
    ):
        alpha = image.convert("RGBA").split()[-1]
    else:
        # No alpha: treat the top-left pixel's colour as the background.
        rgb = image.convert("RGB")
        background = Image.new("RGB", rgb.size, rgb.getpixel((0, 0)))
        alpha = ImageChops.difference(rgb, background).convert("L")

    table = [0] * 256
    for value in range(ALPHA_THRESHOLD, 256):
        table[value] = 1
    mask = alpha.point(table, mode="L")
    box = mask.getbbox() or (0, 0, image.width, image.height)
    return mask.tobytes(), mask.width, mask.height, box


def _runs_of(row: bytes, offset: int, min_run: int) -> List[Tuple[int, int]]:
    """Opaque spans within ``row`` as absolute (start, end) pairs.

    ``bytes.split`` does the scanning in C; we just track the offset of each
    segment. Runs shorter than ``min_run`` are dropped so antialiasing fringes
    and stray pixels don't read as an extra limb.
    """
    runs: List[Tuple[int, int]] = []
    cursor = 0
    for segment in row.split(b"\x00"):
        length = len(segment)
        if length:
            if length >= min_run:
                runs.append((offset + cursor, offset + cursor + length - 1))
            cursor += length
        cursor += 1  # the separator byte
    return runs


def _scan_rows(mask: bytes, width: int, box: Tuple[int, int, int, int]) -> List[RowInfo]:
    x0, y0, x1, y1 = box
    min_run = max(1, (x1 - x0) // 40)
    rows: List[RowInfo] = []
    for y in range(y0, y1):
        row = mask[y * width + x0 : y * width + x1]
        count = row.count(1)
        if count == 0:
            rows.append(RowInfo(y=y, left=x0, right=x0, count=0, runs=[]))
            continue
        left = row.find(b"\x01") + x0
        right = row.rfind(b"\x01") + x0
        rows.append(
            RowInfo(
                y=y,
                left=left,
                right=right,
                count=count,
                runs=_runs_of(row, x0, min_run),
            )
        )
    return rows


def _smooth(values: Sequence[float], window: int) -> List[float]:
    """Moving average, so a single jagged row can't be mistaken for a landmark."""
    if window <= 1 or len(values) < window:
        return list(values)
    out: List[float] = []
    half = window // 2
    for i in range(len(values)):
        lo = max(0, i - half)
        hi = min(len(values), i + half + 1)
        window_slice = values[lo:hi]
        out.append(sum(window_slice) / len(window_slice))
    return out


# ---------------------------------------------------------------- landmarks
def _find_neck(widths: Sequence[float], height: int) -> Optional[int]:
    """Row index of the narrowest point in the upper part of the figure.

    A humanoid's head is wide, the neck below it is narrow, and the shoulders
    below that are wide again - so the neck is a clear local minimum in the
    first third of the body.
    """
    lo = int(height * 0.08)
    hi = int(height * 0.42)
    if hi - lo < 3:
        return None
    window = widths[lo:hi]
    best = min(range(len(window)), key=lambda i: window[i])
    neck = lo + best

    # Require the neck to actually pinch: narrower than the head above it and
    # than the shoulders below, otherwise this isn't a head-on-neck shape.
    head_width = max(widths[: max(1, neck)] or [0])
    below = widths[neck : min(len(widths), neck + int(height * 0.2))]
    shoulder_width = max(below) if below else 0
    if head_width <= 0 or shoulder_width <= 0:
        return None
    if widths[neck] > head_width * 0.92 or widths[neck] > shoulder_width * 0.92:
        return None
    return neck


def _find_crotch(rows: Sequence[RowInfo], height: int) -> Optional[int]:
    """Highest row (as an index) where the figure splits into two legs."""
    start = int(height * 0.45)
    for index in range(start, len(rows)):
        row = rows[index]
        if len(row.runs) >= 2:
            # Confirm the split persists rather than being a one-row artifact.
            lookahead = rows[index : min(len(rows), index + max(3, height // 40))]
            if sum(1 for r in lookahead if len(r.runs) >= 2) >= len(lookahead) * 0.6:
                return index
    return None


def _find_arm_bands(
    rows: Sequence[RowInfo], shoulder: int, waist: int
) -> Optional[Tuple[Tuple[int, int], Tuple[int, int]]]:
    """Column ranges of arms held away from the body, if the rows show three runs."""
    left_bounds: List[Tuple[int, int]] = []
    right_bounds: List[Tuple[int, int]] = []
    for index in range(shoulder, min(waist, len(rows))):
        runs = rows[index].runs
        if len(runs) >= 3:
            left_bounds.append(runs[0])
            right_bounds.append(runs[-1])
    if len(left_bounds) < 3:
        return None
    left = (min(b[0] for b in left_bounds), max(b[1] for b in left_bounds))
    right = (min(b[0] for b in right_bounds), max(b[1] for b in right_bounds))
    return left, right


def analyze(image) -> Silhouette:
    """Measure ``image`` and locate the figure's landmarks."""
    mask, width, _height, box = _binary_mask(image)
    x0, y0, x1, y1 = box
    rows = _scan_rows(mask, width, box)
    body_height = max(1, len(rows))

    widths = _smooth([float(r.width) for r in rows], max(3, body_height // 50))

    def to_y(index: Optional[int], fallback: float) -> int:
        if index is None:
            return int(y0 + fallback * body_height)
        return y0 + index

    neck_index = _find_neck(widths, body_height)
    crotch_index = _find_crotch(rows, body_height)

    confident = neck_index is not None

    neck_y = to_y(neck_index, 0.22)
    crotch_y = to_y(crotch_index, 0.55)
    # Shoulders sit just below the neck, where the body reaches full width.
    shoulder_index = (neck_index if neck_index is not None else int(body_height * 0.22))
    shoulder_scan_end = min(body_height, shoulder_index + max(2, body_height // 12))
    widest = shoulder_index
    for i in range(shoulder_index, shoulder_scan_end):
        if widths[i] > widths[widest]:
            widest = i
    shoulder_y = y0 + widest

    crotch_index_eff = crotch_index if crotch_index is not None else int(body_height * 0.55)
    torso_span = max(1, crotch_index_eff - widest)
    waist_y = y0 + widest + int(torso_span * 0.62)
    hip_y = y0 + widest + int(torso_span * 0.88)

    # Feet: the bottom slice of the legs.
    foot_top = y1 - max(2, int(body_height * 0.07))

    # Where the legs divide: the gap between the two runs just under the crotch.
    leg_split_x = (x0 + x1) / 2.0
    probe = min(len(rows) - 1, crotch_index_eff + max(1, body_height // 40))
    if 0 <= probe < len(rows) and len(rows[probe].runs) >= 2:
        first, second = rows[probe].runs[0], rows[probe].runs[-1]
        leg_split_x = (first[1] + second[0]) / 2.0
    elif rows:
        leg_split_x = rows[min(probe, len(rows) - 1)].center

    arm_bounds = _find_arm_bands(rows, widest, min(len(rows), crotch_index_eff))

    return Silhouette(
        box=(x0, y0, x1, y1),
        rows=rows,
        head_top=y0,
        neck_y=neck_y,
        shoulder_y=shoulder_y,
        waist_y=waist_y,
        hip_y=hip_y,
        crotch_y=crotch_y,
        foot_top=foot_top,
        bottom=y1,
        leg_split_x=leg_split_x,
        arms_detached=arm_bounds is not None,
        arm_bounds=arm_bounds,
        confident=confident,
    )
