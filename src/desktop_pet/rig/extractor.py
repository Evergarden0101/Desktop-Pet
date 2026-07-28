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
from .body_parts import STANDARD_PARTS, BodyPart

try:  # Pillow is a hard dependency for extraction but soft for imports.
    from PIL import Image
except Exception:  # pragma: no cover - only when Pillow missing
    Image = None  # type: ignore


# A proportion band is (part_name, x0, y0, x1, y1, pivot_x, pivot_y) with all
# coordinates expressed as fractions of the *content* bounding box. The pivot is
# in the crop's own normalized space. These follow a ~7.5 head-height figure.
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

    def to_regions_dict(self) -> Dict[str, dict]:
        """Serialize as a ``regions`` extraction block for character.json."""
        out: Dict[str, dict] = {}
        for name, part in self.parts.items():
            if part.source_rect is None:
                continue
            out[name] = {
                "rect": list(part.source_rect),
                "pivot": [round(part.pivot.x, 4), round(part.pivot.y, 4)],
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
    for name, spec in regions.items():
        rect = tuple(int(v) for v in spec["rect"])  # (x0, y0, x1, y1)
        pivot = spec.get("pivot", [0.5, 0.05])
        sprite = _crop_with_alpha(image, rect)  # type: ignore[arg-type]
        parts[name] = BodyPart(
            name=name,
            image=sprite,
            size=sprite.size,
            pivot=Vec2(float(pivot[0]), float(pivot[1])),
            source_rect=rect,  # type: ignore[arg-type]
        )
    return ExtractionResult(
        parts=parts,
        content_box=content_bounding_box(image),
        source_size=image.size,
        method="regions",
    )


def extract_auto_humanoid(image) -> ExtractionResult:
    """Slice a full-body upright image into standard humanoid parts.

    This is a heuristic: it assumes a single, roughly centred, front-facing
    figure standing with arms at the sides. Results are a good starting point;
    refine with the ``regions`` method or pose estimation for production packs.
    """
    _require_pillow()
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
        parts[name] = BodyPart(
            name=name,
            image=sprite,
            size=sprite.size,
            pivot=Vec2(pivx, pivy),
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
            parts[name] = BodyPart(name=name, image=sprite, size=sprite.size)
    return parts
