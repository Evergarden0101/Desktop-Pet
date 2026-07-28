"""Walking and running behaviours."""

from __future__ import annotations

from typing import Optional

from ..core.phrases import pick
from .locomotion import GroundedBehavior


class WalkBehavior(GroundedBehavior):
    name = "walk"
    label = "Walk around"

    running = False

    def on_enter(self, target_x: Optional[float] = None, duration: float = 4.0, **kwargs) -> None:
        super().on_enter(**kwargs)
        self.pet.set_ground_offset()
        self.target_x = target_x
        self.duration = duration
        if target_x is not None:
            self.direction = 1 if target_x > self.pet.body.position.x else -1
        else:
            self.direction = self.pet.rng.choice([-1, 1])

    def _speed(self) -> float:
        return self.config.run_speed if self.running else self.config.walk_speed

    def update(self, dt: float) -> Optional[str]:
        super().update(dt)
        pet = self.pet

        if self.target_x is not None:
            if abs(pet.body.position.x - self.target_x) <= self._speed() * dt + 1.5:
                return "idle"
            self.direction = 1 if self.target_x > pet.body.position.x else -1

        result = self.walk_step(dt, self._speed(), self.direction)
        if result:
            return result

        # Something solid ahead? A window side or screen edge at foot level is
        # an invitation to climb; otherwise it's a wall to turn around at.
        wall = self.wall_blocking(self.direction)
        if wall is not None:
            if self.climb_allowed() and pet.rng.random() < self.config.climb_chance:
                pet.say(pick(pet.rng, "climb"), 2.0)
                return "climb"
            if self.target_x is not None:
                return "idle"  # destination is blocked; give up gracefully
            pet.say(pick(pet.rng, "blocked"), 1.5)
            self.direction = -self.direction

        # Bounce off the world edges instead of walking into the void.
        bounds = self.env.bounds
        if pet.body.position.x <= bounds.left + 6 and self.direction < 0:
            self.direction = 1
        elif pet.body.position.x >= bounds.right - 6 and self.direction > 0:
            self.direction = -1
        self.clamp_to_world()

        pose = self.poses.run(pet.anim_phase) if self.running else self.poses.walk(pet.anim_phase)
        pet.skeleton.blend(pose, min(1.0, dt * 10))

        if self.target_x is None and self.time_in_state >= self.duration:
            return "idle"
        return None


class RunBehavior(WalkBehavior):
    name = "run"
    label = "Run around"
    running = True
