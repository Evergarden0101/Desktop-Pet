"""Simple point-mass physics for the pet's centre of gravity.

The skeleton animates the *pose*; this module moves the pet *through the world*.
The two are combined by the behaviours in :mod:`desktop_pet.behaviors`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .geometry import Vec2, clamp


@dataclass
class PhysicsBody:
    """A damped point mass used for walking, falling and throwing."""

    position: Vec2 = field(default_factory=Vec2)
    velocity: Vec2 = field(default_factory=Vec2)
    gravity: float = 2200.0          # px / s^2
    air_drag: float = 0.02           # fraction of velocity shed per step
    max_speed: float = 6000.0        # px / s, keeps the throw from exploding
    on_ground: bool = False
    gravity_enabled: bool = True

    def integrate(self, dt: float) -> None:
        """Advance the body by ``dt`` seconds (semi-implicit Euler)."""
        if self.gravity_enabled and not self.on_ground:
            self.velocity = Vec2(self.velocity.x, self.velocity.y + self.gravity * dt)

        # Frame-rate independent drag.
        drag = clamp(1.0 - self.air_drag * (dt * 60.0), 0.0, 1.0)
        self.velocity = self.velocity * drag

        speed = self.velocity.length()
        if speed > self.max_speed:
            self.velocity = self.velocity.normalized() * self.max_speed

        self.position = self.position + self.velocity * dt

    def apply_impulse(self, impulse: Vec2) -> None:
        self.velocity = self.velocity + impulse

    def stop(self) -> None:
        self.velocity = Vec2(0.0, 0.0)

    def land(self, ground_y: float) -> None:
        """Snap to a ground line and zero vertical motion."""
        self.position = Vec2(self.position.x, ground_y)
        self.velocity = Vec2(self.velocity.x, 0.0)
        self.on_ground = True

    def leave_ground(self) -> None:
        self.on_ground = False


class VelocityTracker:
    """Estimates a throw velocity from a short history of drag positions."""

    def __init__(self, window: float = 0.12):
        self.window = window
        self._samples: list[tuple[float, Vec2]] = []

    def add(self, timestamp: float, position: Vec2) -> None:
        self._samples.append((timestamp, position))
        cutoff = timestamp - self.window
        self._samples = [s for s in self._samples if s[0] >= cutoff]

    def velocity(self) -> Vec2:
        if len(self._samples) < 2:
            return Vec2(0.0, 0.0)
        (t0, p0), (t1, p1) = self._samples[0], self._samples[-1]
        dt = t1 - t0
        if dt <= 1e-4:
            return Vec2(0.0, 0.0)
        return (p1 - p0) / dt

    def clear(self) -> None:
        self._samples.clear()
