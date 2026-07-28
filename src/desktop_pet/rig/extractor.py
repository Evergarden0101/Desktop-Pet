"""Extract riggable body-part sprites from a character image.

Three strategies are supported, in increasing order of fidelity:

``regions``
    The character pack lists an explicit rectangle (and optional pivot) for
    each part. Deterministic and pixel-perfect - the recommended path for
    hand-authored characters.

``auto_humanoid``
    A best-effort heuristic that slices a single upright, roughly front-facing
    full-body image into standard humanoid proportions. Requires no extra
    dependencies and is what powers "drop in any PNG and go".

``pose``
    Uses a pose-estimation backend (MediaPipe, if installed) to locate joints
    and cut parts around them. Optional; falls back to ``auto_humanoid`` when
    the backend is unavailable.

Everything here depends only on Pillow, so it runs headless (e.g. the
``desktop-pet extract`` CLI and CI tests).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from ..core.geometry import Vec2
from .body_parts import DEFAULT_HUMANOID, STANDARD_PARTS, BodyPart

try:  # Pillow is a hard dependency for extraction but soft for imports.
    from PIL import Image
except Exception:  # pragma: no cover - only when Pillow missing
    Image = None  # type: ignore


# A proportion band is (part_name, x0, y0, x1, y1, pivot_x, pivot_y) with all
# coordinates expressed as fractions of the *content* bounding box. The pivot is
# in the crop's own normalized space. These follow a ~7.5 head-height figure.
#: Default (pivot, anchor) per part in normalized sprite space. ``pivot`` sits
#: on the bone's near joint and ``anchor`` on its far end, so the pair defines
#: which way the artwork runs along the bone. The head is the special one: its
#: joint is at the chin and the skull extends *up*, i.e. toward smaller Y.
_PART_AXES: Dict[str, Tuple[Tuple[float, float], Tuple[float, float]]] = {
    "head": ((0.5, 0.93), (0.5, 0.05)),
}
_DEFAULT_AXIS = ((0.5, 0.06), (0.5, 0.94))


def part_axis(name: str):
    """Return ((pivot_x, pivot_y), (anchor_x, anchor_y)) for ``name``."""
    return _PART_AXES.get(name, _DEFAULT_AXIS)


_HUMANOID_BANDS: List[Tuple[str, float, float, float, float, float, float]] = [
    # part            x0     y0     x1     y1    pivx   pivy
    ("head",         0.34,  0.00,  0.66,  0.135, 0.50,  0.95),
    ("torso",        0.34,  0.135, 0.66,  0.42,  0.50,  0.02),
    ("hips",         0.34,  0.42,  0.66,  0.52,  0.50,  0.10),

    ("upper_arm_l",  0.16,  0.15,  0.36,  0.30,  0.75,  0.10),
    ("forearm_l",    0.14,  0.29,  0.34,  0.44,  0.70,  0.05),
    ("hand_l",       0.13,  0.42,  0.31,  0.53,  0.60,  0.05),

    ("upper_arm_r",  0.64,  0.15,  0.84,  0.30,  0.25,  0.10),
    ("forearm_r",    0.66,  0.29,  0.86,  0.44,  0.30,  0.05),
    ("hand_r",       0.69,  0.42,  0.87,  0.53,  0.40,  0.05),

    ("thigh_l",      0.35,  0.50,  0.52,  0.73,  0.55,  0.05),
    ("shin_l",       0.36,  0.72,  0.52,  0.92,  0.55,  0.03),
    ("foot_l",       0.33,  0.90,  0.54,  1.00,  0.45,  0.20),

    ("thigh_r",      0.48,  0.50,  0.65,  0.73,  0.45,  0.05),
    ("shin_r",       0.48,  0.72,  0.64,  0.92,  0.45,  0.03),
    ("foot_r",       0.46,  0.90,  0.67,  1.00,  0.55,  0.20),
]


@dataclass
class ExtractionResult:
    parts: Dict[str, BodyPart]
    content_box: Tuple[int, int, int, int]
    source_size: Tuple[int, int]
    method: str
    #: Bone specs derived from the artwork's own proportions (character.json
    #: "skeleton"), when the silhouette could be measured.
    skeleton: Optional[List[dict]] = None

    def to_regions_dict(self) -> Dict[str, dict]:
        """Serialize as a ``regions`` extraction block for character.json."""
        out: Dict[str, dict] = {}
        for name, part in self.parts.items():
            if part.source_rect is None:
                continue
            out[name] = {
                "rect": list(part.source_rect),
                "pivot": [round(part.pivot.x, 4), round(part.pivot.y, 4)],
                "anchor": [
                    round(part.child_anchor.x, 4),
                    round(part.child_anchor.y, 4),
                ],
            }
        return out


def _require_pillow() -> None:
    if Image is None:  # pragma: no cover
        raise RuntimeError(
            "Pillow is required for body-part extraction. Install with "
            "`pip install Pillow`."
        )


def content_bounding_box(image, bg_tolerance: int = 10):
    """Return the tight bounding box of the non-transparent/non-background area.

    Uses the alpha channel when present; otherwise treats the top-left pixel as
    the background colour and trims matching borders.
    """
    _require_pillow()
    if image.mode in ("RGBA", "LA") or (image.mode == "P" and "transparency" in image.info):
        rgba = image.convert("RGBA")
        alpha = rgba.split()[-1]
        box = alpha.getbbox()
        if box:
            return box
        return (0, 0, image.width, image.height)

    rgb = image.convert("RGB")
    bg = rgb.getpixel((0, 0))
    # Build a mask of pixels that differ from the background colour.
    from PIL import ImageChops

    bg_img = Image.new("RGB", rgb.size, bg)
    diff = ImageChops.difference(rgb, bg_img).convert("L")
    mask = diff.point(lambda p: 255 if p > bg_tolerance else 0)
    box = mask.getbbox()
    if box:
        return box
    return (0, 0, image.width, image.height)


def _crop_with_alpha(image, rect: Tuple[int, int, int, int]):
    """Crop ``rect`` from ``image`` returning an RGBA sprite."""
    rgba = image.convert("RGBA")
    x0, y0, x1, y1 = rect
    x0 = max(0, min(x0, image.width))
    x1 = max(x0 + 1, min(x1, image.width))
    y0 = max(0, min(y0, image.height))
    y1 = max(y0 + 1, min(y1, image.height))
    return rgba.crop((x0, y0, x1, y1))


def extract_regions(
    image,
    regions: Dict[str, dict],
) -> ExtractionResult:
    """Crop parts from explicit rectangles defined in a character pack."""
    _require_pillow()
    parts: Dict[str, BodyPart] = {}
    default_pivot, default_anchor = None, None
    for name, spec in regions.items():
        rect = tuple(int(v) for v in spec["rect"])  # (x0, y0, x1, y1)
        default_pivot, default_anchor = part_axis(name)
        pivot = spec.get("pivot", default_pivot)
        anchor = spec.get("anchor", default_anchor)
        sprite = _crop_with_alpha(image, rect)  # type: ignore[arg-type]
        parts[name] = BodyPart(
            name=name,
            image=sprite,
            size=sprite.size,
            pivot=Vec2(float(pivot[0]), float(pivot[1])),
            child_anchor=Vec2(float(anchor[0]), float(anchor[1])),
            source_rect=rect,  # type: ignore[arg-type]
        )
    return ExtractionResult(
        parts=parts,
        content_box=content_bounding_box(image),
        source_size=image.size,
        method="regions",
    )


def extract_auto_humanoid(image) -> ExtractionResult:
    """Cut a full-body upright image into standard humanoid parts.

    Uses :mod:`desktop_pet.rig.silhouette` to *measure* the drawing - locating
    the neck, shoulders, hips and the gap between the legs from the alpha mask -
    so the cuts follow the actual figure instead of fixed proportions. Falls back
    to proportion bands when the shape doesn't read as a humanoid (an abstract
    blob, a sitting pose, a creature).
    """
    _require_pillow()
    from . import silhouette as silhouette_mod

    try:
        shape = silhouette_mod.analyze(image)
    except Exception:
        shape = None

    if shape is None or not shape.confident:
        return _extract_bands(image, method="auto_humanoid")

    regions = regions_from_silhouette(shape)
    # A believable humanoid yields most of the standard parts; if the geometry
    # collapsed (tiny or overlapping rectangles), the bands are safer.
    if len(regions) < len(STANDARD_PARTS) - 2:
        return _extract_bands(image, method="auto_humanoid")

    result = extract_regions(image, regions)
    result.method = "auto_humanoid"
    result.content_box = shape.box
    result.skeleton = skeleton_from_silhouette(shape)
    return result


def regions_from_silhouette(shape) -> Dict[str, dict]:
    """Turn silhouette landmarks into per-part rectangles and pivots.

    Pivots matter as much as the rectangles: each is the point on the sprite
    that sits on the bone's joint, in the crop's own 0..1 space. A thigh pivots
    at its hip end, the head at its chin, and so on.
    """
    x0, y0, x1, y1 = shape.box
    regions: Dict[str, dict] = {}

    def add(name: str, rect, pivot, anchor=None) -> None:
        left, top, right, bottom = (int(round(v)) for v in rect)
        left = max(x0, left)
        right = min(x1, right)
        top = max(y0, top)
        bottom = min(y1, bottom)
        if right - left < 2 or bottom - top < 2:
            return
        if anchor is None:
            anchor = part_axis(name)[1]
        regions[name] = {
            "rect": [left, top, right, bottom],
            "pivot": list(pivot),
            "anchor": list(anchor),
        }

    # ---- head: top of the figure down through the neck ---------------------
    head_left, head_right = _extent_between(shape, y0, shape.neck_y)
    pad = (head_right - head_left) * 0.05
    head_bottom = shape.neck_y + (shape.shoulder_y - shape.neck_y) * 0.5
    add("head", (head_left - pad, y0, head_right + pad, head_bottom), (0.5, 0.93))

    # ---- torso and hips ----------------------------------------------------
    torso_left, torso_right = _core_extent(shape, shape.shoulder_y, shape.waist_y)
    add("torso", (torso_left, shape.neck_y, torso_right, shape.hip_y), (0.5, 0.97))

    hip_left, hip_right = _core_extent(shape, shape.hip_y, shape.crotch_y)
    add("hips", (hip_left, shape.hip_y, hip_right, shape.crotch_y), (0.5, 0.5))

    # ---- arms --------------------------------------------------------------
    arm_top = shape.shoulder_y
    arm_bottom = shape.crotch_y
    arm_span = max(1.0, arm_bottom - arm_top)
    if shape.arms_detached and shape.arm_bounds:
        (left_lo, left_hi), (right_lo, right_hi) = shape.arm_bounds
    else:
        # Arms lie against the body: take the outer slice of the torso band.
        body_left, body_right = _extent_between(shape, arm_top, arm_bottom)
        arm_width = max(3.0, (body_right - body_left) * 0.22)
        left_lo, left_hi = body_left, body_left + arm_width
        right_lo, right_hi = body_right - arm_width, body_right

    for side, (lo, hi) in (("l", (left_lo, left_hi)), ("r", (right_lo, right_hi))):
        upper_bottom = arm_top + arm_span * 0.42
        fore_bottom = arm_top + arm_span * 0.78
        add(f"upper_arm_{side}", (lo, arm_top, hi, upper_bottom), (0.5, 0.08))
        add(f"forearm_{side}", (lo, upper_bottom, hi, fore_bottom), (0.5, 0.05))
        add(f"hand_{side}", (lo, fore_bottom, hi, arm_bottom), (0.5, 0.1))

    # ---- legs --------------------------------------------------------------
    leg_top = shape.crotch_y
    foot_top = max(shape.foot_top, leg_top + (y1 - leg_top) * 0.55)
    leg_span = max(1.0, foot_top - leg_top)
    knee_y = leg_top + leg_span * 0.5
    split = shape.leg_split_x

    # Measure the legs from the knees down: hands often hang past the crotch,
    # and including those rows would stretch the leg boxes out to the arms.
    legs_left, legs_right = _extent_between(shape, knee_y, y1)
    # Legs descend from the hips, so clamp them to a sane multiple of hip width
    # (guards against a wide skirt/cape or a shadow under the feet).
    hip_width = max(1.0, hip_right - hip_left)
    legs_left = max(legs_left, hip_left - hip_width * 0.3)
    legs_right = min(legs_right, hip_right + hip_width * 0.3)
    if legs_right - legs_left < hip_width * 0.4:  # clamp collapsed it
        legs_left, legs_right = hip_left, hip_right
    split = min(max(split, legs_left + 2), legs_right - 2)

    for side, (lo, hi) in (("l", (legs_left, split)), ("r", (split, legs_right))):
        if hi - lo < 2:
            continue
        add(f"thigh_{side}", (lo, leg_top, hi, knee_y), (0.5, 0.06))
        add(f"shin_{side}", (lo, knee_y, hi, foot_top), (0.5, 0.04))
        add(f"foot_{side}", (lo - 2, foot_top, hi + 2, y1), (0.5, 0.2))

    return regions


def skeleton_from_silhouette(shape) -> List[dict]:
    """Derive bone lengths from the measured figure, as character.json specs.

    An imported character should keep *its own* build - a long-legged hero
    shouldn't be squashed onto the built-in chibi rig, and a big-headed mascot
    shouldn't be stretched onto a realistic one. Bone lengths therefore come
    straight from the silhouette landmarks (in source pixels; the runtime scale
    normalises overall size). Rest angles are the standard standing pose.
    """
    _, y0, _, y1 = shape.box
    height = max(1.0, y1 - y0)

    head_len = max(6.0, shape.neck_y - y0)
    torso_len = max(6.0, shape.hip_y - shape.shoulder_y)
    hips_len = max(2.0, shape.crotch_y - shape.hip_y)

    arm_span = max(6.0, shape.crotch_y - shape.shoulder_y)
    upper_arm = arm_span * 0.42
    forearm = arm_span * 0.36
    hand = arm_span * 0.22

    foot_top = max(shape.foot_top, shape.crotch_y + (y1 - shape.crotch_y) * 0.55)
    leg_span = max(6.0, foot_top - shape.crotch_y)
    thigh = leg_span * 0.5
    shin = leg_span * 0.5
    foot = max(3.0, (y1 - foot_top))

    # Normalise so a character is ~170 rig units tall regardless of image size;
    # the user's scale setting then means the same thing for every character.
    unit = 170.0 / height

    def L(value: float) -> float:
        return round(value * unit, 2)

    template = {spec.name: spec for spec in DEFAULT_HUMANOID}
    lengths = {
        "hips": L(hips_len),
        "torso": L(torso_len),
        "head": L(head_len),
        "upper_arm_l": L(upper_arm), "forearm_l": L(forearm), "hand_l": L(hand),
        "upper_arm_r": L(upper_arm), "forearm_r": L(forearm), "hand_r": L(hand),
        "thigh_l": L(thigh), "shin_l": L(shin), "foot_l": L(foot),
        "thigh_r": L(thigh), "shin_r": L(shin), "foot_r": L(foot),
    }

    bones: List[dict] = []
    for spec in DEFAULT_HUMANOID:
        bones.append(
            {
                "name": spec.name,
                "parent": spec.parent,
                "length": lengths.get(spec.name, spec.length),
                "rest_angle": spec.rest_angle,
                "part": spec.part,
                "z_order": spec.z_order,
            }
        )
    return bones


def _extent_between(shape, top: float, bottom: float):
    """Leftmost/rightmost opaque column across the rows in ``[top, bottom]``."""
    left = None
    right = None
    for y in range(int(top), int(bottom) + 1):
        row = shape.row_at(y)
        if row is None or row.count == 0:
            continue
        left = row.left if left is None else min(left, row.left)
        right = row.right if right is None else max(right, row.right)
    if left is None or right is None:
        return shape.box[0], shape.box[2]
    return left, right


def _core_extent(shape, top: float, bottom: float):
    """Torso extent, ignoring arms when they are held away from the body."""
    if shape.arms_detached and shape.arm_bounds:
        lefts, rights = [], []
        for y in range(int(top), int(bottom) + 1):
            row = shape.row_at(y)
            if row is None or len(row.runs) < 3:
                continue
            middle = row.runs[len(row.runs) // 2]  # the torso itself
            lefts.append(middle[0])
            rights.append(middle[1])
        if lefts and rights:
            return min(lefts), max(rights)
    return _extent_between(shape, top, bottom)


def _extract_bands(image, method: str = "auto_humanoid") -> ExtractionResult:
    """Fixed-proportion fallback used when the silhouette isn't humanoid."""
    box = content_bounding_box(image)
    bx0, by0, bx1, by1 = box
    bw = bx1 - bx0
    bh = by1 - by0

    parts: Dict[str, BodyPart] = {}
    for name, fx0, fy0, fx1, fy1, pivx, pivy in _HUMANOID_BANDS:
        rect = (
            int(bx0 + fx0 * bw),
            int(by0 + fy0 * bh),
            int(bx0 + fx1 * bw),
            int(by0 + fy1 * bh),
        )
        sprite = _crop_with_alpha(image, rect)
        _, anchor = part_axis(name)
        parts[name] = BodyPart(
            name=name,
            image=sprite,
            size=sprite.size,
            pivot=Vec2(pivx, pivy),
            child_anchor=Vec2(*anchor),
            source_rect=rect,
        )
    return ExtractionResult(
        parts=parts,
        content_box=box,
        source_size=image.size,
        method="auto_humanoid",
    )


def extract_with_pose(image) -> ExtractionResult:
    """Extract parts using MediaPipe pose landmarks when available.

    Falls back to :func:`extract_auto_humanoid` if MediaPipe (or its runtime)
    is not installed, so callers never have to guard the import themselves.
    """
    _require_pillow()
    try:  # pragma: no cover - exercised only where mediapipe is installed
        import numpy as np
        import mediapipe as mp
    except Exception:
        return extract_auto_humanoid(image)

    # pragma: no cover below - requires the optional heavy dependency.
    rgb = image.convert("RGB")
    frame = np.asarray(rgb)
    with mp.solutions.pose.Pose(static_image_mode=True) as pose:  # type: ignore
        result = pose.process(frame)
    if not result.pose_landmarks:
        return extract_auto_humanoid(image)

    lm = result.pose_landmarks.landmark
    w, h = rgb.size

    def px(idx) -> Vec2:
        p = lm[idx]
        return Vec2(p.x * w, p.y * h)

    P = mp.solutions.pose.PoseLandmark  # type: ignore
    # Derive rectangles from landmark pairs; padded so limbs aren't clipped.
    regions = _regions_from_landmarks(px, P, w, h)
    result_obj = extract_regions(image, regions)
    result_obj.method = "pose"
    return result_obj


def _regions_from_landmarks(px, P, w, h) -> Dict[str, dict]:  # pragma: no cover
    """Translate MediaPipe landmarks into part rectangles (helper for pose)."""

    def rect_between(a: Vec2, b: Vec2, pad: float) -> List[int]:
        x0 = min(a.x, b.x) - pad
        y0 = min(a.y, b.y) - pad
        x1 = max(a.x, b.x) + pad
        y1 = max(a.y, b.y) + pad
        return [int(x0), int(y0), int(x1), int(y1)]

    pad = 0.04 * h
    shoulder_l, shoulder_r = px(P.LEFT_SHOULDER), px(P.RIGHT_SHOULDER)
    hip_l, hip_r = px(P.LEFT_HIP), px(P.RIGHT_HIP)
    return {
        "head": rect_between(px(P.LEFT_EAR), px(P.RIGHT_EAR), pad * 1.6),
        "torso": rect_between(shoulder_l, hip_r, pad),
        "hips": rect_between(hip_l, hip_r, pad),
        "upper_arm_l": rect_between(shoulder_l, px(P.LEFT_ELBOW), pad),
        "forearm_l": rect_between(px(P.LEFT_ELBOW), px(P.LEFT_WRIST), pad),
        "hand_l": rect_between(px(P.LEFT_WRIST), px(P.LEFT_INDEX), pad),
        "upper_arm_r": rect_between(shoulder_r, px(P.RIGHT_ELBOW), pad),
        "forearm_r": rect_between(px(P.RIGHT_ELBOW), px(P.RIGHT_WRIST), pad),
        "hand_r": rect_between(px(P.RIGHT_WRIST), px(P.RIGHT_INDEX), pad),
        "thigh_l": rect_between(hip_l, px(P.LEFT_KNEE), pad),
        "shin_l": rect_between(px(P.LEFT_KNEE), px(P.LEFT_ANKLE), pad),
        "foot_l": rect_between(px(P.LEFT_ANKLE), px(P.LEFT_FOOT_INDEX), pad),
        "thigh_r": rect_between(hip_r, px(P.RIGHT_KNEE), pad),
        "shin_r": rect_between(px(P.RIGHT_KNEE), px(P.RIGHT_ANKLE), pad),
        "foot_r": rect_between(px(P.RIGHT_ANKLE), px(P.RIGHT_FOOT_INDEX), pad),
    }


def extract(image, method: str = "auto_humanoid", **kwargs) -> ExtractionResult:
    """Dispatch to the requested extraction strategy."""
    if method == "regions":
        return extract_regions(image, kwargs["regions"])
    if method == "pose":
        return extract_with_pose(image)
    if method == "auto_humanoid":
        return extract_auto_humanoid(image)
    raise ValueError(f"Unknown extraction method: {method!r}")


def save_parts(result: ExtractionResult, out_dir: str) -> Dict[str, str]:
    """Write every extracted sprite to ``out_dir`` as a PNG."""
    _require_pillow()
    os.makedirs(out_dir, exist_ok=True)
    paths: Dict[str, str] = {}
    for name, part in result.parts.items():
        if part.image is None:
            continue
        path = os.path.join(out_dir, f"{name}.png")
        part.image.save(path)
        paths[name] = path
    return paths


def load_parts_from_dir(out_dir: str, names: Optional[List[str]] = None) -> Dict[str, BodyPart]:
    """Load previously extracted part PNGs from ``out_dir``."""
    _require_pillow()
    names = names or STANDARD_PARTS
    parts: Dict[str, BodyPart] = {}
    for name in names:
        path = os.path.join(out_dir, f"{name}.png")
        if os.path.exists(path):
            sprite = Image.open(path).convert("RGBA")
            pivot, anchor = part_axis(name)
            parts[name] = BodyPart(
                name=name,
                image=sprite,
                size=sprite.size,
                pivot=Vec2(*pivot),
                child_anchor=Vec2(*anchor),
            )
    return parts
