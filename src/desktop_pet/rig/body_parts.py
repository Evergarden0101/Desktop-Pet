"""Body-part definitions and the default humanoid rig template.

A *body part* is one extracted image region (head, torso, forearm, ...) plus a
pivot describing where the part attaches to its parent bone. The default rig
below is a generic humanoid; character packs may override any of it through
their ``character.json``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from ..core.geometry import Vec2
from ..core.skeleton import Bone, Skeleton


@dataclass
class BodyPart:
    """One extracted sprite region and how it hangs off a bone.

    ``image`` is left untyped so this module stays importable without Pillow;
    at runtime it holds a ``PIL.Image.Image`` (or ``None`` before extraction).
    """

    name: str
    image: object = None
    size: Tuple[int, int] = (0, 0)
    # Pivot in normalized sprite coordinates (0..1): the point placed on the
    # bone's *near* joint.
    pivot: Vec2 = field(default_factory=lambda: Vec2(0.5, 0.1))
    # Where the bone's *far* end lands on the sprite, also normalized. Together
    # with ``pivot`` this defines the sprite's axis, so the renderer can map
    # pivot -> bone base and anchor -> bone tip. That handles parts whose art
    # runs "backwards" along the bone - most importantly the head, which grows
    # upward from the neck joint.
    child_anchor: Vec2 = field(default_factory=lambda: Vec2(0.5, 0.9))
    source_rect: Optional[Tuple[int, int, int, int]] = None


# Canonical part names. Character packs are free to add more, but these are the
# ones the built-in behaviours know how to animate.
STANDARD_PARTS: List[str] = [
    "hips",
    "torso",
    "head",
    "upper_arm_l",
    "forearm_l",
    "hand_l",
    "upper_arm_r",
    "forearm_r",
    "hand_r",
    "thigh_l",
    "shin_l",
    "foot_l",
    "thigh_r",
    "shin_r",
    "foot_r",
]

# Left/right limb chains, handy for behaviours and IK.
ARM_CHAINS = {
    "l": ("upper_arm_l", "forearm_l", "hand_l"),
    "r": ("upper_arm_r", "forearm_r", "hand_r"),
}
LEG_CHAINS = {
    "l": ("thigh_l", "shin_l", "foot_l"),
    "r": ("thigh_r", "shin_r", "foot_r"),
}


@dataclass
class BoneSpec:
    """Serializable description of a bone used to build a :class:`Skeleton`."""

    name: str
    parent: Optional[str]
    length: float
    rest_angle: float
    part: Optional[str]
    z_order: int = 0
    pivot: Tuple[float, float] = (0.5, 0.05)


# The default humanoid rig, drawn in a neutral standing pose. Angles are in
# radians in screen space: 0 points to the character's right (+X) and +pi/2
# points down (+Y). ``local_angle`` is measured relative to the parent bone.
#
# Geometry check for the standing pose (facing right, base 0):
#   * ``hips`` (root) points up (-pi/2), so its tip is the pelvis joint from
#     which the torso rises and the thighs descend.
#   * ``torso``/``head`` continue straight up (local 0).
#   * thighs get local ~pi so they end up pointing down (world ~+pi/2).
#   * feet get local ~-1.4 so they point forward (world ~0).
# Lengths are "rig units" multiplied by the character scale at runtime.
#
# Proportions follow a stylised ~6.5-head figure (a slightly cute but still
# believably human build; a strict anatomical figure is 7.5-8 heads, which
# reads as gangly at desktop-pet sizes). With head length 26:
#   total height ~= hips 4 + torso 52 + head 26 + neck gap  ~= 6.4 heads
#   leg (thigh 44 + shin 40 + ankle) ~= 47% of height, as in a real figure
#   arm (upper 32 + fore 28 + hand 10) reaches mid-thigh when hanging
DEFAULT_HUMANOID: List[BoneSpec] = [
    BoneSpec("hips", None, 4.0, -1.5708, "hips", z_order=5),          # points up
    BoneSpec("torso", "hips", 52.0, 0.0, "torso", z_order=6),
    BoneSpec("head", "torso", 26.0, 0.0, "head", z_order=10),

    # Arms hang down close to the body, splaying only slightly outward.
    BoneSpec("upper_arm_l", "torso", 32.0, 3.32, "upper_arm_l", z_order=4),
    BoneSpec("forearm_l", "upper_arm_l", 28.0, 0.12, "forearm_l", z_order=3),
    BoneSpec("hand_l", "forearm_l", 10.0, 0.0, "hand_l", z_order=3),

    BoneSpec("upper_arm_r", "torso", 32.0, 2.96, "upper_arm_r", z_order=11),
    BoneSpec("forearm_r", "upper_arm_r", 28.0, 0.12, "forearm_r", z_order=12),
    BoneSpec("hand_r", "forearm_r", 10.0, 0.0, "hand_r", z_order=13),

    # Legs descend from the pelvis (hips tip), nearly vertical; feet point
    # forward. A small outward splay keeps them from overlapping exactly.
    BoneSpec("thigh_l", "hips", 44.0, 3.20, "thigh_l", z_order=4),
    BoneSpec("shin_l", "thigh_l", 40.0, 0.04, "shin_l", z_order=3),
    BoneSpec("foot_l", "shin_l", 13.0, -1.42, "foot_l", z_order=3),

    BoneSpec("thigh_r", "hips", 44.0, 3.08, "thigh_r", z_order=7),
    BoneSpec("shin_r", "thigh_r", 40.0, 0.04, "shin_r", z_order=6),
    BoneSpec("foot_r", "shin_r", 13.0, -1.42, "foot_r", z_order=6),
]


#
# "Cute" (chibi) proportions: a big round head on a small body, ~3 heads tall.
# This is the classic desktop-mascot look and reads much better at the small
# sizes a desktop pet is actually drawn at, where a realistic 6-7 head figure
# turns into a spindly stick.
CUTE_HUMANOID: List[BoneSpec] = [
    BoneSpec("hips", None, 4.0, -1.5708, "hips", z_order=5),
    BoneSpec("torso", "hips", 34.0, 0.0, "torso", z_order=6),
    BoneSpec("head", "torso", 42.0, 0.0, "head", z_order=10),

    BoneSpec("upper_arm_l", "torso", 19.0, 3.34, "upper_arm_l", z_order=4),
    BoneSpec("forearm_l", "upper_arm_l", 17.0, 0.16, "forearm_l", z_order=3),
    BoneSpec("hand_l", "forearm_l", 8.0, 0.0, "hand_l", z_order=3),

    BoneSpec("upper_arm_r", "torso", 19.0, 2.94, "upper_arm_r", z_order=11),
    BoneSpec("forearm_r", "upper_arm_r", 17.0, 0.16, "forearm_r", z_order=12),
    BoneSpec("hand_r", "forearm_r", 8.0, 0.0, "hand_r", z_order=13),

    BoneSpec("thigh_l", "hips", 24.0, 3.22, "thigh_l", z_order=4),
    BoneSpec("shin_l", "thigh_l", 22.0, 0.05, "shin_l", z_order=3),
    BoneSpec("foot_l", "shin_l", 11.0, -1.45, "foot_l", z_order=3),

    BoneSpec("thigh_r", "hips", 24.0, 3.06, "thigh_r", z_order=7),
    BoneSpec("shin_r", "thigh_r", 22.0, 0.05, "shin_r", z_order=6),
    BoneSpec("foot_r", "shin_r", 11.0, -1.45, "foot_r", z_order=6),
]

#: Selectable body styles. ``radii`` are capsule half-thicknesses in rig units
#: and ``head_ratio``/``eye_scale`` tune the drawn head and face.
BODY_STYLES = {
    "cute": {
        "label": "Cute (big head, chibi)",
        "specs": CUTE_HUMANOID,
        "radii": {
            "torso": 15.0, "hips": 13.5,
            "upper_arm_l": 6.0, "forearm_l": 5.4, "hand_l": 5.6,
            "upper_arm_r": 6.0, "forearm_r": 5.4, "hand_r": 5.6,
            "thigh_l": 8.0, "shin_l": 7.0, "foot_l": 6.2,
            "thigh_r": 8.0, "shin_r": 7.0, "foot_r": 6.2,
        },
        "head_ratio": 0.56,
        "eye_scale": 1.9,     # big sparkly eyes
        "outline_width": 3.2,
    },
    "human": {
        "label": "Human (realistic proportions)",
        "specs": DEFAULT_HUMANOID,
        "radii": {
            "torso": 15.0, "hips": 13.0,
            "upper_arm_l": 6.0, "forearm_l": 5.0, "hand_l": 5.5,
            "upper_arm_r": 6.0, "forearm_r": 5.0, "hand_r": 5.5,
            "thigh_l": 8.5, "shin_l": 6.5, "foot_l": 5.5,
            "thigh_r": 8.5, "shin_r": 6.5, "foot_r": 5.5,
        },
        "head_ratio": 0.55,
        "eye_scale": 1.0,
        "outline_width": 3.0,
    },
}

DEFAULT_STYLE = "cute"


def style_config(style: Optional[str]) -> dict:
    """Return the :data:`BODY_STYLES` entry for ``style`` (falling back safely)."""
    return BODY_STYLES.get(style or DEFAULT_STYLE, BODY_STYLES[DEFAULT_STYLE])


def humanoid_specs(style: Optional[str] = None) -> List[BoneSpec]:
    return list(style_config(style)["specs"])


def build_skeleton(specs: List[BoneSpec]) -> Skeleton:
    """Instantiate a :class:`Skeleton` from a list of :class:`BoneSpec`."""
    bones: List[Bone] = []
    for spec in specs:
        bones.append(
            Bone(
                name=spec.name,
                length=spec.length,
                parent=spec.parent,
                rest_angle=spec.rest_angle,
                local_angle=spec.rest_angle,
                part=spec.part,
                z_order=spec.z_order,
                pivot=Vec2(*spec.pivot),
            )
        )
    return Skeleton(bones)


def default_skeleton(style: Optional[str] = None) -> Skeleton:
    return build_skeleton(humanoid_specs(style))


def specs_from_json(data: List[dict]) -> List[BoneSpec]:
    """Parse a ``skeleton.bones`` array from a character JSON file."""
    specs: List[BoneSpec] = []
    for entry in data:
        specs.append(
            BoneSpec(
                name=entry["name"],
                parent=entry.get("parent"),
                length=float(entry.get("length", 20.0)),
                rest_angle=float(entry.get("rest_angle", 0.0)),
                part=entry.get("part"),
                z_order=int(entry.get("z_order", 0)),
                pivot=tuple(entry.get("pivot", (0.5, 0.05))),  # type: ignore[arg-type]
            )
        )
    return specs


def z_ordered_bone_names(skeleton: Skeleton) -> List[str]:
    """Bone names sorted by draw order (back to front)."""
    return sorted(skeleton.bones, key=lambda n: skeleton.bones[n].z_order)
