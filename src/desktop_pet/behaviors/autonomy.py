"""The autonomy brain: decides what an idle pet should do next.

This is intentionally *not* a behaviour/state - it sits above the state machine
and, whenever the pet has been idle long enough, picks a feasible action from
the user's ``enabled_behaviors`` (only offering "climb" when a wall is nearby,
biasing toward "sleep" when energy is low, and so on).
"""

from __future__ import annotations

from typing import Dict, List, Tuple

from ..core.pet import Pet
from ..core.phrases import pick

# Per-mode multipliers applied to each behaviour's base weight. A missing entry
# means 1.0, so a mode only needs to state what it changes. This is what makes
# "free" feel busy and curious while "calm" mostly loiters.
MODE_WEIGHTS: Dict[str, Dict[str, float]] = {
    "free": {},
    "mischief": {
        "climb": 3.0,
        "creep": 2.5,
        "run": 2.0,
        "sit": 1.5,
        "sleep": 0.2,
        "idle_look": 0.5,
    },
    "calm": {
        "walk": 0.5,
        "run": 0.0,
        "climb": 0.0,
        "creep": 0.2,
        "chase_cursor": 0.0,
        "sit": 2.0,
        "sleep": 2.0,
        "idle_look": 2.0,
    },
    "follow": {
        "chase_cursor": 6.0,
        "walk": 0.5,
        "run": 0.5,
        "climb": 0.5,
        "sleep": 0.2,
    },
}

MODE_LABELS = {
    "free": "Free spirit (does its own thing)",
    "mischief": "Mischief (loves climbing your windows)",
    "calm": "Calm (mostly relaxes)",
    "follow": "Follow the cursor",
}


class AutonomyController:
    def __init__(self, pet: Pet):
        self.pet = pet
        self._timer = self._next_delay()
        self._chatter = pet.rng.uniform(8.0, 20.0)

    def _next_delay(self) -> float:
        cfg = self.pet.config
        return self.pet.rng.uniform(cfg.autonomy_min, cfg.autonomy_max)

    def _mode_weight(self, name: str) -> float:
        table = MODE_WEIGHTS.get(self.pet.config.mode, {})
        return table.get(name, 1.0)

    # ------------------------------------------------------------- feasibility
    def _candidates(self) -> List[Tuple[str, float, dict]]:
        """Return ``(behaviour, weight, kwargs)`` options valid right now."""
        pet = self.pet
        cfg = pet.config
        enabled = set(cfg.enabled_behaviors)
        options: List[Tuple[str, float, dict]] = []

        def offer(name: str, weight: float, **kwargs) -> None:
            weight *= self._mode_weight(name)
            if weight <= 0:
                return
            if name in enabled and pet.state.has(name):
                options.append((name, weight, kwargs))

        bounds = pet.env.bounds
        target = pet.rng.uniform(bounds.left + 40, bounds.right - 40)

        # Prefer heading toward an interesting window edge rather than a random
        # spot, so the pet visibly seeks out things to climb on.
        edge_x = self._nearby_window_edge()
        if edge_x is not None and pet.rng.random() < 0.6:
            target = edge_x

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

    def _nearby_window_edge(self) -> float | None:
        """X of the closest climbable window edge that shares the pet's floor."""
        pet = self.pet
        feet = pet.feet_y()
        best_x = None
        best_dist = 900.0
        for wall in pet.env.walls:
            if wall.window_handle is None:
                continue
            if not (wall.y0 <= feet <= wall.y1 + 4):
                continue  # not reachable from the surface the pet stands on
            dist = abs(wall.x - pet.body.position.x)
            if 30.0 < dist < best_dist:
                best_dist = dist
                best_x = wall.x
        return best_x

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

        self._chatter_tick(dt)

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


    def _chatter_tick(self, dt: float) -> None:
        """Occasionally say something, weighted by how the pet is feeling."""
        pet = self.pet
        if not pet.config.show_speech_bubbles:
            return
        self._chatter -= dt
        if self._chatter > 0:
            return
        self._chatter = pet.rng.uniform(14.0, 34.0)
        if pet.speech.visible:
            return  # don't talk over an existing bubble

        if pet.config.stats_enabled and pet.stats.hunger > 70:
            category = "hungry"
        elif pet.config.stats_enabled and pet.stats.energy < 30:
            category = "tired"
        else:
            category = {"climb": "climb", "sit": "sit", "walk": "walk"}.get(
                pet.state.current_name or "", "idle"
            )
        pet.say(pick(pet.rng, category, pet.phrases), 3.0)


def make_autonomy(pet: Pet) -> AutonomyController:
    return AutonomyController(pet)
