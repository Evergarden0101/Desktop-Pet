"""Helpers that derive measurements from a skeleton's rest pose."""

from __future__ import annotations

from ..core.geometry import Vec2
from ..core.skeleton import Skeleton


def stand_offset_of(skeleton: Skeleton) -> float:
    """Vertical distance (rig units) from the root to the lowest foot in rest.

    Solved with scale 1 and facing +1 at the origin, so the caller multiplies by
    the live scale. Used to plant the pet's feet exactly on a surface.
    """
    saved_scale = skeleton.scale
    saved_facing = skeleton.facing
    saved_root = skeleton.root_position
    saved_angles = skeleton.snapshot()

    skeleton.scale = 1.0
    skeleton.facing = 1
    skeleton.root_position = Vec2(0.0, 0.0)
    skeleton.reset_to_rest()
    skeleton.solve()

    lowest = 0.0
    for name in skeleton.bones:
        tip = skeleton.tip_scaled_of(name)
        lowest = max(lowest, tip.y, skeleton.bones[name].world_pos.y)

    # Restore whatever the caller had.
    skeleton.scale = saved_scale
    skeleton.facing = saved_facing
    skeleton.root_position = saved_root
    skeleton.apply(saved_angles)
    skeleton.solve()
    return lowest


def rest_span(skeleton: Skeleton) -> tuple[float, float]:
    """Return (width, height) of the rest-pose bounding box in rig units."""
    saved_angles = skeleton.snapshot()
    saved_scale = skeleton.scale
    skeleton.scale = 1.0
    skeleton.root_position = Vec2(0.0, 0.0)
    skeleton.facing = 1
    skeleton.reset_to_rest()
    skeleton.solve()

    xs: list[float] = []
    ys: list[float] = []
    for name in skeleton.bones:
        base = skeleton.bones[name].world_pos
        tip = skeleton.tip_scaled_of(name)
        xs.extend([base.x, tip.x])
        ys.extend([base.y, tip.y])

    skeleton.scale = saved_scale
    skeleton.apply(saved_angles)
    skeleton.solve()
    if not xs:
        return (0.0, 0.0)
    return (max(xs) - min(xs), max(ys) - min(ys))
