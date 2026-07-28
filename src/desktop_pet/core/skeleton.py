"""A lightweight 2D skeletal-animation system.

The pet's body is decomposed into *bones*. Each bone owns a body-part sprite
(extracted from the character image) and is connected to a parent through a
joint. Forward kinematics (FK) turns a set of joint rotations into world-space
transforms for every bone; two-bone inverse kinematics (IK) lets a limb reach
toward a target point, which is what makes climbing, creeping and grabbing look
believable.

The module is pure Python so it can be tested without a display.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .geometry import Vec2, clamp, lerp, lerp_angle


@dataclass
class Bone:
    """A single rigid segment in the skeleton.

    Attributes
    ----------
    name:
        Unique identifier (e.g. ``"forearm_l"``).
    length:
        Distance from this bone's joint to its child joint, in local units.
    parent:
        Name of the parent bone, or ``None`` for the root.
    rest_angle:
        The bone's default local rotation (radians) relative to its parent.
    local_angle:
        The current local rotation relative to the parent. Animations write
        here; ``Skeleton.solve`` reads it.
    part:
        Name of the body-part sprite attached to this bone (``rig.body_parts``).
    z_order:
        Draw order. Higher numbers are painted on top.
    pivot:
        Where along the sprite the joint sits, in normalized (0..1) sprite
        coordinates. Defaults to the sprite's proximal edge centre.
    """

    name: str
    length: float
    parent: Optional[str] = None
    rest_angle: float = 0.0
    local_angle: float = 0.0
    part: Optional[str] = None
    z_order: int = 0
    pivot: Vec2 = field(default_factory=lambda: Vec2(0.5, 0.0))

    # Solved world-space values (filled by Skeleton.solve).
    world_pos: Vec2 = field(default_factory=Vec2)
    world_angle: float = 0.0

    @property
    def tip(self) -> Vec2:
        """World position of the far (child) end of the bone."""
        return self.world_pos + Vec2.from_angle(self.world_angle, self.length)


class Skeleton:
    """A hierarchy of bones with FK/IK solving.

    The skeleton is defined in a *local* coordinate space; the owner positions
    it in the world via :attr:`root_position`, :attr:`facing` and
    :attr:`scale`.
    """

    def __init__(self, bones: List[Bone]):
        self.bones: Dict[str, Bone] = {}
        self.order: List[str] = []
        for bone in bones:
            self.add_bone(bone)

        self.root_position: Vec2 = Vec2(0.0, 0.0)
        self.scale: float = 1.0
        # ``facing`` is +1 for right-facing, -1 for left-facing (mirrored).
        self.facing: int = 1

    # ------------------------------------------------------------------ setup
    def add_bone(self, bone: Bone) -> None:
        if bone.name in self.bones:
            raise ValueError(f"Duplicate bone name: {bone.name}")
        if bone.parent is not None and bone.parent not in self.bones:
            raise ValueError(
                f"Bone '{bone.name}' references unknown parent '{bone.parent}'"
            )
        self.bones[bone.name] = bone
        self.order.append(bone.name)

    def root(self) -> Bone:
        for name in self.order:
            if self.bones[name].parent is None:
                return self.bones[name]
        raise ValueError("Skeleton has no root bone")

    def children_of(self, name: str) -> List[Bone]:
        return [b for b in self.bones.values() if b.parent == name]

    def reset_to_rest(self) -> None:
        for bone in self.bones.values():
            bone.local_angle = bone.rest_angle

    # -------------------------------------------------------------------- FK
    def solve(self) -> None:
        """Compute world transforms for every bone via forward kinematics.

        ``order`` preserves insertion order; because a parent is always added
        before its children, iterating it resolves the hierarchy in one pass.
        """
        for name in self.order:
            bone = self.bones[name]
            local = bone.local_angle * self.facing
            if bone.parent is None:
                bone.world_pos = self.root_position
                # Facing flips the whole rig around the vertical axis.
                base = 0.0 if self.facing >= 0 else math.pi
                bone.world_angle = base + local
            else:
                parent = self.bones[bone.parent]
                bone.world_pos = parent.tip_scaled(self.scale)
                bone.world_angle = parent.world_angle + local

    def tip_scaled_of(self, name: str) -> Vec2:
        bone = self.bones[name]
        return bone.world_pos + Vec2.from_angle(
            bone.world_angle, bone.length * self.scale
        )

    def world_length(self, name: str) -> float:
        return self.bones[name].length * self.scale

    # -------------------------------------------------------------------- IK
    def solve_two_bone_ik(
        self,
        upper: str,
        lower: str,
        target: Vec2,
        bend_positive: bool = True,
    ) -> bool:
        """Aim a two-bone chain (e.g. thigh+shin) at ``target``.

        Returns ``True`` if the target is reachable, ``False`` if the chain was
        stretched straight toward an out-of-range target. The result is written
        back into the two bones' ``local_angle`` so a subsequent :meth:`solve`
        renders the pose.
        """
        upper_bone = self.bones[upper]
        lower_bone = self.bones[lower]

        # Ensure world transforms up to the chain root are current.
        self.solve()
        origin = upper_bone.world_pos

        l1 = upper_bone.length * self.scale
        l2 = lower_bone.length * self.scale
        to_target = target - origin
        dist = clamp(to_target.length(), 1e-4, l1 + l2 - 1e-4)
        reachable = to_target.length() <= (l1 + l2)

        # Law of cosines for the interior joint angles.
        cos_upper = clamp((dist * dist + l1 * l1 - l2 * l2) / (2 * dist * l1), -1, 1)
        cos_lower = clamp((l1 * l1 + l2 * l2 - dist * dist) / (2 * l1 * l2), -1, 1)
        angle_a = math.acos(cos_upper)
        angle_b = math.acos(cos_lower)

        base_angle = to_target.angle()
        sign = 1.0 if bend_positive else -1.0

        upper_world = base_angle - sign * angle_a
        lower_world = upper_world + sign * (math.pi - angle_b)

        # Convert desired world angles back into local (parent-relative) angles.
        parent_angle = 0.0
        if upper_bone.parent is not None:
            parent_angle = self.bones[upper_bone.parent].world_angle

        upper_bone.local_angle = (upper_world - parent_angle) * self.facing
        lower_bone.local_angle = (lower_world - upper_world) * self.facing
        return reachable

    # ------------------------------------------------------------------ util
    def bounding_radius(self) -> float:
        """Rough radius (local units) used for coarse collision tests."""
        total = 0.0
        for bone in self.bones.values():
            total += bone.length
        return total * self.scale

    def snapshot(self) -> Dict[str, float]:
        """Capture current local angles keyed by bone name."""
        return {name: b.local_angle for name, b in self.bones.items()}

    def apply(self, angles: Dict[str, float]) -> None:
        for name, angle in angles.items():
            if name in self.bones:
                self.bones[name].local_angle = angle

    def blend(self, angles: Dict[str, float], t: float) -> None:
        """Blend current pose toward ``angles`` by factor ``t`` (angle-aware)."""
        for name, angle in angles.items():
            bone = self.bones.get(name)
            if bone is not None:
                bone.local_angle = lerp_angle(bone.local_angle, angle, t)


# ``Bone`` needs the scale-aware tip after the class body is defined; attach it
# here to keep the dataclass declaration readable above.
def _tip_scaled(self: Bone, scale: float) -> Vec2:
    return self.world_pos + Vec2.from_angle(self.world_angle, self.length * scale)


Bone.tip_scaled = _tip_scaled  # type: ignore[attr-defined]
