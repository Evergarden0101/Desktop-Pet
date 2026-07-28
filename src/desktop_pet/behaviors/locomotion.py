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


#: How far above its own head (in body heights) the pet can grab a ledge.
#: Shared with ClimbBehavior so "can I reach it?" and "am I still on it?"
#: agree - otherwise the pet grabs a window it immediately falls off.
REACH_UP_BODIES = 1.0


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

    def wall_blocking(self, direction: int, lookahead: float = 12.0) -> Optional[Wall]:
        """The climbable wall directly ahead of the pet, if any.

        Two things this must *not* do, both of which used to stop the pet ever
        climbing an application window:

        * **Don't filter on ``Wall.facing``.** ``facing`` says which side of the
          wall is climbable, and the pet meets screen edges and window edges
          from opposite sides: walking right, it reaches the screen's right edge
          (facing -1) from the inside, but a window's *left* edge (facing +1)
          from the outside. Filtering on facing therefore matched screen edges
          only. Which side the pet is on is decided at attach time instead.

        * **Don't require the wall to reach the pet's feet.** Windows float
          above the taskbar, so a window edge almost never spans the floor the
          pet walks on. A wall counts when it overlaps the pet's body at all -
          it reaches up and grabs the ledge. A window entirely above its head
          is still ignored, so the pet walks underneath.
        """
        pet = self.pet
        front_x = pet.body.position.x + direction * pet.half_width()
        feet = pet.feet_y()
        head = feet - pet.body_height()
        # Windows float above the taskbar, so their edges usually stop short of
        # the floor. Allow one body-height of upward reach - the pet hops up and
        # grabs a ledge just overhead - or floating windows would be unclimbable
        # from the ground. Anything higher is still walked under.
        reach_up = pet.body_height() * REACH_UP_BODIES
        best: Optional[Wall] = None
        best_dist = lookahead
        for wall in self.env.walls:
            distance = (wall.x - front_x) * direction
            if distance < -pet.half_width() or distance > best_dist:
                continue
            if wall.y0 > feet or wall.y1 < head - reach_up:
                continue  # entirely below the feet, or out of reach overhead
            best = wall
            best_dist = max(distance, 0.0)
        return best

    def climb_allowed(self) -> bool:
        """Whether bumping into a wall may turn into a climb.

        Checks the behaviour mode as well as the enabled list: "calm" zeroes
        the climb weight, and a mode that says the pet doesn't climb must also
        stop it climbing walls it happens to walk into - otherwise the setting
        only governs *spontaneous* climbs and the pet still scales windows.
        """
        if "climb" not in self.config.enabled_behaviors:
            return False
        if not self.pet.state.has("climb"):
            return False
        from .autonomy import MODE_WEIGHTS

        return MODE_WEIGHTS.get(self.config.mode, {}).get("climb", 1.0) > 0
