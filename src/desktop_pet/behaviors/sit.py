"""Sitting on a ledge with legs dangling."""

from __future__ import annotations

from typing import Optional

from .locomotion import GroundedBehavior


class SitBehavior(GroundedBehavior):
    name = "sit"
    label = "Sit down"

    def on_enter(self, duration: float = 8.0, **kwargs) -> None:
        super().on_enter(**kwargs)
        # Sit so the pelvis is close to the surface; shins hang below it.
        self.pet.set_ground_offset(self.pet.stand_offset * 0.5)
        self.duration = duration

    def update(self, dt: float) -> Optional[str]:
        super().update(dt)
        if not self.stick_to_support():
            return "fall"
        self.pet.anim_phase = (self.pet.anim_phase + dt * 0.5) % 1.0
        self.pet.skeleton.blend(self.poses.sit_dangle(self.pet.anim_phase), min(1.0, dt * 8))
        if self.time_in_state >= self.duration:
            return "idle"
        return None

    def on_exit(self) -> None:
        self.pet.set_ground_offset()
