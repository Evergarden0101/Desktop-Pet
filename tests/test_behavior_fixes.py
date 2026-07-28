"""Regression tests for size changes, speech bubbles, phrases and climbing."""

from __future__ import annotations

import random

from desktop_pet.behaviors import register_default_behaviors
from desktop_pet.behaviors.autonomy import MODE_WEIGHTS, AutonomyController
from desktop_pet.config import AppConfig
from desktop_pet.core.environment import Environment
from desktop_pet.core.geometry import Vec2
from desktop_pet.core.pet import Pet
from desktop_pet.core.phrases import PHRASES, merged_pool, pick
from desktop_pet.platform.null import NullBackend


def make_pet(seed=7, **overrides):
    cfg = AppConfig(**overrides)
    pet = Pet(cfg, rng=random.Random(seed))
    register_default_behaviors(pet)
    backend = NullBackend()
    pet.set_environment(Environment(backend.snapshot(), cfg.interact_with_windows))
    floor = pet.env.world_floor()
    pet.body.position = Vec2(700, floor - pet.stand_offset)
    pet.state.change("idle")
    return pet, backend


def step(pet, backend, seconds, dt=1 / 60):
    for _ in range(int(seconds / dt)):
        pet.set_environment(Environment(backend.snapshot(), pet.config.interact_with_windows))
        pet.update(dt)


# --------------------------------------------------------------- rescaling
def test_rescale_keeps_feet_on_the_floor():
    """Growing the pet must not push it through the floor and off-screen."""
    pet, backend = make_pet()
    floor = pet.env.world_floor()
    assert abs(pet.feet_y() - floor) < 1.0

    for scale in (2.0, 3.5, 0.5, 1.0):
        pet.rescale(scale)
        assert abs(pet.feet_y() - floor) < 1.0, f"feet drifted at scale {scale}"
        assert pet.position.y < floor, "root must stay above the floor"


def test_rescale_while_standing_on_a_window_keeps_contact():
    pet, backend = make_pet()
    # Stand on the sample editor's title bar (x 300..1000, top y=200).
    pet.body.position = Vec2(500, 200 - pet.stand_offset)
    pet.body.on_ground = True
    pet.rescale(2.5)
    assert abs(pet.feet_y() - 200) < 1.0


def test_big_pet_stays_on_screen_after_resize_and_settle():
    pet, backend = make_pet()
    pet.rescale(3.0)
    step(pet, backend, 3.0)
    bounds = pet.env.bounds
    assert pet.feet_y() <= bounds.bottom + 1
    assert pet.body.on_ground


def test_fall_recovers_pet_that_started_below_the_world():
    """A pet somehow below every floor must be pulled back, not lost forever."""
    pet, backend = make_pet()
    floor = pet.env.world_floor()
    pet.body.position = Vec2(700, floor + 800)  # way below the screen
    pet.state.change("fall")
    step(pet, backend, 2.0)
    assert pet.body.on_ground
    assert abs(pet.feet_y() - floor) < 5.0


# ----------------------------------------------------------- speech bubble
def test_speech_bubble_is_inside_the_painted_bounds():
    """The overlay mask clips painting, so the bubble must be in bounding_rect."""
    pet, _ = make_pet()
    pet.say("hello there", 3.0)
    body = pet.body_rect()
    speech = pet.speech_rect()
    full = pet.bounding_rect()

    assert speech is not None
    assert full.top <= speech.top and full.bottom >= speech.bottom
    assert full.left <= speech.left and full.right >= speech.right
    # And the body is still fully covered.
    assert full.top <= body.top and full.bottom >= body.bottom


def test_bounds_grow_for_longer_and_cjk_text():
    pet, _ = make_pet()
    pet.say("hi", 3.0)
    short = pet.bounding_rect().width
    pet.say("a much longer sentence than before", 3.0)
    assert pet.bounding_rect().width > short
    pet.say("你好呀我是你的桌面宠物", 3.0)
    # CJK glyphs are full-width; the reservation must account for that.
    assert pet.bounding_rect().width > short


def test_speech_bubble_not_clickable_but_body_is():
    pet, _ = make_pet()
    pet.say("hello", 3.0)
    body = pet.body_rect()
    speech = pet.speech_rect()
    assert pet.contains_point(body.center.x, body.center.y)
    # A point up in the bubble must not grab the pet.
    assert not pet.contains_point(speech.center.x, speech.top + 2)


def test_bounds_shrink_when_bubble_expires():
    pet, backend = make_pet()
    pet.say("hello", 0.5)
    with_bubble = pet.bounding_rect().height
    step(pet, backend, 1.0)
    assert not pet.speech.visible
    assert pet.bounding_rect().height < with_bubble


# ----------------------------------------------------------------- phrases
def test_phrase_pools_have_english_and_chinese():
    def has_cjk(text: str) -> bool:
        return any(ord(ch) > 0x2E80 for ch in text)

    for category, lines in PHRASES.items():
        assert lines, f"{category} is empty"
        assert any(has_cjk(line) for line in lines), f"{category} has no Chinese"
        assert any(not has_cjk(line) for line in lines), f"{category} has no English"


def test_pick_is_stable_and_handles_unknown_categories():
    rng = random.Random(1)
    assert pick(rng, "greet") in PHRASES["greet"]
    assert pick(rng, "no_such_category") == ""


def test_character_phrase_overrides_merge():
    pool = merged_pool({"greet": ["yo!"]})
    assert pool["greet"] == ["yo!"]
    assert pool["sleep"] == PHRASES["sleep"]  # untouched categories survive


def test_pet_say_category_uses_pool():
    pet, _ = make_pet()
    pet.phrases = merged_pool({"greet": ["custom-greeting"]})
    pet.say_category("greet")
    assert pet.speech.text == "custom-greeting"


def test_say_ignores_empty_text():
    pet, _ = make_pet()
    pet.say("")
    assert not pet.speech.visible


# ---------------------------------------------------------------- climbing
def test_walking_into_a_window_edge_triggers_a_climb():
    """The pet should climb window sides it meets, not only ride them down."""
    pet, backend = make_pet(autonomy_enabled=False, climb_chance=1.0)
    floor = pet.env.world_floor()
    # A window sitting on the floor, to the pet's right.
    backend.windows[0].rect = backend.windows[0].rect.__class__(760, 500, 400, floor - 500)
    pet.body.position = Vec2(700, floor - pet.stand_offset)
    pet.set_environment(Environment(backend.snapshot(), True))
    pet.state.change("walk", target_x=1500, duration=30)

    for _ in range(int(6.0 * 60)):
        pet.set_environment(Environment(backend.snapshot(), True))
        pet.update(1 / 60)
        if pet.state.current_name == "climb":
            break
    assert pet.state.current_name == "climb"


def test_wall_blocking_ignores_floating_windows():
    """A window hovering above the pet must not block it - it walks underneath."""
    pet, backend = make_pet(autonomy_enabled=False)
    floor = pet.env.world_floor()
    backend.windows[0].rect = backend.windows[0].rect.__class__(760, 100, 400, 200)
    backend.windows[1].rect = backend.windows[1].rect.__class__(60, 100, 200, 150)
    pet.body.position = Vec2(700, floor - pet.stand_offset)
    pet.set_environment(Environment(backend.snapshot(), True))

    behavior = pet.state._states["walk"]
    behavior.on_enter(target_x=1500)
    assert behavior.wall_blocking(1) is None  # nothing at foot level


def test_climb_sticks_to_one_wall_while_ascending():
    pet, backend = make_pet(autonomy_enabled=False)
    # Editor window: x 300..1000, y 200..680. Climb its left edge.
    pet.body.position = Vec2(305, 640)
    pet.set_environment(Environment(backend.snapshot(), True))
    pet.state.change("climb", direction=-1)
    start_y = pet.position.y

    for _ in range(int(3.0 * 60)):
        pet.set_environment(Environment(backend.snapshot(), True))
        pet.update(1 / 60)
        if pet.state.current_name != "climb":
            break
    assert pet.position.y < start_y  # made upward progress
    assert abs(pet.position.x - 300) < 60  # stayed on that edge


def test_climb_drops_pet_when_its_window_disappears():
    pet, backend = make_pet(autonomy_enabled=False)
    pet.body.position = Vec2(305, 600)
    pet.set_environment(Environment(backend.snapshot(), True))
    pet.state.change("climb", direction=-1)
    for _ in range(30):
        pet.set_environment(Environment(backend.snapshot(), True))
        pet.update(1 / 60)

    backend.windows.clear()  # every window closed
    for _ in range(20):
        pet.set_environment(Environment(backend.snapshot(), True))
        pet.update(1 / 60)
    assert pet.state.current_name in ("fall", "idle", "land")


# ------------------------------------------------------------------- modes
def test_all_modes_are_selectable_and_produce_actions():
    for mode in MODE_WEIGHTS:
        pet, backend = make_pet(mode=mode, autonomy_min=0.1, autonomy_max=0.3)
        autonomy = AutonomyController(pet)
        seen = set()
        for _ in range(int(25 / (1 / 60))):
            pet.set_environment(Environment(backend.snapshot(), True))
            autonomy.update(1 / 60)
            pet.update(1 / 60)
            seen.add(pet.state.current_name)
        assert seen, f"mode {mode} produced no states"
        assert pet.position.x == pet.position.x  # no NaN


def test_calm_mode_avoids_running_and_climbing():
    pet, backend = make_pet(mode="calm", autonomy_min=0.1, autonomy_max=0.3)
    autonomy = AutonomyController(pet)
    seen = set()
    for _ in range(int(40 / (1 / 60))):
        pet.set_environment(Environment(backend.snapshot(), True))
        autonomy.update(1 / 60)
        pet.update(1 / 60)
        seen.add(pet.state.current_name)
    assert "run" not in seen
    assert "climb" not in seen


def test_default_mode_is_free_and_does_its_own_thing():
    cfg = AppConfig()
    assert cfg.mode == "free"
    assert cfg.autonomy_enabled

    pet, backend = make_pet(autonomy_min=0.2, autonomy_max=0.5)
    autonomy = AutonomyController(pet)
    seen = set()
    for _ in range(int(45 / (1 / 60))):
        pet.set_environment(Environment(backend.snapshot(), True))
        autonomy.update(1 / 60)
        pet.update(1 / 60)
        seen.add(pet.state.current_name)
    assert len(seen) >= 3, f"free mode should vary its activity, saw {seen}"


# ------------------------------------------------- climbing app windows
def _window_rect(backend, *args):
    return backend.windows[0].rect.__class__(*args)


def test_walking_climbs_a_window_left_edge():
    """Approaching a window head-on must trigger a climb.

    Regression: ``wall_blocking`` filtered on ``Wall.facing``, which matched
    only screen edges. A window's *left* edge faces the opposite way from the
    screen's right edge, so walking into a window never started a climb.
    """
    pet, backend = make_pet(autonomy_enabled=False, climb_chance=1.0)
    floor = pet.env.world_floor()
    backend.windows = backend.windows[:1]
    backend.windows[0].rect = _window_rect(backend, 900, 300, 500, floor - 300)
    pet.body.position = Vec2(700, floor - pet.stand_offset)
    pet.set_environment(Environment(backend.snapshot(), True))
    pet.state.change("walk", target_x=1850, duration=60)

    climbed = False
    for _ in range(60 * 12):
        pet.set_environment(Environment(backend.snapshot(), True))
        pet.update(1 / 60)
        if pet.state.current_name == "climb":
            climbed = True
    assert climbed, "pet walked into a window edge without climbing it"
    assert pet.position.y < floor - pet.stand_offset, "made no upward progress"


def test_climbing_works_from_either_side_of_a_wall():
    """Screen edges are met from the inside, window edges from the outside."""
    for start_x, expect_side in ((700, "left-of-window"), (1600, "right-of-window")):
        pet, backend = make_pet(autonomy_enabled=False, climb_chance=1.0)
        floor = pet.env.world_floor()
        backend.windows = backend.windows[:1]
        backend.windows[0].rect = _window_rect(backend, 900, 300, 500, floor - 300)
        pet.body.position = Vec2(start_x, floor - pet.stand_offset)
        pet.set_environment(Environment(backend.snapshot(), True))
        target = 1850 if start_x < 900 else 60
        pet.state.change("walk", target_x=target, duration=60)
        top = pet.position.y
        for _ in range(60 * 12):
            pet.set_environment(Environment(backend.snapshot(), True))
            pet.update(1 / 60)
            top = min(top, pet.position.y)
        assert top < floor - pet.stand_offset - 40, f"no climb from {expect_side}"


def test_window_far_overhead_is_walked_under_not_climbed():
    pet, backend = make_pet(autonomy_enabled=False, climb_chance=1.0)
    floor = pet.env.world_floor()
    backend.windows = backend.windows[:1]
    backend.windows[0].rect = _window_rect(backend, 900, 60, 500, 200)  # way up
    pet.body.position = Vec2(700, floor - pet.stand_offset)
    pet.set_environment(Environment(backend.snapshot(), True))
    pet.state.change("walk", target_x=1850, duration=60)
    for _ in range(60 * 8):
        pet.set_environment(Environment(backend.snapshot(), True))
        pet.update(1 / 60)
        assert pet.state.current_name != "climb", "climbed an unreachable window"


# ------------------------------------------------- sitting on a ledge
def test_sitting_on_a_window_hangs_the_legs_into_it():
    """Perched on a title bar, the legs must extend below the edge."""
    pet, backend = make_pet(autonomy_enabled=False, scale=1.5)
    pet.rescale(1.5)
    top = backend.windows[0].rect.top
    pet.body.position = Vec2(500, top - pet.stand_offset)
    pet.set_environment(Environment(backend.snapshot(), True))
    pet.state.change("idle")
    step(pet, backend, 0.3)
    pet.state.change("sit", duration=30)
    step(pet, backend, 2.0)

    assert pet.state.current_name == "sit", "the pet fell instead of sitting"
    assert pet.state.current.on_ledge
    lowest = pet.body_rect(pad=0).bottom
    assert lowest > top + 10, "legs do not hang over the edge"
    # The pelvis rests on the edge rather than floating above it.
    assert abs(pet.position.y - top) < pet.stand_offset * 0.3


def test_sitting_on_the_floor_keeps_feet_planted():
    pet, backend = make_pet(autonomy_enabled=False)
    floor = pet.env.world_floor()
    pet.body.position = Vec2(150, floor - pet.stand_offset)
    pet.set_environment(Environment(backend.snapshot(), True))
    pet.state.change("idle")
    step(pet, backend, 0.3)
    pet.state.change("sit", duration=30)
    step(pet, backend, 2.0)

    assert pet.state.current_name == "sit"
    assert not pet.state.current.on_ledge
    # Nothing should poke through the floor.
    assert pet.body_rect(pad=0).bottom <= floor + 2


def test_calm_mode_does_not_climb_walls_it_walks_into():
    """Mode weights must govern bumped-into climbs, not just spontaneous ones."""
    pet, backend = make_pet(autonomy_enabled=False, mode="calm", climb_chance=1.0)
    floor = pet.env.world_floor()
    backend.windows = backend.windows[:1]
    backend.windows[0].rect = _window_rect(backend, 900, 300, 500, floor - 300)
    pet.body.position = Vec2(700, floor - pet.stand_offset)
    pet.set_environment(Environment(backend.snapshot(), True))
    pet.state.change("walk", target_x=1850, duration=60)
    for _ in range(60 * 8):
        pet.set_environment(Environment(backend.snapshot(), True))
        pet.update(1 / 60)
        assert pet.state.current_name != "climb"
