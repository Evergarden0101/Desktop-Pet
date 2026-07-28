"""Behaviour registry.

:func:`register_default_behaviors` wires the built-in behaviours into a pet's
state machine. Third-party packs can add their own before or after calling it.
"""

from __future__ import annotations

from typing import List, Type

from ..core.pet import Pet
from .base import Behavior
from .climb import ClimbBehavior
from .creep import CreepBehavior
from .drag import DragBehavior
from .fall import FallBehavior, LandBehavior
from .idle import IdleBehavior, SleepBehavior
from .interact import CheerBehavior, ChaseCursorBehavior, WaveBehavior
from .sit import SitBehavior
from .walk import RunBehavior, WalkBehavior

DEFAULT_BEHAVIORS: List[Type[Behavior]] = [
    IdleBehavior,
    WalkBehavior,
    RunBehavior,
    CreepBehavior,
    ClimbBehavior,
    SitBehavior,
    SleepBehavior,
    FallBehavior,
    LandBehavior,
    DragBehavior,
    ChaseCursorBehavior,
    WaveBehavior,
    CheerBehavior,
]


def register_default_behaviors(pet: Pet) -> None:
    for behavior_cls in DEFAULT_BEHAVIORS:
        pet.state.register(behavior_cls(pet))
    # Start settled on the ground.
    if pet.state.current is None:
        pet.state.change("idle")


__all__ = [
    "Behavior",
    "DEFAULT_BEHAVIORS",
    "register_default_behaviors",
]
