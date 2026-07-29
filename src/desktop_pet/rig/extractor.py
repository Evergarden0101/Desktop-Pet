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
#
# Bones that point *up* the body (hips -> torso -> head) need sprites that run
# bottom-to-top: the joint is at the sprite's lower edge and the art extends
# above it. Limb bones point down from their proximal joint and run the usual
# top-to-bottom way. Getting the torso wrong is not a subtle bug - the pivot
# and anchor collapse onto each other, the measured sprite axis becomes a few
# pixels, and the part is then scaled up by an enormous factor.
_PART_AXES: Dict[str, Tuple[Tuple[float, float], Tuple[float, float]]] = {
    "head": ((0.5, 0.93), (0.5, 0.05)),
    "torso": ((0.5, 0.97), (0.5, 0.03)),
    "hips": ((0.5, 0.92), (0.5, 0.08)),
}
_DEFAULT_AXIS = ((0.5, 0.06), (0.5, 0.94))

#: Parts every articulated figure must yield for the cut to be trusted. Arms
#: are deliberately absent: when they rest against the body they stay part of
#: the torso sprite rather than being sliced out (see regions_from_silhouette).
CORE_PARTS = frozenset(
    {
        "head", "torso", "hips",
        "thigh_l", "shin_l", "foot_l",
        "thigh_r", "shin_r", "foot_r",
    }
)


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
    #: "figure" (fully articulated) or "cutout" (head + body only).
    layout: str = "figure"
    #: Which analysis located the figure: "pose" (a detected human) or
    #: "outline" (silhouette measurement).
    detector: str = "outline"
    #: Colours sampled from the picture, keyed by part, for limbs that are
    #: drawn rather than cut out (``layout == "hybrid"``).
    palette: Optional[Dict[str, str]] = None
    #: Thickness of each drawn limb, in rig units.
    limb_radii: Optional[Dict[str, float]] = None
    #: How far off the body's centre line a drawn limb hangs, in rig units,
    #: keyed by the joint it hangs from ("torso" = shoulders, "hips").
    joint_offsets: Optional[Dict[str, float]] = None

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

    image, shape = _prepare(image)
    if shape is None or not shape.confident:
        return _extract_bands(image, method="auto_humanoid")

    # Can this picture actually supply limbs worth animating? Folded arms and a
    # shot cropped at the thigh cannot: slicing "legs" out of a block of denim
    # gives a pet that walks on two rectangles. Whatever the picture can't
    # supply is *drawn* instead, at anatomical proportions and in colours taken
    # from the picture, so it still looks like the same character.
    draw_arms, draw_legs = _limb_plan(shape)
    if draw_arms or draw_legs:
        return _extract_hybrid(image, shape, draw_arms, draw_legs)

    regions = regions_from_silhouette(shape)
    # Sanity gate: if the geometry collapsed (tiny or overlapping rectangles),
    # the proportion bands are safer. What counts as "enough" depends on the
    # layout - a cutout is meant to be just head + body, and a figure whose
    # arms stay inside the torso legitimately has no arm parts.
    required = {"head", "torso"} if shape.layout == "cutout" else CORE_PARTS
    if not required.issubset(regions):
        return _extract_bands(image, method="auto_humanoid")

    result = extract_regions(image, regions)
    result.method = "auto_humanoid"
    result.content_box = shape.box
    result.skeleton = skeleton_from_silhouette(shape)
    result.layout = shape.layout
    result.detector = getattr(shape, "source", "outline")
    return result


def _limb_plan(shape) -> Tuple[bool, bool]:
    """Decide which limbs have to be drawn instead of cut out.

    Returns ``(draw_arms, draw_legs)``. Cutting a limb out is always preferable
    *when the picture really shows it* - those pixels are the character. The
    two cases where it doesn't work:

    **Arms.** Folded across the chest, or simply hanging against the body, they
    leave no gap to cut along. Slicing strips off the torso's edges just
    duplicates those pixels into blobs that swing about, so previously they
    were left baked into the torso - which meant the rig carried no arm bones
    at all, and a pet with no arms can neither reach for a ledge while climbing
    nor wave when you poke it. Drawing them fixes both.

    **Legs.** Only a detector can *know* legs are missing: its landmarks carry a
    confidence, so "no knees and no ankles in this photo" is a measurement.
    Reading the outline alone, a failed leg split usually just means the legs
    are pressed together - and those pixels really are the legs, so they get
    cut as before.

    An abstract shape (a ball, a mascot with no head-on-body structure) is
    rigged as a cutout on purpose; giving it human arms and legs would be worse
    than the single body sprite it gets today.
    """
    humanoid = getattr(shape, "source", "outline") == "pose"
    if shape.layout == "cutout" and not humanoid:
        return (False, False)
    return (not shape.arms_detached, humanoid and not shape.legs_detected)


def _extract_hybrid(image, shape, draw_arms: bool, draw_legs: bool) -> ExtractionResult:
    """Cut what the picture supplies; draw the rest in the picture's colours."""
    from . import palette as palette_mod

    regions = hybrid_regions(shape, draw_arms, draw_legs)
    if "head" not in regions or "torso" not in regions:
        return _extract_bands(image, method="auto_humanoid")

    result = extract_regions(image, regions)
    result.method = "auto_humanoid"
    result.content_box = shape.box
    result.skeleton = hybrid_skeleton(shape, draw_arms, draw_legs)
    result.layout = "hybrid"
    result.detector = getattr(shape, "source", "outline")

    try:
        colours = palette_mod.sample_character(image, shape, getattr(shape, "person", None))
    except Exception:
        colours = {}
    unit = hybrid_unit(shape, draw_arms, draw_legs)
    result.palette = palette_mod.limb_palette(colours)
    result.limb_radii = limb_radii_for(shape, unit)
    result.joint_offsets = joint_offsets_for(shape, unit)
    return result


def _prepare(image):
    """Return ``(image, shape)``: the picture to cut from, and its landmarks.

    Two things happen here, and the order matters.

    **The person is lifted off the background.** A photograph is an opaque
    rectangle, so *every* measurement and every crop taken from it would carry
    a slab of wall or sky along with the body - the pet would be a photo with
    corners, and the "head" would be a strip of whatever was behind it. When
    the pose model returns a segmentation mask it becomes the image's alpha
    channel, and everything downstream sees the person alone.

    **The figure is located, detector first.** Outline analysis is defeated by
    photographs: hair covering the shoulders makes the widest point of the
    upper body land inside the hair, so the head comes out half a face tall.
    The model's landmarks win when they're available; otherwise we read the
    silhouette, which is the right tool for clean artwork.
    """
    from . import detect, silhouette as silhouette_mod

    try:
        person = detect.detect_person(image)
    except Exception:
        person = None

    if person is not None:
        try:
            cut = detect.cutout(image, person)
        except Exception:
            cut = None
        if cut is not None:
            image = cut
        try:
            shape = silhouette_mod.from_person(image, person)
            if shape is not None:
                return image, shape
        except Exception:
            pass

    try:
        return image, silhouette_mod.analyze(image)
    except Exception:
        return image, None


def regions_from_silhouette(shape) -> Dict[str, dict]:
    """Turn silhouette landmarks into per-part rectangles and pivots.

    Pivots matter as much as the rectangles: each is the point on the sprite
    that sits on the bone's joint, in the crop's own 0..1 space. A thigh pivots
    at its hip end, the head at its chin, and so on.
    """
    x0, y0, x1, y1 = shape.box
    regions: Dict[str, dict] = {}

    def add(name: str, rect, pivot=None, anchor=None) -> None:
        left, top, right, bottom = (int(round(v)) for v in rect)
        left = max(x0, left)
        right = min(x1, right)
        top = max(y0, top)
        bottom = min(y1, bottom)
        if right - left < 2 or bottom - top < 2:
            return
        default_pivot, default_anchor = part_axis(name)
        regions[name] = {
            "rect": [left, top, right, bottom],
            "pivot": list(pivot if pivot is not None else default_pivot),
            "anchor": list(anchor if anchor is not None else default_anchor),
        }

    # ---- head: top of the figure down through the neck ---------------------
    head_left, head_right = _extent_between(shape, y0, shape.neck_y)
    pad = (head_right - head_left) * 0.05
    head_bottom = shape.neck_y + (shape.shoulder_y - shape.neck_y) * 0.5
    add("head", (head_left - pad, y0, head_right + pad, head_bottom))

    if shape.layout == "cutout":
        # No usable legs in the picture (a bust or waist-up crop): keep the
        # body as one piece so the pet still looks exactly like the source.
        body_left, body_right = _extent_between(shape, shape.shoulder_y, y1)
        add("torso", (body_left, shape.neck_y, body_right, y1))
        return regions

    # ---- torso and hips ----------------------------------------------------
    torso_left, torso_right = _core_extent(shape, shape.shoulder_y, shape.waist_y)
    add("torso", (torso_left, shape.neck_y, torso_right, shape.hip_y))

    hip_left, hip_right = _core_extent(shape, shape.hip_y, shape.crotch_y)
    add("hips", (hip_left, shape.hip_y, hip_right, shape.crotch_y))

    # ---- arms --------------------------------------------------------------
    # Only cut arms out when they are actually separable from the body. If they
    # rest against (or are folded across) the torso - which is most photographs
    # - the torso crop already contains them, and slicing thin strips off its
    # edges just duplicates those pixels into limbs that then swing around as
    # detached blobs. Leaving them baked into the torso looks far better; the
    # body simply leans as one piece.
    if shape.arms_detached and shape.arm_bounds:
        arm_top = shape.shoulder_y
        arm_bottom = shape.crotch_y
        arm_span = max(1.0, arm_bottom - arm_top)
        (left_lo, left_hi), (right_lo, right_hi) = shape.arm_bounds
        for side, (lo, hi) in (("l", (left_lo, left_hi)), ("r", (right_lo, right_hi))):
            upper_bottom = arm_top + arm_span * 0.42
            fore_bottom = arm_top + arm_span * 0.78
            add(f"upper_arm_{side}", (lo, arm_top, hi, upper_bottom))
            add(f"forearm_{side}", (lo, upper_bottom, hi, fore_bottom))
            add(f"hand_{side}", (lo, fore_bottom, hi, arm_bottom))

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
        add(f"thigh_{side}", (lo, leg_top, hi, knee_y))
        add(f"shin_{side}", (lo, knee_y, hi, foot_top))
        add(f"foot_{side}", (lo - 2, foot_top, hi + 2, y1), pivot=(0.5, 0.2))

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

    if shape.layout == "cutout":
        return _cutout_skeleton(shape)

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

    lengths = {
        "hips": L(hips_len),
        "torso": L(torso_len),
        "head": L(head_len),
        "upper_arm_l": L(upper_arm), "forearm_l": L(forearm), "hand_l": L(hand),
        "upper_arm_r": L(upper_arm), "forearm_r": L(forearm), "hand_r": L(hand),
        "thigh_l": L(thigh), "shin_l": L(shin), "foot_l": L(foot),
        "thigh_r": L(thigh), "shin_r": L(shin), "foot_r": L(foot),
    }

    # Arms that could not be separated stay baked into the torso sprite, so the
    # rig must not carry arm bones for them - an bone with no part would just
    # animate nothing while widening the pet's bounds.
    skip = set()
    if not shape.arms_detached:
        for side in ("l", "r"):
            skip |= {f"upper_arm_{side}", f"forearm_{side}", f"hand_{side}"}

    bones: List[dict] = []
    for spec in DEFAULT_HUMANOID:
        if spec.name in skip:
            continue
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


#: Limb lengths as multiples of the character's own head height, from standard
#: figure-drawing proportions (a ~7.5-head adult). These are used when the limbs
#: have to be *drawn* rather than cut out, so they are believable by
#: construction instead of inheriting whatever the photo happened to show.
_LIMB_HEADS = {
    "upper_arm": 1.15, "forearm": 1.05, "hand": 0.38,
    "thigh": 1.70, "shin": 1.55, "foot": 0.36,
}


#: Shoulder-to-hip length of a standard figure, in head heights. Used to read a
#: head-equivalent off the torso, which is the more trustworthy measurement.
TORSO_HEADS = 2.2

#: Every character is normalised to this standing height in rig units, so the
#: user's scale setting means the same thing whatever picture they imported.
RIG_HEIGHT = 170.0


def _head_height(shape) -> float:
    """Crown-to-chin height of the head crop."""
    y0 = shape.box[1]
    head_bottom = shape.neck_y + (shape.shoulder_y - shape.neck_y) * 0.5
    return max(6.0, head_bottom - y0)


def _limb_unit(shape) -> float:
    """One "head" of anatomy in source pixels - the scale drawn limbs use.

    The head crop is the obvious candidate and the least trustworthy one: it
    starts at the top of the picture's content, so a hat, a ponytail or simply
    a portrait shot at close range all inflate it, and limbs quoted in heads
    then put the pet on stilts. The torso is measured shoulder-to-hip - between
    two landmark pairs on the pose path - and is about
    :data:`TORSO_HEADS` heads on a standard figure, so it is the better ruler.

    Taking the smaller of the two keeps whichever measurement was truncated
    from stretching the limbs: a big-haired portrait falls back to its torso, a
    figure whose hips had to be guessed falls back to its head.
    """
    head = _head_height(shape)
    torso = shape.hip_y - shape.shoulder_y
    if torso > 4:
        return max(6.0, min(head, torso / TORSO_HEADS))
    return head


def _hybrid_lengths(shape, draw_arms: bool, draw_legs: bool) -> Dict[str, float]:
    """Every bone length for a hybrid rig, in **source pixels**.

    Anything cut from the picture keeps its *measured* length, so the pet still
    has the character's own build. Anything drawn gets an anatomical length -
    a multiple of :func:`_limb_unit` from :data:`_LIMB_HEADS` - which is
    believable by construction rather than inheriting whatever the photo
    happened to show; a shot cropped at the thigh has no leg length to read.
    """
    _, _, _, y1 = shape.box
    anatomy = _limb_unit(shape)

    lengths = {
        "head": _head_height(shape),
        "torso": max(6.0, shape.hip_y - shape.shoulder_y),
    }

    if draw_arms:
        for side in ("l", "r"):
            for key in ("upper_arm", "forearm", "hand"):
                lengths[f"{key}_{side}"] = anatomy * _LIMB_HEADS[key]
    else:
        arm_span = max(6.0, shape.crotch_y - shape.shoulder_y)
        for side in ("l", "r"):
            lengths[f"upper_arm_{side}"] = arm_span * 0.42
            lengths[f"forearm_{side}"] = arm_span * 0.36
            lengths[f"hand_{side}"] = arm_span * 0.22

    if draw_legs:
        lengths["hips"] = max(3.0, anatomy * 0.22)
        for side in ("l", "r"):
            for key in ("thigh", "shin", "foot"):
                lengths[f"{key}_{side}"] = anatomy * _LIMB_HEADS[key]
    else:
        lengths["hips"] = max(2.0, shape.crotch_y - shape.hip_y)
        foot_top = max(shape.foot_top, shape.crotch_y + (y1 - shape.crotch_y) * 0.55)
        leg_span = max(6.0, foot_top - shape.crotch_y)
        for side in ("l", "r"):
            lengths[f"thigh_{side}"] = leg_span * 0.5
            lengths[f"shin_{side}"] = leg_span * 0.5
            lengths[f"foot_{side}"] = max(3.0, y1 - foot_top)

    return lengths


def hybrid_unit(shape, draw_arms: bool = True, draw_legs: bool = True) -> float:
    """Rig units per source pixel for a hybrid character.

    Normalising by the *finished rig* rather than by the source crop is what
    keeps an imported photo the same size as every other character: a waist-up
    shot's drawn legs are height the crop never contained, so scaling by the
    crop would make that pet twice as tall at the same user scale setting.

    Radii and joint offsets have to use this too, or the limbs come out fat.
    """
    lengths = _hybrid_lengths(shape, draw_arms, draw_legs)
    standing = sum(
        lengths[name]
        for name in ("head", "torso", "hips", "thigh_l", "shin_l", "foot_l")
    )
    return RIG_HEIGHT / standing if standing > 1e-6 else 1.0


def hybrid_skeleton(shape, draw_arms: bool = True, draw_legs: bool = True) -> List[dict]:
    """Rig for a character whose limbs are partly drawn."""
    lengths = _hybrid_lengths(shape, draw_arms, draw_legs)
    unit = hybrid_unit(shape, draw_arms, draw_legs)
    return [
        {
            "name": spec.name,
            "parent": spec.parent,
            "length": round(lengths[spec.name] * unit, 2)
            if spec.name in lengths
            else spec.length,
            "rest_angle": spec.rest_angle,
            "part": spec.part,
            "z_order": spec.z_order,
        }
        for spec in DEFAULT_HUMANOID
    ]


def hybrid_regions(shape, draw_arms: bool = True, draw_legs: bool = True) -> Dict[str, dict]:
    """Cut the parts the picture supplies and leave the drawn ones out.

    A *missing* region is exactly what tells the renderer to paint that bone
    instead of blitting a sprite, so this is the one place that decides which
    limbs come from the picture.
    """
    if not draw_legs:
        # The picture has real legs, so take the full measured cut. Arms that
        # are being drawn simply have no region there either: they are only
        # ever added when the outline showed a gap to cut along.
        return regions_from_silhouette(shape)

    x0, y0, x1, y1 = shape.box
    regions: Dict[str, dict] = {}

    def add(name: str, rect) -> None:
        left, top, right, bottom = (int(round(v)) for v in rect)
        left, right = max(x0, left), min(x1, right)
        top, bottom = max(y0, top), min(y1, bottom)
        if right - left < 2 or bottom - top < 2:
            return
        pivot, anchor = part_axis(name)
        regions[name] = {
            "rect": [left, top, right, bottom],
            "pivot": list(pivot),
            "anchor": list(anchor),
        }

    head_left, head_right = _extent_between(shape, y0, shape.neck_y)
    pad = (head_right - head_left) * 0.05
    head_bottom = shape.neck_y + (shape.shoulder_y - shape.neck_y) * 0.5
    add("head", (head_left - pad, y0, head_right + pad, head_bottom))

    # Torso runs neck-to-hips: below that the drawn legs take over, so the
    # crop stops before any cropped-off denim can come along for the ride.
    torso_left, torso_right = _extent_between(shape, shape.shoulder_y, shape.hip_y)
    add("torso", (torso_left, shape.neck_y, torso_right, shape.hip_y))

    if not draw_arms and shape.arm_bounds:
        arm_top, arm_bottom = shape.shoulder_y, shape.crotch_y
        arm_span = max(1.0, arm_bottom - arm_top)
        (left_lo, left_hi), (right_lo, right_hi) = shape.arm_bounds
        for side, (lo, hi) in (("l", (left_lo, left_hi)), ("r", (right_lo, right_hi))):
            upper_bottom = arm_top + arm_span * 0.42
            fore_bottom = arm_top + arm_span * 0.78
            add(f"upper_arm_{side}", (lo, arm_top, hi, upper_bottom))
            add(f"forearm_{side}", (lo, upper_bottom, hi, fore_bottom))
            add(f"hand_{side}", (lo, fore_bottom, hi, arm_bottom))

    return regions


def _body_widths(shape) -> Tuple[float, float]:
    """Shoulder and hip widths in source pixels."""
    left, right = _extent_between(shape, shape.shoulder_y, shape.waist_y)
    shoulder_w = max(8.0, right - left)
    hip_left, hip_right = _extent_between(shape, shape.hip_y, shape.crotch_y)
    # A photo cropped at the hips has no rows between hip and crotch, so that
    # extent collapses to the whole frame; anatomy says hips are a little
    # narrower than shoulders, so cap it there rather than trusting the span.
    return shoulder_w, min(max(8.0, hip_right - hip_left), shoulder_w * 1.05)


def limb_radii_for(shape, unit: Optional[float] = None) -> Dict[str, float]:
    """Thickness of each drawn limb, in rig units, from the body's own width.

    ``unit`` is rig units per source pixel; pass the same value the skeleton
    was built with (:func:`hybrid_unit`) or the limbs won't match their bones.
    """
    if unit is None:
        unit = hybrid_unit(shape)
    shoulder_w, hip_w = _body_widths(shape)

    # Radii are *half*-widths, so a limb is twice as wide as the number here.
    arm = shoulder_w * 0.115 * unit
    leg = hip_w * 0.20 * unit
    return {
        "upper_arm_l": arm, "upper_arm_r": arm,
        "forearm_l": arm * 0.86, "forearm_r": arm * 0.86,
        "hand_l": arm * 0.92, "hand_r": arm * 0.92,
        "thigh_l": leg, "thigh_r": leg,
        "shin_l": leg * 0.82, "shin_r": leg * 0.82,
        # Feet are short bones, so a radius near their length rounds them into
        # boots; keep them slim and let the length read as the foot.
        "foot_l": leg * 0.62, "foot_r": leg * 0.62,
        "hips": hip_w * 0.30 * unit,
    }


def joint_offsets_for(shape, unit: Optional[float] = None) -> Dict[str, float]:
    """How far each drawn limb hangs off the body's centre line, in rig units.

    Arms are set just inside the shoulder line and legs just inside the hips,
    so a photograph's wide torso gets arms at its corners rather than a pair
    sprouting from the middle of the chest. ``unit`` is as in
    :func:`limb_radii_for`.
    """
    if unit is None:
        unit = hybrid_unit(shape)
    shoulder_w, hip_w = _body_widths(shape)
    return {
        "torso": shoulder_w * 0.34 * unit,
        "hips": hip_w * 0.22 * unit,
    }


def _cutout_skeleton(shape) -> List[dict]:
    """Two-bone rig for pictures that have no usable legs.

    A bust or waist-up photo can't be articulated honestly, but it still makes
    a fine pet: the body stays one piece and only leans and bobs, driven by the
    ``torso``/``head`` deltas the ordinary poses already contain. Behaviours
    address missing bones harmlessly - blending skips unknown names and the
    climbing IK catches the lookup - so walking, climbing and sitting all work.
    """
    _, y0, _, y1 = shape.box
    height = max(1.0, y1 - y0)
    unit = 170.0 / height

    head_len = max(6.0, (shape.neck_y - y0)) * unit
    body_len = max(6.0, (y1 - shape.neck_y)) * unit
    return [
        {"name": "hips", "parent": None, "length": 2.0, "rest_angle": -1.5708,
         "part": None, "z_order": 5},
        {"name": "torso", "parent": "hips", "length": round(body_len, 2),
         "rest_angle": 0.0, "part": "torso", "z_order": 6},
        {"name": "head", "parent": "torso", "length": round(head_len, 2),
         "rest_angle": 0.0, "part": "head", "z_order": 10},
    ]


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
    """Extract using the pose detector explicitly.

    ``auto_humanoid`` already prefers the detector when it is installed, so
    this exists mainly to *require* it: if the model or library is missing the
    call still succeeds via silhouette analysis, but ``result.detector`` will
    say so.
    """
    _require_pillow()
    result = extract_auto_humanoid(image)
    result.method = "pose"
    return result


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
