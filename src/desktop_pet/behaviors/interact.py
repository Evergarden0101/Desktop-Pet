"""Interaction behaviours: chasing the cursor, waving, cheering, petting."""

from __future__ import annotations

from typing import Optional

from ..core.geometry import Vec2
from .locomotion import GroundedBehavior


class ChaseCursorBehavior(GroundedBehavior):
    name = "chase_cursor"
    label = "Chase cursor"

    #: Stop chasing once within this horizontal distance of the cursor.
    reach = 26.0

    def on_enter(self, duration: float = 6.0, **kwargs) -> None:
        super().on_enter(**kwargs)
        self.pet.set_ground_offset()
        self.duration = duration

    def update(self, dt: float) -> Optional[str]:
        super().update(dt)
        pet = self.pet
        cursor = self.env.snapshot.cursor
        dx = cursor.x - pet.body.position.x
        if abs(dx) <= self.reach:
            # Caught up - look up at the cursor and idle-breathe.
            pet.skeleton.blend(self.poses.idle(pet.anim_phase), min(1.0, dt * 8))
            pet.anim_phase = (pet.anim_phase + dt * 0.5) % 1.0
            if self.time_in_state >= self.duration:
                return "idle"
            return None

        direction = 1 if dx > 0 else -1
        speed = self.config.run_speed if abs(dx) > 260 else self.config.walk_speed
        result = self.walk_step(dt, speed, direction)
        if result:
            return result
        self.clamp_to_world()

        running = speed >= self.config.run_speed
        pose = self.poses.run(pet.anim_phase) if running else self.poses.walk(pet.anim_phase)
        pet.skeleton.blend(pose, min(1.0, dt * 10))

        if self.time_in_state >= self.duration:
            return "idle"
        return None


class _OneShotPose(GroundedBehavior):
    """A short grounded gesture that returns to idle when finished."""

    pose_name = "wave"
    duration = 2.4

    def on_enter(self, **kwargs) -> None:
        super().on_enter(**kwargs)
        self.pet.set_ground_offset()

    def _pose(self, phase: float):
        return getattr(self.poses, self.pose_name)(phase)

    def update(self, dt: float) -> Optional[str]:
        super().update(dt)
        if not self.stick_to_support():
            return "fall"
        self.pet.anim_phase = (self.pet.anim_phase + dt) % 1.0
        self.pet.skeleton.blend(self._pose(self.pet.anim_phase), min(1.0, dt * 10))
        if self.time_in_state >= self.duration:
            return "idle"
        return None


class WaveBehavior(_OneShotPose):
    name = "wave"
    label = "Wave"
    pose_name = "wave"

    def on_enter(self, **kwargs) -> None:
        super().on_enter(**kwargs)
        self.pet.say("hi!", 2.0)
        self.pet.stats.play(6.0)


class CheerBehavior(_OneShotPose):
    name = "cheer"
    label = "Cheer"
    pose_name = "cheer"

    def on_enter(self, **kwargs) -> None:
        super().on_enter(**kwargs)
        self.pet.say("yay!", 2.0)
        self.pet.stats.play(10.0)
