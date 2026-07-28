"""Idle and sleep behaviours."""

from __future__ import annotations

from typing import Optional

from .locomotion import GroundedBehavior


class IdleBehavior(GroundedBehavior):
    name = "idle"
    label = "Idle"

    def on_enter(self, **kwargs) -> None:
        super().on_enter(**kwargs)
        self.pet.set_ground_offset()  # normal standing height
        self.pet.body.velocity = self.pet.body.velocity * 0.0

    def update(self, dt: float) -> Optional[str]:
        super().update(dt)
        if not self.stick_to_support():
            return "fall"
        self.pet.anim_phase = (self.pet.anim_phase + dt * 0.4) % 1.0
        self.pet.skeleton.blend(self.poses.idle(self.pet.anim_phase), min(1.0, dt * 8))
        return None


class SleepBehavior(GroundedBehavior):
    name = "sleep"
    label = "Sleep"

    def on_enter(self, **kwargs) -> None:
        super().on_enter(**kwargs)
        # Lie lower to the ground.
        self.pet.set_ground_offset(self.pet.stand_offset * 0.35)
        self.duration = kwargs.get("duration", 12.0)
        self.pet.say("zzz...", self.duration)

    def update(self, dt: float) -> Optional[str]:
        super().update(dt)
        if not self.stick_to_support():
            return "fall"
        self.pet.anim_phase = (self.pet.anim_phase + dt * 0.15) % 1.0
        self.pet.skeleton.blend(self.poses.sleep(), min(1.0, dt * 4))
        self.pet.stats.rest(dt * 2.0)
        if self.time_in_state >= self.duration:
            return "idle"
        return None

    def on_exit(self) -> None:
        self.pet.set_ground_offset()
