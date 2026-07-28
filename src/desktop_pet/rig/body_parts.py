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
    # Pivot in normalized sprite coordinates (0..1). This point is placed on the
    # bone's joint; the sprite is then rotated to the bone's world angle.
    pivot: Vec2 = field(default_factory=lambda: Vec2(0.5, 0.1))
    # Optional child anchor: where the *next* joint sits on this sprite, used to
    # derive bone length automatically during extraction.
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
DEFAULT_HUMANOID: List[BoneSpec] = [
    BoneSpec("hips", None, 4.0, -1.5708, "hips", z_order=5),          # points up
    BoneSpec("torso", "hips", 44.0, 0.0, "torso", z_order=6),
    BoneSpec("head", "torso", 32.0, 0.0, "head", z_order=10),

    # Arms hang down and splay slightly outward from the shoulders (torso tip).
    BoneSpec("upper_arm_l", "torso", 30.0, 3.39, "upper_arm_l", z_order=4),
    BoneSpec("forearm_l", "upper_arm_l", 26.0, 0.15, "forearm_l", z_order=3),
    BoneSpec("hand_l", "forearm_l", 12.0, 0.0, "hand_l", z_order=3),

    BoneSpec("upper_arm_r", "torso", 30.0, 2.89, "upper_arm_r", z_order=8),
    BoneSpec("forearm_r", "upper_arm_r", 26.0, 0.15, "forearm_r", z_order=9),
    BoneSpec("hand_r", "forearm_r", 12.0, 0.0, "hand_r", z_order=9),

    # Legs descend from the pelvis (hips tip); feet point forward.
    BoneSpec("thigh_l", "hips", 40.0, 3.22, "thigh_l", z_order=4),
    BoneSpec("shin_l", "thigh_l", 38.0, 0.05, "shin_l", z_order=3),
    BoneSpec("foot_l", "shin_l", 14.0, -1.40, "foot_l", z_order=3),

    BoneSpec("thigh_r", "hips", 40.0, 3.06, "thigh_r", z_order=7),
    BoneSpec("shin_r", "thigh_r", 38.0, 0.05, "shin_r", z_order=6),
    BoneSpec("foot_r", "shin_r", 14.0, -1.40, "foot_r", z_order=6),
]


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


def default_skeleton() -> Skeleton:
    return build_skeleton(DEFAULT_HUMANOID)


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
