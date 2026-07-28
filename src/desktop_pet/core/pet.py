"""The pet entity: the thing that lives on your desktop.

A :class:`Pet` owns its skeleton, a physics body for its centre of mass, a pose
library, live desktop :class:`Environment`, virtual-pet stats and a state
machine of behaviours. The UI layer feeds it a fresh environment + input events
each frame and then renders ``skeleton`` after :meth:`update`.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from ..config import AppConfig
from ..rig.body_parts import BodyPart, default_skeleton
from ..rig.poses import PoseLibrary
from ..rig.skeleton_utils import stand_offset_of
from .environment import Environment, Surface
from .events import EventBus
from .geometry import Vec2, clamp
from .physics import PhysicsBody, VelocityTracker
from .skeleton import Skeleton
from .state_machine import StateMachine


@dataclass
class Stats:
    """Tamagotchi-style needs. All values are 0..100."""

    happiness: float = 80.0
    energy: float = 90.0
    hunger: float = 30.0  # higher = hungrier

    def clamp(self) -> None:
        self.happiness = clamp(self.happiness, 0, 100)
        self.energy = clamp(self.energy, 0, 100)
        self.hunger = clamp(self.hunger, 0, 100)

    def decay(self, per_min: float, dt: float) -> None:
        step = per_min * (dt / 60.0)
        self.hunger += step
        self.energy -= step * 0.6
        self.happiness -= step * 0.4
        self.clamp()

    def feed(self, amount: float = 30.0) -> None:
        self.hunger -= amount
        self.happiness += amount * 0.3
        self.clamp()

    def play(self, amount: float = 20.0) -> None:
        self.happiness += amount
        self.energy -= amount * 0.4
        self.clamp()

    def rest(self, amount: float = 25.0) -> None:
        self.energy += amount
        self.clamp()


@dataclass
class SpeechBubble:
    text: str = ""
    timer: float = 0.0

    @property
    def visible(self) -> bool:
        return self.timer > 0.0 and bool(self.text)


class Pet:
    def __init__(
        self,
        config: AppConfig,
        skeleton: Optional[Skeleton] = None,
        parts: Optional[Dict[str, BodyPart]] = None,
        pet_id: int = 0,
        rng: Optional[random.Random] = None,
    ):
        self.config = config
        self.pet_id = pet_id
        self.rng = rng or random.Random()

        self.skeleton = skeleton or default_skeleton()
        self.skeleton.scale = config.scale
        self.parts: Dict[str, BodyPart] = parts or {}
        self.poses = PoseLibrary(self.skeleton)

        self.body = PhysicsBody(gravity=config.gravity)
        self.body.gravity_enabled = config.gravity_enabled
        self.velocity_tracker = VelocityTracker()

        # Vertical distance from the skeleton root to the feet in the rest pose;
        # used to plant the pet on surfaces.
        self.stand_offset = stand_offset_of(self.skeleton) * config.scale
        # How far above the current support surface the root should sit. Most
        # behaviours use ``stand_offset``; sit/creep/sleep shrink it.
        self.ground_offset = self.stand_offset

        self.facing = 1
        self.anim_phase = 0.0
        self.stats = Stats()
        self.speech = SpeechBubble()

        self.events = EventBus()
        self.env = Environment(_empty_snapshot(), config.interact_with_windows)
        self.current_surface: Optional[Surface] = None

        self.state = StateMachine(self)

    # ------------------------------------------------------------ geometry
    @property
    def position(self) -> Vec2:
        """The skeleton root (pelvis) position in virtual-desktop space."""
        return self.body.position

    @position.setter
    def position(self, value: Vec2) -> None:
        self.body.position = value

    def feet_y(self) -> float:
        return self.body.position.y + self.ground_offset

    def set_feet_on(self, surface: Surface, x: Optional[float] = None) -> None:
        """Plant the pet's feet on ``surface`` (optionally at column ``x``)."""
        x = self.body.position.x if x is None else x
        self.body.position = Vec2(surface.clamp_x(x), surface.y - self.ground_offset)
        self.body.velocity = Vec2(self.body.velocity.x, 0.0)
        self.body.on_ground = True
        self.current_surface = surface

    def face_toward(self, x: float) -> None:
        if x < self.body.position.x - 2:
            self.facing = -1
        elif x > self.body.position.x + 2:
            self.facing = 1

    def half_height(self) -> float:
        return self.stand_offset

    def half_width(self) -> float:
        return 0.28 * self.stand_offset

    # ----------------------------------------------------------- behaviour
    def say(self, text: str, duration: float = 3.0) -> None:
        if self.config.show_speech_bubbles:
            self.speech = SpeechBubble(text=text, timer=duration)

    def set_ground_offset(self, offset: Optional[float] = None) -> None:
        self.ground_offset = self.stand_offset if offset is None else offset

    def rescale(self, scale: float) -> None:
        self.config.scale = scale
        self.skeleton.scale = scale
        self.stand_offset = stand_offset_of(self.skeleton) * scale
        self.ground_offset = self.stand_offset

    # -------------------------------------------------------------- update
    def set_environment(self, env: Environment) -> None:
        self.env = env

    def update(self, dt: float) -> None:
        # Stats slowly change over time.
        if self.config.stats_enabled:
            self.stats.decay(self.config.stat_decay_per_min, dt)

        # Speech bubble countdown.
        if self.speech.timer > 0:
            self.speech.timer -= dt

        # Behaviour drives physics + pose.
        self.state.update(dt)

        # Render transform: place skeleton at the pet's root and solve FK.
        self.skeleton.root_position = self.body.position
        self.skeleton.facing = self.facing
        self.skeleton.scale = self.config.scale
        self.skeleton.solve()

    def handle_event(self, event: str, **data) -> None:
        self.state.handle_event(event, **data)


def _empty_snapshot():
    from ..platform.base import DesktopSnapshot

    return DesktopSnapshot()
