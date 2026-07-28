"""2D geometry helpers used across the engine.

This module is intentionally dependency-free (pure Python + ``math``) so it can
be unit-tested on any platform, including CI runners that have no GUI stack
installed.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Tuple


def clamp(value: float, low: float, high: float) -> float:
    """Clamp ``value`` into the inclusive range ``[low, high]``."""
    if low > high:
        low, high = high, low
    return max(low, min(high, value))


def lerp(a: float, b: float, t: float) -> float:
    """Linear interpolation between ``a`` and ``b`` by factor ``t``."""
    return a + (b - a) * t


def lerp_angle(a: float, b: float, t: float) -> float:
    """Interpolate between two angles (radians) along the shortest arc."""
    diff = (b - a + math.pi) % (2 * math.pi) - math.pi
    return a + diff * t


def approach(current: float, target: float, max_delta: float) -> float:
    """Move ``current`` toward ``target`` by at most ``max_delta``."""
    if current < target:
        return min(current + max_delta, target)
    return max(current - max_delta, target)


def smoothstep(t: float) -> float:
    """Classic smoothstep easing on ``t`` in ``[0, 1]``."""
    t = clamp(t, 0.0, 1.0)
    return t * t * (3 - 2 * t)


@dataclass(frozen=True)
class Vec2:
    """An immutable 2D vector."""

    x: float = 0.0
    y: float = 0.0

    def __add__(self, other: "Vec2") -> "Vec2":
        return Vec2(self.x + other.x, self.y + other.y)

    def __sub__(self, other: "Vec2") -> "Vec2":
        return Vec2(self.x - other.x, self.y - other.y)

    def __mul__(self, scalar: float) -> "Vec2":
        return Vec2(self.x * scalar, self.y * scalar)

    __rmul__ = __mul__

    def __truediv__(self, scalar: float) -> "Vec2":
        return Vec2(self.x / scalar, self.y / scalar)

    def __iter__(self):
        yield self.x
        yield self.y

    def dot(self, other: "Vec2") -> float:
        return self.x * other.x + self.y * other.y

    def length(self) -> float:
        return math.hypot(self.x, self.y)

    def length_sq(self) -> float:
        return self.x * self.x + self.y * self.y

    def normalized(self) -> "Vec2":
        length = self.length()
        if length < 1e-9:
            return Vec2(0.0, 0.0)
        return Vec2(self.x / length, self.y / length)

    def rotated(self, radians: float) -> "Vec2":
        cos_a = math.cos(radians)
        sin_a = math.sin(radians)
        return Vec2(self.x * cos_a - self.y * sin_a, self.x * sin_a + self.y * cos_a)

    def angle(self) -> float:
        """Angle of the vector in radians, measured from +X axis."""
        return math.atan2(self.y, self.x)

    def rounded(self) -> Tuple[int, int]:
        return int(round(self.x)), int(round(self.y))

    def distance_to(self, other: "Vec2") -> float:
        return (self - other).length()

    @staticmethod
    def from_angle(radians: float, length: float = 1.0) -> "Vec2":
        return Vec2(math.cos(radians) * length, math.sin(radians) * length)


@dataclass(frozen=True)
class Rect:
    """An axis-aligned rectangle described by its top-left corner and size."""

    x: float
    y: float
    width: float
    height: float

    @property
    def left(self) -> float:
        return self.x

    @property
    def top(self) -> float:
        return self.y

    @property
    def right(self) -> float:
        return self.x + self.width

    @property
    def bottom(self) -> float:
        return self.y + self.height

    @property
    def center(self) -> Vec2:
        return Vec2(self.x + self.width / 2, self.y + self.height / 2)

    def contains(self, point: Vec2) -> bool:
        return self.left <= point.x <= self.right and self.top <= point.y <= self.bottom

    def intersects(self, other: "Rect") -> bool:
        return not (
            self.right < other.left
            or self.left > other.right
            or self.bottom < other.top
            or self.top > other.bottom
        )

    def inflated(self, dx: float, dy: float) -> "Rect":
        return Rect(self.x - dx, self.y - dy, self.width + 2 * dx, self.height + 2 * dy)

    @staticmethod
    def from_bounds(left: float, top: float, right: float, bottom: float) -> "Rect":
        return Rect(left, top, right - left, bottom - top)

    @staticmethod
    def bounding(points: Iterable[Vec2]) -> "Rect":
        points = list(points)
        if not points:
            return Rect(0, 0, 0, 0)
        xs = [p.x for p in points]
        ys = [p.y for p in points]
        return Rect.from_bounds(min(xs), min(ys), max(xs), max(ys))
