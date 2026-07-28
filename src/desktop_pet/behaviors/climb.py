"""Climbing window sides and screen edges.

The pet attaches to the nearest vertical :class:`~desktop_pet.core.environment.Wall`
and ascends. Its hands are placed on the wall with two-bone IK so the climb
reads as grabbing rather than sliding. Reaching a window's top edge, it mounts
the title bar and stands there; losing the wall (window moved) drops it into a
fall.
"""

from __future__ import annotations

import math
from typing import Optional

from ..core.environment import Wall
from ..core.geometry import Vec2
from .base import Behavior
from .locomotion import REACH_UP_BODIES


class ClimbBehavior(Behavior):
    name = "climb"
    label = "Climb"

    #: How close (px) the pet must be to a wall to grab it.
    grab_radius = 46.0

    def on_enter(self, wall: Optional[Wall] = None, direction: int = -1, **kwargs) -> None:
        super().on_enter(**kwargs)
        pet = self.pet
        pet.set_ground_offset()
        pet.body.on_ground = False
        pet.body.stop()
        self.direction = direction  # -1 = up (screen y decreases), +1 = down
        target = wall or self.env.nearest_wall(pet.body.position, self.grab_radius)
        # Remember *which* wall by identity, not by object: the Environment is
        # rebuilt every frame, so the instance is gone next tick. Tracking the
        # identity keeps the pet on one edge instead of hopping between a window
        # side and a screen edge mid-climb.
        self._wall_id = self._identity(target) if target else None
        self._stuck = 0.0
        # Which side of the wall the pet climbs on is decided by where it
        # actually is, not by ``Wall.facing``: it meets a screen edge from the
        # inside but an application window's edge from the outside, and both
        # must work.
        self._side = 0
        if target is not None:
            self._side = 1 if pet.body.position.x >= target.x else -1
            self._attach(target)

    @staticmethod
    def _identity(wall: Wall):
        return (wall.window_handle, wall.facing, wall.kind)

    def _attach(self, wall: Wall) -> None:
        pet = self.pet
        side = self._side or (1 if pet.body.position.x >= wall.x else -1)
        # Overlap the edge slightly so the pet reads as gripping it rather
        # than floating alongside.
        pet.body.position = Vec2(
            wall.x + side * pet.half_width() * 0.55, pet.body.position.y
        )
        pet.facing = -side  # face the wall it is holding on to

    def _current_wall(self) -> Optional[Wall]:
        """Re-resolve the wall being climbed (walls are rebuilt every frame).

        Matches the remembered identity first - and only within a tolerance of
        the pet, so a window that gets dragged away drops the pet rather than
        teleporting it across the desktop.
        """
        pet = self.pet
        # The pet may start below a floating window's edge and climb up into
        # it, so tolerate being under the wall's span by one body height - the
        # same reach ``wall_blocking`` used to decide the climb was possible.
        margin = self.grab_radius + pet.body_height() * REACH_UP_BODIES
        if self._wall_id is not None:
            for wall in self.env.walls:
                if self._identity(wall) != self._wall_id:
                    continue
                if abs(wall.x - pet.body.position.x) > self.grab_radius * 2:
                    continue
                if not wall.contains_y(pet.body.position.y, margin):
                    continue
                return wall
        # Lost it (window closed/moved): fall back to whatever is in reach.
        fallback = self.env.nearest_wall(pet.body.position, self.grab_radius)
        if fallback is not None:
            self._wall_id = self._identity(fallback)
        return fallback

    def update(self, dt: float) -> Optional[str]:
        super().update(dt)
        pet = self.pet
        wall = self._current_wall()
        if wall is None:
            return "fall"

        self._attach(wall)
        pet.body.position = Vec2(
            pet.body.position.x,
            pet.body.position.y + self.config.climb_speed * self.direction * dt,
        )
        pet.anim_phase = (pet.anim_phase + dt * 1.2) % 1.0

        # Mounting the top: the pet's body (root) has risen to the wall's top
        # edge, so it can pull itself up and stand on the ledge. Using the root
        # here (rather than the far-below feet) means the wall is still in range
        # when the mount fires.
        if self.direction < 0 and pet.body.position.y <= wall.top + 6:
            surface = self._top_surface(wall)
            if surface is not None:
                pet.set_feet_on(surface)
                pet.say_category("sit", 2.5)
                # Settle in on the ledge it just conquered.
                if pet.state.has("sit") and pet.rng.random() < 0.5:
                    return "sit"
                return "idle"
            return "fall"

        # Reached the bottom of the wall - let go.
        if self.direction > 0 and pet.body.position.y >= wall.y1 - pet.stand_offset:
            return "fall"

        # If a surface appears under the feet on the way down, stand on it
        # instead of sliding past (window stacked on window).
        if self.direction > 0:
            support = self.env.surface_under(pet.body.position.x, pet.feet_y(), 8.0)
            if support is not None:
                pet.set_feet_on(support)
                return "idle"

        pet.skeleton.blend(self.poses.climb(pet.anim_phase), min(1.0, dt * 8))
        self._reach_hands(wall)
        return None

    def _top_surface(self, wall: Wall):
        # Allow a margin of the pet's own width: while climbing it hugs the
        # edge and can sit just outside the window's span, but it should still
        # be able to pull itself up onto the ledge (set_feet_on clamps it on).
        margin = self.pet.half_width() + 10.0
        for surface in self.env.surfaces:
            if abs(surface.y - wall.top) <= 6 and surface.contains_x(
                self.pet.body.position.x, margin=margin
            ):
                return surface
        return None

    def _reach_hands(self, wall: Wall) -> None:
        """Place both hands on the wall via IK for a convincing grip."""
        pet = self.pet
        # Ensure the skeleton is anchored where the pet currently is so the IK
        # targets resolve in world space (pet.update re-solves afterwards).
        pet.skeleton.root_position = pet.body.position
        pet.skeleton.facing = pet.facing
        pet.skeleton.scale = pet.config.scale
        pet.skeleton.solve()

        reach = 0.5 - 0.5 * math.cos(pet.anim_phase * math.tau)
        high = pet.body.position.y - pet.stand_offset * (0.55 + 0.2 * reach)
        low = pet.body.position.y - pet.stand_offset * (0.35 - 0.2 * reach)
        wall_x = wall.x
        try:
            pet.skeleton.solve_two_bone_ik(
                "upper_arm_r", "forearm_r", Vec2(wall_x, high), bend_positive=True
            )
            pet.skeleton.solve_two_bone_ik(
                "upper_arm_l", "forearm_l", Vec2(wall_x, low), bend_positive=False
            )
        except KeyError:
            pass  # custom rigs may lack these bones; the pose alone still works
