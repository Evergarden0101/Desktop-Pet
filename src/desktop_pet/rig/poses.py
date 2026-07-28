"""Procedural pose generation for the standard humanoid rig.

Rather than hand-keying 15 bones across dozens of frames, poses are generated
from the rig's *rest* angles plus small per-bone deltas, many of them driven by
a cyclic ``phase`` (0..1). This keeps animation data tiny, works for any rig
whose rest pose differs, and makes actions such as walking, climbing and
creeping read as smooth loops.

A "pose" is simply ``{bone_name: absolute_local_angle}``. Behaviours blend the
live skeleton toward these each frame.
"""

from __future__ import annotations

import math
from typing import Dict

from ..core.skeleton import Skeleton

Pose = Dict[str, float]

TAU = math.tau


def rest_angles(skeleton: Skeleton) -> Pose:
    return {name: bone.rest_angle for name, bone in skeleton.bones.items()}


class PoseLibrary:
    """Generates named poses relative to a skeleton's rest pose."""

    def __init__(self, skeleton: Skeleton):
        self.base: Pose = rest_angles(skeleton)

    # ------------------------------------------------------------- helpers
    def _pose(self, deltas: Pose) -> Pose:
        pose = dict(self.base)
        for name, delta in deltas.items():
            if name in pose:
                pose[name] = pose[name] + delta
        return pose

    # -------------------------------------------------------------- actions
    def idle(self, phase: float) -> Pose:
        """Gentle breathing sway."""
        breathe = math.sin(phase * TAU) * 0.04
        sway = math.sin(phase * TAU) * 0.03
        return self._pose(
            {
                "torso": breathe,
                "head": -breathe * 0.5 + math.sin(phase * TAU * 0.5) * 0.05,
                "upper_arm_l": sway,
                "upper_arm_r": -sway,
            }
        )

    def blink_look(self, phase: float) -> Pose:
        """Idle variation: glance around."""
        return self._pose({"head": math.sin(phase * TAU) * 0.35})

    def walk(self, phase: float) -> Pose:
        """A symmetric two-beat walk cycle."""
        swing = math.sin(phase * TAU)
        counter = math.sin(phase * TAU + math.pi)
        knee = max(0.0, math.sin(phase * TAU + math.pi / 2)) * 0.7
        knee2 = max(0.0, math.sin(phase * TAU - math.pi / 2)) * 0.7
        bob = abs(math.sin(phase * TAU)) * 0.05
        return self._pose(
            {
                "torso": bob + 0.06,
                "head": -bob,
                "thigh_l": swing * 0.5,
                "shin_l": knee,
                "thigh_r": counter * 0.5,
                "shin_r": knee2,
                # Arms swing opposite to legs.
                "upper_arm_l": counter * 0.45,
                "upper_arm_r": swing * 0.45,
                "forearm_l": 0.2 + abs(counter) * 0.2,
                "forearm_r": 0.2 + abs(swing) * 0.2,
            }
        )

    def run(self, phase: float) -> Pose:
        """Faster, deeper version of the walk cycle with forward lean."""
        swing = math.sin(phase * TAU)
        counter = math.sin(phase * TAU + math.pi)
        knee = max(0.0, math.sin(phase * TAU + math.pi / 2)) * 1.1
        knee2 = max(0.0, math.sin(phase * TAU - math.pi / 2)) * 1.1
        return self._pose(
            {
                "torso": 0.28,
                "head": -0.15,
                "thigh_l": swing * 0.9,
                "shin_l": knee,
                "thigh_r": counter * 0.9,
                "shin_r": knee2,
                "upper_arm_l": counter * 0.9 - 0.3,
                "upper_arm_r": swing * 0.9 - 0.3,
                "forearm_l": 1.1,
                "forearm_r": 1.1,
            }
        )

    def climb(self, phase: float) -> Pose:
        """Alternating reach-and-pull up a vertical surface.

        Behaviours may override the reaching hand/foot via IK; this provides the
        base cycle so it still looks alive without a grab target.
        """
        reach = math.sin(phase * TAU)
        return self._pose(
            {
                "torso": 0.05,
                "head": 0.1,
                # Right side reaches up while left pulls down, then swap.
                "upper_arm_r": -1.6 - reach * 0.5,
                "forearm_r": -0.3,
                "upper_arm_l": -1.6 + reach * 0.5,
                "forearm_l": -0.3,
                "thigh_r": -0.2 - reach * 0.4,
                "shin_r": 0.9 + reach * 0.3,
                "thigh_l": -0.2 + reach * 0.4,
                "shin_l": 0.9 - reach * 0.3,
            }
        )

    def creep(self, phase: float) -> Pose:
        """Low crawl on hands and knees (horizontal creeping).

        The torso pitches forward toward horizontal (+delta rotates it from the
        up-pointing rest toward +X) and the limbs tuck under in an alternating
        crawl.
        """
        crawl = math.sin(phase * TAU)
        counter = math.sin(phase * TAU + math.pi)
        return self._pose(
            {
                "torso": 1.45,          # torso pitched forward to ~horizontal
                "head": -0.9,           # look ahead
                "upper_arm_l": -1.1 + crawl * 0.5,   # reach forward to the floor
                "forearm_l": 0.6,
                "upper_arm_r": -1.1 + counter * 0.5,
                "forearm_r": 0.6,
                "thigh_l": -1.0 + counter * 0.4,     # knees drawn under body
                "shin_l": 1.4,
                "thigh_r": -1.0 + crawl * 0.4,
                "shin_r": 1.4,
            }
        )

    def sit(self) -> Pose:
        """Sit with legs hanging forward (e.g. on a window edge or taskbar).

        Thighs rotate forward toward horizontal (negative delta) and knees bend
        so the shins hang down.
        """
        return self._pose(
            {
                "torso": 0.0,
                "thigh_l": -1.5,
                "shin_l": 1.2,
                "thigh_r": -1.5,
                "shin_r": 1.2,
                "upper_arm_l": -0.2,
                "upper_arm_r": 0.2,
                "forearm_l": 0.3,
                "forearm_r": 0.3,
            }
        )

    def sit_dangle(self, phase: float) -> Pose:
        """Sitting variation with gently swinging legs."""
        swing = math.sin(phase * TAU) * 0.25
        pose = self.sit()
        pose["shin_l"] = pose.get("shin_l", 0.0) + swing
        pose["shin_r"] = pose.get("shin_r", 0.0) - swing
        return pose

    def sleep(self) -> Pose:
        """Lying down / curled up."""
        return self._pose(
            {
                "torso": 1.5,
                "head": -1.4,
                "thigh_l": 1.1,
                "shin_l": 1.2,
                "thigh_r": 1.0,
                "shin_r": 1.3,
                "upper_arm_l": -0.6,
                "forearm_l": 1.2,
                "upper_arm_r": -0.4,
                "forearm_r": 1.0,
            }
        )

    def fall(self, phase: float) -> Pose:
        """Flailing while airborne."""
        flail = math.sin(phase * TAU * 3)
        return self._pose(
            {
                "torso": -0.2,
                "upper_arm_l": -1.9 + flail * 0.4,
                "upper_arm_r": -1.9 - flail * 0.4,
                "forearm_l": -0.6,
                "forearm_r": -0.6,
                "thigh_l": -0.5 + flail * 0.3,
                "thigh_r": -0.5 - flail * 0.3,
                "shin_l": 0.6,
                "shin_r": 0.6,
            }
        )

    def drag(self, phase: float) -> Pose:
        """Dangling from the scruff while the user drags the pet."""
        wobble = math.sin(phase * TAU * 2) * 0.15
        return self._pose(
            {
                "torso": -0.1 + wobble,
                "head": 0.2,
                "upper_arm_l": -2.4,
                "upper_arm_r": -2.4,
                "forearm_l": -0.3,
                "forearm_r": -0.3,
                "thigh_l": 0.3 + wobble,
                "thigh_r": 0.3 - wobble,
                "shin_l": 0.5,
                "shin_r": 0.5,
            }
        )

    def wave(self, phase: float) -> Pose:
        """Friendly wave with the right arm."""
        wave = math.sin(phase * TAU * 2) * 0.4
        return self._pose(
            {
                "upper_arm_r": -2.6,
                "forearm_r": -0.6 + wave,
                "head": 0.1,
            }
        )

    def cheer(self, phase: float) -> Pose:
        """Both arms up, small hop feel."""
        pump = math.sin(phase * TAU * 2) * 0.2
        return self._pose(
            {
                "upper_arm_l": -2.8 + pump,
                "upper_arm_r": -2.8 - pump,
                "forearm_l": -0.4,
                "forearm_r": -0.4,
                "head": -0.1,
            }
        )
