"""Base class for behaviours (the states of the pet's state machine).

A behaviour bundles three things:

* a *pose driver* - what the body does each frame (via the pose library / IK);
* *locomotion* - how the pet moves through the world (via physics + environment);
* *transitions* - when to hand control to another behaviour.

Behaviours are deliberately small and composable; the autonomy brain
(:mod:`desktop_pet.behaviors.autonomy`) sequences them.
"""

from __future__ import annotations

from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ..core.pet import Pet
    from ..core.environment import Environment


class Behavior:
    #: Registered name; also the value used in ``AppConfig.enabled_behaviors``.
    name: str = "base"
    #: Human-friendly label for menus.
    label: str = "Base"
    #: Whether the autonomy brain may pick this behaviour spontaneously.
    autonomous: bool = True

    def __init__(self, pet: "Pet"):
        self.pet = pet
        self.time_in_state: float = 0.0

    # ---- convenience accessors ------------------------------------------- #
    @property
    def env(self) -> "Environment":
        return self.pet.env

    @property
    def config(self):
        return self.pet.config

    @property
    def poses(self):
        return self.pet.poses

    # ---- lifecycle ------------------------------------------------------- #
    def on_enter(self, **kwargs) -> None:
        self.time_in_state = 0.0

    def on_exit(self) -> None:
        pass

    def update(self, dt: float) -> Optional[str]:
        """Advance the behaviour. Return a behaviour name to transition, else None."""
        self.time_in_state += dt
        return None

    def on_event(self, event: str, **data) -> Optional[str]:
        """Handle a UI/system event. Return a behaviour name to transition."""
        # Universal reactions shared by most behaviours.
        if event == "grab" and self.config.draggable:
            return "drag"
        return None
