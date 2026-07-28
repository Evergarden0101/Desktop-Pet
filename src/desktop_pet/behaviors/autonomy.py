"""The autonomy brain: decides what an idle pet should do next.

This is intentionally *not* a behaviour/state - it sits above the state machine
and, whenever the pet has been idle long enough, picks a feasible action from
the user's ``enabled_behaviors`` (only offering "climb" when a wall is nearby,
biasing toward "sleep" when energy is low, and so on).
"""

from __future__ import annotations

from typing import Dict, List, Tuple

from ..core.pet import Pet


class AutonomyController:
    def __init__(self, pet: Pet):
        self.pet = pet
        self._timer = self._next_delay()

    def _next_delay(self) -> float:
        cfg = self.pet.config
        return self.pet.rng.uniform(cfg.autonomy_min, cfg.autonomy_max)

    # ------------------------------------------------------------- feasibility
    def _candidates(self) -> List[Tuple[str, float, dict]]:
        """Return ``(behaviour, weight, kwargs)`` options valid right now."""
        pet = self.pet
        cfg = pet.config
        enabled = set(cfg.enabled_behaviors)
        options: List[Tuple[str, float, dict]] = []

        def offer(name: str, weight: float, **kwargs) -> None:
            if name in enabled and pet.state.has(name):
                options.append((name, weight, kwargs))

        bounds = pet.env.bounds
        target = pet.rng.uniform(bounds.left + 40, bounds.right - 40)

        offer("walk", 3.0, target_x=target, duration=pet.rng.uniform(2, 5))
        offer("run", 1.0, target_x=target, duration=pet.rng.uniform(1.5, 3))
        offer("creep", 1.2, duration=pet.rng.uniform(3, 6))
        offer("wave", 0.8)
        offer("cheer", 0.5)
        offer("sit", 1.5, duration=pet.rng.uniform(5, 10))
        offer("chase_cursor", 1.0 if cfg.follow_cursor else 0.4)

        # Climb only when there's actually a wall within reach.
        if pet.env.nearest_wall(pet.body.position, 60.0) is not None:
            offer("climb", 2.5, direction=-1)

        # Sleep more when tired.
        sleep_weight = 0.6
        if pet.stats.energy < 35:
            sleep_weight = 3.5
        offer("sleep", sleep_weight, duration=pet.rng.uniform(6, 14))

        return options

    def _choose(self, options: List[Tuple[str, float, dict]]):
        total = sum(weight for _, weight, _ in options)
        if total <= 0:
            return None
        roll = self.pet.rng.uniform(0, total)
        upto = 0.0
        for name, weight, kwargs in options:
            upto += weight
            if roll <= upto:
                return name, kwargs
        return options[-1][0], options[-1][2]

    # ------------------------------------------------------------------- tick
    def update(self, dt: float) -> None:
        pet = self.pet
        if not pet.config.autonomy_enabled:
            return
        # Only interrupt when the pet is settled (idle).
        if pet.state.current_name != "idle":
            self._timer = self._next_delay()
            return

        self._timer -= dt
        if self._timer > 0:
            return
        self._timer = self._next_delay()

        options = self._candidates()
        choice = self._choose(options)
        if choice is None:
            return
        name, kwargs = choice
        pet.state.change(name, **kwargs)


def make_autonomy(pet: Pet) -> AutonomyController:
    return AutonomyController(pet)
