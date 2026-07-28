"""A tiny, explicit finite-state machine for pet behaviour.

Each state is a :class:`desktop_pet.behaviors.base.Behavior`. The machine owns
the *current* behaviour, forwards ticks to it, and performs the enter/exit
bookkeeping when a behaviour requests a transition.
"""

from __future__ import annotations

from typing import Dict, Optional, TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ..behaviors.base import Behavior
    from .pet import Pet


class StateMachine:
    def __init__(self, pet: "Pet"):
        self.pet = pet
        self._states: Dict[str, "Behavior"] = {}
        self.current: Optional["Behavior"] = None
        self.previous_name: Optional[str] = None

    def register(self, behavior: "Behavior") -> None:
        self._states[behavior.name] = behavior

    def has(self, name: str) -> bool:
        return name in self._states

    @property
    def current_name(self) -> Optional[str]:
        return self.current.name if self.current else None

    def change(self, name: str, **kwargs) -> None:
        """Transition to the behaviour registered under ``name``."""
        if name not in self._states:
            raise KeyError(f"Unknown behaviour: {name!r}")
        target = self._states[name]
        if self.current is target and not kwargs.get("force"):
            return
        if self.current is not None:
            self.previous_name = self.current.name
            self.current.on_exit()
        self.current = target
        target.on_enter(**kwargs)

    def update(self, dt: float) -> None:
        if self.current is None:
            return
        next_state = self.current.update(dt)
        if next_state and next_state != self.current.name:
            self.change(next_state)

    def handle_event(self, event: str, **data) -> None:
        if self.current is not None:
            result = self.current.on_event(event, **data)
            if result and result != self.current.name:
                self.change(result)
