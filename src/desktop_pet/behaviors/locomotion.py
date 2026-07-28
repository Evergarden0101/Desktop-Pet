"""Shared helpers for behaviours that keep the pet on a surface.

Because the :class:`~desktop_pet.core.environment.Environment` is rebuilt every
frame (windows move!), a behaviour cannot hold onto a ``Surface`` reference. It
must *re-resolve* the surface under the pet each frame - which conveniently
makes the pet ride windows that get dragged around and fall when the ledge slips
out from under it.
"""

from __future__ import annotations

from typing import Optional

from ..core.environment import Surface, Wall
from ..core.geometry import Vec2
from .base import Behavior


class GroundedBehavior(Behavior):
    """Base class for behaviours where the pet stands on a surface."""

    #: Vertical tolerance (px) for staying attached while a window jitters.
    support_tolerance = 10.0

    def resolve_support(self) -> Optional[Surface]:
        """Find the surface currently under the pet's feet, if any."""
        pet = self.pet
        return self.env.surface_under(
            pet.body.position.x, pet.feet_y(), self.support_tolerance
        )

    def stick_to_support(self) -> bool:
        """Keep feet planted on the surface under the pet.

        Returns ``False`` when support was lost (caller should fall).
        """
        support = self.resolve_support()
        if support is None:
            # Allow a small step-down onto a slightly lower ledge before falling.
            hit = self.env.ground_below(
                self.pet.body.position.x, self.pet.feet_y() - 2, margin=0.0
            )
            if hit and (hit.y - self.pet.feet_y()) <= self.support_tolerance + 6:
                self.pet.set_feet_on(hit.surface)
                return True
            self.pet.body.on_ground = False
            return False
        self.pet.set_feet_on(support)
        return True

    def walk_step(self, dt: float, speed: float, direction: int) -> Optional[str]:
        """Move horizontally at ``speed`` in ``direction`` (+1/-1).

        Returns a transition name if the pet fell off, else ``None``.
        """
        pet = self.pet
        pet.facing = direction if direction != 0 else pet.facing
        new_x = pet.body.position.x + speed * direction * dt
        pet.body.position = Vec2(new_x, pet.body.position.y)

        if not self.stick_to_support():
            return "fall"

        # Advance the animation phase proportional to distance travelled.
        pet.anim_phase = (pet.anim_phase + abs(speed) * dt / 90.0) % 1.0
        return None

    def clamp_to_world(self) -> None:
        pet = self.pet
        bounds = self.env.bounds
        x = min(max(pet.body.position.x, bounds.left + 4), bounds.right - 4)
        pet.body.position = Vec2(x, pet.body.position.y)

    def wall_blocking(self, direction: int, lookahead: float = 10.0) -> Optional[Wall]:
        """The wall directly ahead at foot level, if any.

        Walls whose bottom hangs above the pet (a floating window) don't block
        - the pet walks past underneath. A wall counts only when it actually
        spans the pet's feet, i.e. a window side reaching (near) this surface,
        or a screen edge. This is what makes windows feel solid from the
        ground and gives the pet something to climb.
        """
        pet = self.pet
        front_x = pet.body.position.x + direction * pet.half_width()
        probe_y = pet.feet_y() - 6.0
        best: Optional[Wall] = None
        best_dist = lookahead
        for wall in self.env.walls:
            if wall.facing != -direction:
                continue  # climbable face must point back toward the pet
            distance = (wall.x - front_x) * direction
            if distance < -pet.half_width() or distance > best_dist:
                continue
            if not (wall.y0 <= probe_y <= wall.y1):
                continue  # hangs above (or starts below) the pet's feet
            best = wall
            best_dist = max(distance, 0.0)
        return best

    def climb_allowed(self) -> bool:
        return "climb" in self.config.enabled_behaviors and self.pet.state.has("climb")
