"""Creeping / crawling low along a surface."""

from __future__ import annotations

from typing import Optional

from .locomotion import GroundedBehavior


class CreepBehavior(GroundedBehavior):
    name = "creep"
    label = "Creep"

    def on_enter(self, target_x: Optional[float] = None, duration: float = 5.0, **kwargs) -> None:
        super().on_enter(**kwargs)
        # Crawl low to the ground.
        self.pet.set_ground_offset(self.pet.stand_offset * 0.45)
        self.target_x = target_x
        self.duration = duration
        if target_x is not None:
            self.direction = 1 if target_x > self.pet.body.position.x else -1
        else:
            self.direction = self.pet.rng.choice([-1, 1])
        self.pet.say("...", 1.5)

    def update(self, dt: float) -> Optional[str]:
        super().update(dt)
        pet = self.pet
        if self.target_x is not None and abs(pet.body.position.x - self.target_x) <= 2.0:
            return "idle"

        result = self.walk_step(dt, self.config.creep_speed, self.direction)
        if result:
            return result

        bounds = self.env.bounds
        if pet.body.position.x <= bounds.left + 6 and self.direction < 0:
            self.direction = 1
        elif pet.body.position.x >= bounds.right - 6 and self.direction > 0:
            self.direction = -1
        self.clamp_to_world()

        pet.skeleton.blend(self.poses.creep(pet.anim_phase), min(1.0, dt * 8))
        if self.target_x is None and self.time_in_state >= self.duration:
            return "idle"
        return None

    def on_exit(self) -> None:
        self.pet.set_ground_offset()
