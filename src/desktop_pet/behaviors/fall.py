"""Falling and landing (gravity takes over)."""

from __future__ import annotations

from typing import Optional

from ..core.geometry import Vec2
from .base import Behavior


class FallBehavior(Behavior):
    name = "fall"
    label = "Fall"
    autonomous = False

    def on_enter(self, **kwargs) -> None:
        super().on_enter(**kwargs)
        self.pet.set_ground_offset()
        self.pet.body.on_ground = False
        self.pet.current_surface = None

    def update(self, dt: float) -> Optional[str]:
        super().update(dt)
        pet = self.pet
        prev_feet = pet.feet_y()

        pet.body.gravity_enabled = self.config.gravity_enabled
        pet.body.integrate(dt)

        bounds = self.env.bounds
        # Soft ceiling so a hard upward throw doesn't fly off into the void.
        if pet.body.position.y < bounds.top:
            pet.body.position = Vec2(pet.body.position.x, bounds.top)
            if pet.body.velocity.y < 0:
                pet.body.velocity = Vec2(pet.body.velocity.x, abs(pet.body.velocity.y) * 0.3)
        # Bounce gently off the world's side walls.
        if pet.body.position.x < bounds.left + 4:
            pet.body.position = Vec2(bounds.left + 4, pet.body.position.y)
            pet.body.velocity = Vec2(abs(pet.body.velocity.x) * 0.5, pet.body.velocity.y)
        elif pet.body.position.x > bounds.right - 4:
            pet.body.position = Vec2(bounds.right - 4, pet.body.position.y)
            pet.body.velocity = Vec2(-abs(pet.body.velocity.x) * 0.5, pet.body.velocity.y)

        # Swept landing test: land on the first surface the feet crossed this
        # frame (checking the whole [prev_feet, new_feet] span prevents fast
        # falls from tunnelling straight through thin ledges).
        new_feet = pet.feet_y()
        surface = self._first_surface_crossed(pet.body.position.x, prev_feet, new_feet)
        if surface is not None and pet.body.velocity.y >= 0:
            pet.set_feet_on(surface)
            impact = pet.body.velocity.y
            pet.body.stop()
            if impact > 900:
                pet.say("oof!", 1.2)
                return "land"
            return "idle"

        pet.anim_phase = (pet.anim_phase + dt) % 1.0
        pet.skeleton.blend(self.poses.fall(pet.anim_phase), min(1.0, dt * 6))
        return None

    def _first_surface_crossed(self, x: float, prev_feet: float, new_feet: float):
        """Highest surface whose height lies within the feet's travel this frame."""
        best = None
        low = min(prev_feet, new_feet) - 1.0
        high = max(prev_feet, new_feet)
        for surface in self.env.surfaces:
            if not surface.contains_x(x):
                continue
            if low <= surface.y <= high:
                if best is None or surface.y < best.y:
                    best = surface
        return best


class LandBehavior(Behavior):
    """Brief squash-and-recover after a hard landing."""

    name = "land"
    label = "Land"
    autonomous = False

    def on_enter(self, **kwargs) -> None:
        super().on_enter(**kwargs)
        self.pet.set_ground_offset(self.pet.stand_offset * 0.7)

    def update(self, dt: float) -> Optional[str]:
        super().update(dt)
        self.pet.skeleton.blend(self.poses.idle(0.25), min(1.0, dt * 8))
        # Ease the crouch back to standing.
        target = self.pet.stand_offset
        self.pet.ground_offset += (target - self.pet.ground_offset) * min(1.0, dt * 6)
        if self.time_in_state > 0.45:
            return "idle"
        return None

    def on_exit(self) -> None:
        self.pet.set_ground_offset()
