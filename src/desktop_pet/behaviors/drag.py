"""User dragging and throwing.

While the mouse holds the pet, ``drag`` follows the cursor and records a short
velocity history. On release the pet is launched with that velocity (if
throwing is enabled) and control passes to ``fall``.
"""

from __future__ import annotations

import time
from typing import Optional

from ..core.geometry import Vec2
from .base import Behavior


class DragBehavior(Behavior):
    name = "drag"
    label = "Drag"
    autonomous = False

    def on_enter(self, grab_offset: Optional[Vec2] = None, **kwargs) -> None:
        super().on_enter(**kwargs)
        pet = self.pet
        pet.set_ground_offset()
        pet.body.on_ground = False
        pet.body.stop()
        pet.velocity_tracker.clear()
        # Offset between cursor and root so the pet doesn't snap to the cursor.
        self.grab_offset = grab_offset or Vec2(0.0, -pet.stand_offset * 0.5)
        self.cursor = pet.body.position - self.grab_offset

    def on_event(self, event: str, **data) -> Optional[str]:
        if event == "drag_move":
            self.cursor = data.get("position", self.cursor)
            return None
        if event == "release":
            return self._release()
        return None

    def _release(self) -> str:
        pet = self.pet
        if self.config.throwable:
            pet.body.velocity = pet.velocity_tracker.velocity()
        else:
            pet.body.stop()
        return "fall"

    def update(self, dt: float) -> Optional[str]:
        super().update(dt)
        pet = self.pet
        target = self.cursor + self.grab_offset
        # Smoothly chase the cursor for a bit of dangle/lag.
        pet.body.position = pet.body.position + (target - pet.body.position) * min(1.0, dt * 22)
        pet.velocity_tracker.add(time.monotonic(), pet.body.position)
        pet.face_toward(self.cursor.x)

        pet.anim_phase = (pet.anim_phase + dt) % 1.0
        pet.skeleton.blend(self.poses.drag(pet.anim_phase), min(1.0, dt * 10))
        return None
