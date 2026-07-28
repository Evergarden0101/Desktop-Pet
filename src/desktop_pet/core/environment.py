"""Turns a raw desktop snapshot into things the pet can physically interact with.

Windows, monitors and the taskbar become:

* **surfaces** - horizontal ledges the pet can stand, walk and sit on (window
  title-bar tops, the taskbar, the screen floor);
* **walls** - vertical edges the pet can climb (window sides, screen sides).

Behaviours query this model ("what's under my feet?", "is there a wall to grab?")
without knowing anything about Win32.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import List, Optional

from ..platform.base import DesktopSnapshot
from .geometry import Rect, Vec2, clamp


class SurfaceKind(Enum):
    FLOOR = "floor"
    WINDOW = "window"
    TASKBAR = "taskbar"


class WallKind(Enum):
    SCREEN = "screen"
    WINDOW = "window"


@dataclass
class Surface:
    """A horizontal ledge at height ``y`` spanning ``[x0, x1]``."""

    y: float
    x0: float
    x1: float
    kind: SurfaceKind
    window_handle: Optional[int] = None
    label: str = ""

    def contains_x(self, x: float, margin: float = 0.0) -> bool:
        return self.x0 - margin <= x <= self.x1 + margin

    def clamp_x(self, x: float) -> float:
        return clamp(x, self.x0, self.x1)

    @property
    def width(self) -> float:
        return self.x1 - self.x0


@dataclass
class Wall:
    """A vertical edge at column ``x`` spanning ``[y0, y1]``.

    ``facing`` is +1 if the climbable face points right (the pet climbs on the
    left of the wall) or -1 if it points left.
    """

    x: float
    y0: float
    y1: float
    facing: int
    kind: WallKind
    window_handle: Optional[int] = None

    def contains_y(self, y: float, margin: float = 0.0) -> bool:
        return self.y0 - margin <= y <= self.y1 + margin

    @property
    def top(self) -> float:
        return self.y0


@dataclass
class SurfaceHit:
    surface: Surface
    y: float


class Environment:
    """A queryable model of the desktop for one or more frames."""

    def __init__(self, snapshot: DesktopSnapshot, interactive_windows: bool = True):
        self.snapshot = snapshot
        self.interactive_windows = interactive_windows
        self.bounds: Rect = snapshot.virtual_bounds()
        self.surfaces: List[Surface] = []
        self.walls: List[Wall] = []
        self._build()

    # --------------------------------------------------------------- build
    def _build(self) -> None:
        snap = self.snapshot

        # Floor(s): the top of the taskbar / work-area bottom for each monitor.
        for monitor in snap.monitors:
            work = monitor.work_area
            self.surfaces.append(
                Surface(
                    y=work.bottom,
                    x0=monitor.bounds.left,
                    x1=monitor.bounds.right,
                    kind=SurfaceKind.FLOOR,
                    label=f"floor@{monitor.index}",
                )
            )
            # Screen side walls so the pet can climb the very edges of a display.
            self.walls.append(
                Wall(monitor.bounds.left, monitor.bounds.top, work.bottom, +1, WallKind.SCREEN)
            )
            self.walls.append(
                Wall(monitor.bounds.right, monitor.bounds.top, work.bottom, -1, WallKind.SCREEN)
            )

        # Taskbars: their top edge is a nice ledge to sit on.
        for bar in snap.taskbars:
            self.surfaces.append(
                Surface(
                    y=bar.top,
                    x0=bar.left,
                    x1=bar.right,
                    kind=SurfaceKind.TASKBAR,
                    label="taskbar",
                )
            )

        # Windows: title-bar top is a surface; both sides are climbable walls.
        if self.interactive_windows:
            for win in snap.windows:
                if win.is_minimized:
                    continue
                r = win.rect
                if r.width < 40 or r.height < 30:
                    continue
                self.surfaces.append(
                    Surface(
                        y=r.top,
                        x0=r.left,
                        x1=r.right,
                        kind=SurfaceKind.WINDOW,
                        window_handle=win.handle,
                        label=win.title,
                    )
                )
                self.walls.append(
                    Wall(r.left, r.top, r.bottom, +1, WallKind.WINDOW, win.handle)
                )
                self.walls.append(
                    Wall(r.right, r.top, r.bottom, -1, WallKind.WINDOW, win.handle)
                )

    # --------------------------------------------------------------- query
    def ground_below(self, x: float, y: float, margin: float = 0.0) -> Optional[SurfaceHit]:
        """Highest surface at column ``x`` located at or below ``y``.

        This is what a falling pet lands on. Returns ``None`` if nothing is
        underneath (it will keep falling to the world floor).
        """
        best: Optional[SurfaceHit] = None
        for surface in self.surfaces:
            if not surface.contains_x(x, margin):
                continue
            if surface.y < y - 0.5:
                continue  # above the point; can't land upward
            if best is None or surface.y < best.y:
                best = SurfaceHit(surface, surface.y)
        return best

    def surface_under(
        self, x: float, foot_y: float, tolerance: float = 6.0
    ) -> Optional[Surface]:
        """The surface the pet is currently resting on, within ``tolerance``."""
        for surface in self.surfaces:
            if surface.contains_x(x) and abs(surface.y - foot_y) <= tolerance:
                return surface
        return None

    def walls_near(self, pos: Vec2, radius: float) -> List[Wall]:
        near: List[Wall] = []
        for wall in self.walls:
            if abs(wall.x - pos.x) <= radius and wall.contains_y(pos.y, radius):
                near.append(wall)
        return near

    def nearest_wall(self, pos: Vec2, radius: float) -> Optional[Wall]:
        candidates = self.walls_near(pos, radius)
        if not candidates:
            return None
        return min(candidates, key=lambda w: abs(w.x - pos.x))

    def world_floor(self) -> float:
        """The lowest floor surface - the ultimate resting height."""
        floors = [s.y for s in self.surfaces if s.kind != SurfaceKind.WINDOW]
        return max(floors) if floors else self.bounds.bottom

    def clamp_position(self, pos: Vec2, margin: float = 0.0) -> Vec2:
        return Vec2(
            clamp(pos.x, self.bounds.left + margin, self.bounds.right - margin),
            clamp(pos.y, self.bounds.top + margin, self.bounds.bottom - margin),
        )

    def is_off_edge(self, surface: Surface, x: float, margin: float = 2.0) -> bool:
        return x < surface.x0 - margin or x > surface.x1 + margin
