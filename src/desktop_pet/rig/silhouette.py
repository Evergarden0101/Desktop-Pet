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


#: Anatomical proportions of a standing human, measured in head-heights from
#: the crown (a "head" here includes hair, which is what a photo shows).
#: Used to sanity-check measured landmarks and to fill in ones the picture
#: doesn't show - a photo cropped at the thigh still has a believable hip.
HEADS_TO_SHOULDER = 1.10
HEADS_TO_HIP = 3.10
HEADS_TO_CROTCH = 3.90
HEADS_TO_KNEE = 5.60
HEADS_TO_FOOT = 7.40

#: A leg region smaller than this fraction of the figure means the picture is
#: cropped above the legs (a bust or waist-up shot) and cannot be rigged as a
#: walking figure.
MIN_LEG_FRACTION = 0.16

#: Plausible range for head height as a fraction of the whole figure, used to
#: sanity-check the shoulder measurement. A real standing human sits near 0.13;
#: stylised art goes higher. Outside this band the picture isn't a full figure.
MIN_HEAD_FRACTION = 0.07
MAX_HEAD_FRACTION = 0.34


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
    #: How the picture can be rigged:
    #:   "figure" - head, body and legs are all present: full articulated rig
    #:   "cutout" - no usable legs (bust/waist-up crop, or an abstract shape):
    #:              rig as head + body so the pet still looks like the picture
    layout: str = "figure"
    #: True when the legs were split by measurement rather than assumed.
    legs_detected: bool = False
    #: Which analysis produced these landmarks: "outline" (silhouette) or
    #: "pose" (a detected human). Surfaced so the importer can tell the user.
    source: str = "outline"
    #: The detected landmarks behind a "pose" analysis, when there were any.
    #: Colour sampling uses them to find the face far more precisely than the
    #: bounding box can.
    person: Optional[object] = None

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
def _find_shoulder(widths: Sequence[float], height: int) -> Optional[int]:
    """Row index of the shoulder line: where the figure widens fastest.

    Looking for a *narrow neck* (a local minimum in width) works on clip-art
    but fails on photographs, because hair falls past the jaw and fills the
    neck in - the profile just grows steadily from crown to shoulders with no
    pinch anywhere. What survives both cases is the **shoulder step**: going
    down the body, width jumps sharply where the shoulders start, and that
    jump is the largest positive gradient in the upper half.
    """
    lo = max(2, int(height * 0.04))
    hi = int(height * 0.50)
    if hi - lo < 4:
        return None

    # Compare each row against one a short distance above, so the measurement
    # spans the shoulder slope rather than pixel noise.
    span = max(2, height // 40)
    best_row = None
    best_gain = 0.0
    for i in range(lo, hi):
        above = widths[max(0, i - span)]
        gain = widths[i] - above
        if gain > best_gain:
            best_gain = gain
            best_row = i

    if best_row is None:
        return None
    # The step must be a real widening, not a gentle taper.
    max_width = max(widths) if widths else 0.0
    if max_width <= 0 or best_gain < max_width * 0.06:
        return None
    return best_row


def _find_crotch(rows: Sequence[RowInfo], height: int) -> Optional[int]:
    """Highest row (as an index) where the figure splits into exactly two legs.

    *Exactly* two matters. A figure with its arms held clear of the body also
    has separated runs across the torso - arm, torso, arm - and accepting "two
    or more" made that read as the crotch, putting it up around the ribs. Two
    runs and no more is the leg signature.
    """
    start = int(height * 0.40)
    for index in range(start, len(rows)):
        if len(rows[index].runs) != 2:
            continue
        # Confirm the split persists rather than being a one-row artifact.
        lookahead = rows[index : min(len(rows), index + max(3, height // 40))]
        if sum(1 for r in lookahead if len(r.runs) == 2) >= len(lookahead) * 0.6:
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
    """Measure ``image`` and locate the figure's landmarks.

    The strategy is *measure first, then fall back on anatomy*: the shoulder
    line and the gap between the legs are read straight off the alpha mask,
    and anything the picture doesn't show (a crotch hidden by a baggy coat, a
    hip below the crop) is filled in from human proportions anchored to the
    measured head height. That keeps clean artwork pixel-accurate while still
    producing a believable rig from an ordinary photo.
    """
    mask, width, _height, box = _binary_mask(image)
    x0, y0, x1, y1 = box
    rows = _scan_rows(mask, width, box)
    body_height = max(1, len(rows))

    widths = _smooth([float(r.width) for r in rows], max(3, body_height // 50))

    # ---- head height, from the shoulder step -----------------------------
    shoulder_index = _find_shoulder(widths, body_height)
    measured_shoulder = shoulder_index is not None
    if shoulder_index is None:
        shoulder_index = int(body_height * 0.20)

    head_h = max(4.0, float(shoulder_index) / HEADS_TO_SHOULDER)
    # A head much bigger than a quarter of the picture means we are looking at
    # a bust/waist-up crop, not a full figure: proportions below the shoulders
    # can no longer be trusted, but the head measurement itself still is.
    head_fraction = head_h / body_height

    # ---- crotch: measured split, or anatomy ------------------------------
    crotch_index = _find_crotch(rows, body_height)
    predicted_crotch = HEADS_TO_CROTCH * head_h
    legs_detected = False
    if crotch_index is not None:
        # Trust a measured split only when it lands somewhere a crotch could
        # plausibly be; wide hips and long coats produce spurious early splits.
        if 0.35 * body_height <= crotch_index <= 0.78 * body_height:
            legs_detected = True
        else:
            crotch_index = None
    if crotch_index is None:
        crotch_index = int(min(predicted_crotch, body_height * 0.62))

    # ---- can this be rigged as a walking figure? -------------------------
    leg_fraction = (body_height - crotch_index) / body_height
    layout = "figure"
    if not legs_detected:
        # Nothing below the torso actually parted into two legs, so judge the
        # shape by its head. A human head is between about a tenth and a
        # quarter of standing height; well outside that range means this isn't
        # a full figure. Too *large* is a bust or waist-up crop; too *small*
        # means the shoulder step was really just the curve of a blob, and
        # there is no head-on-body structure at all.
        # (A chibi has a huge head *and* real legs - hence testing the measured
        # split first, so it is never demoted here.)
        if (
            leg_fraction < MIN_LEG_FRACTION
            or not (MIN_HEAD_FRACTION <= head_fraction <= MAX_HEAD_FRACTION)
        ):
            # Rig as a cutout (head + body) rather than inventing limbs that
            # aren't in the picture.
            layout = "cutout"

    shoulder_y = y0 + shoulder_index
    neck_y = y0 + max(0, int(shoulder_index - head_h * 0.10))

    torso_span = max(1, crotch_index - shoulder_index)
    waist_y = y0 + shoulder_index + int(torso_span * 0.62)
    hip_y = y0 + shoulder_index + int(torso_span * 0.86)
    crotch_y = y0 + crotch_index

    # ---- feet -------------------------------------------------------------
    predicted_foot_top = y0 + HEADS_TO_KNEE * head_h + (HEADS_TO_FOOT - HEADS_TO_KNEE) * head_h * 0.72
    if legs_detected and predicted_foot_top < y1 - 4:
        foot_top = int(predicted_foot_top)
    else:
        foot_top = y1 - max(2, int((y1 - crotch_y) * 0.14))
    foot_top = int(min(max(foot_top, crotch_y + 4), y1 - 2))

    # ---- where the legs divide -------------------------------------------
    leg_split_x = _leg_split(rows, crotch_index, body_height, x0, x1)

    arm_bounds = _find_arm_bands(rows, shoulder_index, min(len(rows), crotch_index))

    # "Confident" now means we located a real shoulder line - the one landmark
    # everything else is anchored to. A cutout layout is still a usable result.
    confident = measured_shoulder

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
        layout=layout,
        legs_detected=legs_detected,
    )


def from_person(image, person) -> Optional[Silhouette]:
    """Build a :class:`Silhouette` from detected body landmarks.

    This is the reliable path for photographs. The model tells us where the
    shoulders, hips, knees and ankles actually are, which is exactly what the
    outline cannot reveal once hair covers the neck and shoulders.

    Two details matter:

    * **The head runs from the top of the hair to the shoulders.** The model
      locates the *face* (ears, eyes, nose); hair sits above and around it and
      is part of the character, so the head box is taken from the top of the
      opaque content down to the shoulder line. Cropping to the face alone is
      what leaves a pet with half a head.
    * **Visibility decides the layout.** Landmarks carry a confidence that they
      are in frame, so a waist-up photo is recognised as having no legs rather
      than having legs guessed at.
    """
    mask, width, _height, box = _binary_mask(image)
    x0, y0, x1, y1 = box
    rows = _scan_rows(mask, width, box)
    body_height = max(1, len(rows))

    shoulder = person.mid_y("shoulder_l", "shoulder_r")
    if shoulder is None or not person.has("shoulder_l", "shoulder_r"):
        return None  # without shoulders there is nothing to anchor to

    def clamp_y(value: float) -> int:
        return int(min(max(value, y0), y1))

    shoulder_y = clamp_y(shoulder)
    # Head: from the top of the actual artwork (hair included) to the shoulders.
    head_top = y0
    head_h = max(6.0, shoulder_y - head_top)
    neck_y = clamp_y(shoulder_y - head_h * 0.12)

    hip = person.mid_y("hip_l", "hip_r")
    hips_visible = person.has("hip_l", "hip_r")
    if hip is not None and hips_visible:
        hip_y = clamp_y(hip)
    else:
        hip_y = clamp_y(head_top + HEADS_TO_HIP * head_h)

    knee = person.mid_y("knee_l", "knee_r")
    knees_visible = person.has("knee_l", "knee_r")
    ankle = person.mid_y("ankle_l", "ankle_r")
    ankles_visible = person.has("ankle_l", "ankle_r")

    # The crotch sits a little below the hip joints.
    crotch_y = clamp_y(hip_y + head_h * 0.35)
    waist_y = clamp_y(shoulder_y + (hip_y - shoulder_y) * 0.62)

    if ankle is not None and ankles_visible:
        foot_top = clamp_y(ankle - head_h * 0.12)
    elif knee is not None and knees_visible:
        foot_top = clamp_y(knee + (knee - crotch_y) * 0.85)
    else:
        foot_top = y1 - max(2, int((y1 - crotch_y) * 0.14))
    foot_top = int(min(max(foot_top, crotch_y + 4), y1 - 2))

    # Legs divide between the hip joints.
    hips_mid = person.mid("hip_l", "hip_r")
    leg_split_x = hips_mid[0] if hips_mid else (x0 + x1) / 2.0
    leg_split_x = min(max(leg_split_x, x0 + 2), x1 - 2)

    # Layout: are the legs actually in the picture?
    leg_fraction = (y1 - crotch_y) / body_height
    legs_in_frame = knees_visible or ankles_visible
    layout = "figure"
    if not legs_in_frame and leg_fraction < 0.30:
        layout = "cutout"
    if crotch_y >= y1 - 8:
        layout = "cutout"

    # Arms are only worth cutting out when the model can see them clearly and
    # the outline shows a gap - otherwise they stay part of the torso sprite.
    arm_bounds = _find_arm_bands(
        rows, shoulder_y - y0, max(shoulder_y - y0 + 1, crotch_y - y0)
    )

    return Silhouette(
        box=(x0, y0, x1, y1),
        rows=rows,
        head_top=head_top,
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
        confident=True,
        layout=layout,
        legs_detected=legs_in_frame,
        source="pose",
        person=person,
    )


def _leg_split(rows, crotch_index: int, body_height: int, x0: int, x1: int) -> float:
    """Column where the two legs part.

    Uses the gap between the outer runs just below the crotch when the legs are
    actually separate. Baggy trousers merge into one run, so as a fallback the
    leg region is halved down its own centre line - visually convincing even
    though the split is invented.
    """
    probe = min(len(rows) - 1, crotch_index + max(1, body_height // 40))
    if 0 <= probe < len(rows):
        runs = rows[probe].runs
        if len(runs) >= 2:
            return (runs[0][1] + runs[-1][0]) / 2.0

    # Centre of the leg region, averaged over a few rows for stability.
    centres = [
        r.center
        for r in rows[crotch_index:]
        if r.count > 0
    ]
    if centres:
        return sum(centres) / len(centres)
    return (x0 + x1) / 2.0
