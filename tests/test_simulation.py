"""Headless integration tests: run the whole simulation without a GUI.

These drive :class:`Pet` + behaviours + :class:`Environment` exactly as the UI
would, but with the synthetic :class:`NullBackend`, so we can assert the pet
behaves sanely (stays in bounds, lands after falling, transitions between
states, climbs walls) on any platform.
"""

from __future__ import annotations

import random

from desktop_pet.behaviors import register_default_behaviors
from desktop_pet.behaviors.autonomy import AutonomyController
from desktop_pet.config import AppConfig
from desktop_pet.core.environment import Environment
from desktop_pet.core.geometry import Vec2
from desktop_pet.core.pet import Pet
from desktop_pet.platform.null import NullBackend


def make_pet(seed=1234, **cfg_overrides):
    cfg = AppConfig(**cfg_overrides)
    pet = Pet(cfg, rng=random.Random(seed))
    register_default_behaviors(pet)
    backend = NullBackend()
    pet.set_environment(Environment(backend.snapshot(), cfg.interact_with_windows))
    # Start standing on the floor.
    floor = pet.env.world_floor()
    pet.body.position = Vec2(600, floor - pet.stand_offset)
    pet.state.change("idle")
    return pet, backend


def step(pet, backend, seconds, dt=1 / 60, autonomy=None):
    steps = int(seconds / dt)
    for _ in range(steps):
        pet.set_environment(Environment(backend.snapshot(), pet.config.interact_with_windows))
        if autonomy is not None:
            autonomy.update(dt)
        pet.update(dt)


def test_pet_initializes_and_idles():
    pet, backend = make_pet()
    step(pet, backend, 1.0)
    assert pet.state.current_name in ("idle", "walk", "run", "sit", "creep", "sleep")
    assert pet.body.on_ground


def test_pet_falls_and_lands_on_floor():
    pet, backend = make_pet()
    # Drop from the top of the screen at x=150 (no window in that column).
    pet.body.position = Vec2(150, 50)
    pet.state.change("fall")
    step(pet, backend, 4.0)
    floor = pet.env.world_floor()
    assert pet.body.on_ground
    assert abs(pet.feet_y() - floor) < 5.0


def test_pet_lands_on_window_top():
    pet, backend = make_pet()
    # Above the sample editor window (x 300..1000, top=200); should catch it.
    pet.body.position = Vec2(500, 40)
    pet.state.change("fall")
    step(pet, backend, 4.0)
    assert pet.body.on_ground
    assert abs(pet.feet_y() - 200) < 5.0  # landed on the window's title bar


def test_walk_stays_in_bounds():
    pet, backend = make_pet(autonomy_enabled=False)
    for target in (50, 1900, 300):
        pet.state.change("walk", target_x=target, duration=30)
        step(pet, backend, 6.0)
        bounds = pet.env.bounds
        assert bounds.left <= pet.body.position.x <= bounds.right


def test_drag_and_throw():
    pet, backend = make_pet()
    pet.handle_event("grab", grab_offset=Vec2(0, -20))
    assert pet.state.current_name == "drag"
    # Simulate a quick drag to the upper-left then release.
    for i in range(10):
        pet.set_environment(Environment(backend.snapshot()))
        pet.handle_event("drag_move", position=Vec2(600 - i * 15, 200 - i * 10))
        pet.update(1 / 60)
    pet.handle_event("release")
    assert pet.state.current_name == "fall"
    step(pet, backend, 4.0)
    assert pet.body.on_ground  # eventually lands again


def test_climb_reaches_window_top():
    pet, backend = make_pet(autonomy_enabled=False)
    # Place the pet against the sample editor's left wall (x=300, y 200..680).
    pet.body.position = Vec2(305, 600)
    pet.state.change("climb", direction=-1)
    step(pet, backend, 8.0)
    # It should have mounted the top (idle on the window) or still be climbing up.
    assert pet.body.position.y < 600  # made upward progress
    assert pet.state.current_name in ("idle", "climb", "fall")


def test_autonomy_changes_behaviors_over_time():
    pet, backend = make_pet(autonomy_min=0.2, autonomy_max=0.5)
    autonomy = AutonomyController(pet)
    seen = set()
    dt = 1 / 60
    for _ in range(int(40 / dt)):
        pet.set_environment(Environment(backend.snapshot()))
        autonomy.update(dt)
        pet.update(dt)
        seen.add(pet.state.current_name)
    # Over 40 seconds the autonomy brain should have tried several actions.
    assert len(seen) >= 3


def test_window_moving_out_from_under_pet_makes_it_fall():
    pet, backend = make_pet(autonomy_enabled=False)
    # Stand the pet on the browser window top (x 1050..1670, top=120).
    pet.body.position = Vec2(1300, 120 - pet.stand_offset)
    pet.set_environment(Environment(backend.snapshot()))
    pet.state.change("idle")
    step(pet, backend, 0.3)
    assert pet.body.on_ground
    # Now move that window far away; the ledge is gone.
    backend.windows[1].rect = backend.windows[1].rect.__class__(50, 900, 200, 100)
    step(pet, backend, 3.0)
    # The pet should have fallen and re-landed on the floor below.
    assert abs(pet.feet_y() - pet.env.world_floor()) < 6.0


def test_simulation_never_produces_nan():
    pet, backend = make_pet()
    autonomy = AutonomyController(pet)
    step(pet, backend, 30.0, autonomy=autonomy)
    assert pet.body.position.x == pet.body.position.x  # not NaN
    assert pet.body.position.y == pet.body.position.y
