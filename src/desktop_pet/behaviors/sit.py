"""Sitting - on the floor, or perched on a ledge with the legs hanging over."""

from __future__ import annotations

from typing import Optional

from ..core.environment import SurfaceKind
from .locomotion import GroundedBehavior


class SitBehavior(GroundedBehavior):
    name = "sit"
    label = "Sit down"

    def on_enter(self, duration: float = 8.0, **kwargs) -> None:
        super().on_enter(**kwargs)
        self.duration = duration
        self._apply_posture()

    def _apply_posture(self) -> None:
        """Choose between sitting on the floor and perching on an edge.

        On a window title bar or the taskbar the pet plants its *pelvis* on the
        surface (``ground_offset`` ~ 0) so the legs hang below the edge and
        overlap the window underneath. On the floor there is nothing to dangle
        into, so it sits normally with its feet planted.

        Changing ``ground_offset`` moves where the pet's "footing" is measured
        from, so it must be re-planted immediately: otherwise the body is left
        hovering a half-height above the surface, ``stick_to_support`` finds
        nothing under it and the pet falls instead of sitting down.
        """
        pet = self.pet
        support = self.resolve_support()
        self.on_ledge = (
            support is not None
            and support.kind in (SurfaceKind.WINDOW, SurfaceKind.TASKBAR)
        )
        if self.on_ledge:
            # Pelvis rests on the edge; shins drop below it.
            pet.set_ground_offset(pet.stand_offset * 0.04)
        else:
            pet.set_ground_offset(pet.stand_offset * 0.5)
        if support is not None:
            pet.set_feet_on(support)

    def update(self, dt: float) -> Optional[str]:
        super().update(dt)
        pet = self.pet
        if not self.stick_to_support():
            return "fall"

        # A window can move out from under the pet, turning a ledge perch into
        # a floor sit (or vice versa); re-check while the posture is cheap.
        if self.time_in_state % 0.5 < dt:
            was_ledge = self.on_ledge
            self._apply_posture()
            if was_ledge != self.on_ledge:
                self.stick_to_support()

        pet.anim_phase = (pet.anim_phase + dt * 0.5) % 1.0
        pose = (
            self.poses.sit_ledge(pet.anim_phase)
            if self.on_ledge
            else self.poses.sit_dangle(pet.anim_phase)
        )
        pet.skeleton.blend(pose, min(1.0, dt * 8))

        if self.time_in_state >= self.duration:
            return "idle"
        return None

    def on_exit(self) -> None:
        self.pet.set_ground_offset()
