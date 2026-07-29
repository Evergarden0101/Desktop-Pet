"""Terrain and movement tests.

Run headless:  QT_QPA_PLATFORM=offscreen python tests/test_physics.py
"""

from __future__ import annotations

import os
import random
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from PySide6.QtCore import QRect  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from desktop_pet.assets import discover  # noqa: E402
from desktop_pet.config import Config  # noqa: E402
from desktop_pet.obstacles import Ledge, Terrain  # noqa: E402
from desktop_pet.pet import Pet, State  # noqa: E402
from desktop_pet.strings import Strings  # noqa: E402

FLOOR_Y = 700
FLOOR = QRect(0, 0, 1280, FLOOR_Y)


class FakeApp:
    """Just enough of PetApp for a Pet to run."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.strings = Strings("en")
        self.paused = False
        self.terrain = None

    def echo_husband(self, origin):
        pass


def terrain_with(*rects: QRect) -> Terrain:
    ledges = [Ledge(float(FLOOR_Y), 0.0, 1280.0)]
    for r in rects:
        ledges.append(Ledge(float(r.top()), float(r.left()), float(r.right())))
    return Terrain(ledges=ledges, walls=list(rects), floor=FLOOR)


def run(pet: Pet, terrain: Terrain, seconds: float, dt: float = 0.033) -> None:
    for _ in range(int(seconds / dt)):
        pet.tick(dt, terrain)


def make_pet(app, assets, x, y, facing_right=True) -> Pet:
    pet = Pet(assets, app, x, y)
    pet.facing_right = facing_right
    return pet


def main() -> int:
    qapp = QApplication(sys.argv[:1])
    cfg = Config()
    cfg.play_chance = 0.0          # keep the tests deterministic
    app = FakeApp(cfg)

    pets = discover(ROOT / "assets" / "pets", cfg.scale)
    assert pets, "no pet assets built -- run tools/make_frames.py first"
    assets = pets[0]
    ph = assets.size[1]
    failures = []

    def check(name, condition, detail=""):
        if condition:
            print(f"  PASS  {name}")
        else:
            print(f"  FAIL  {name} {detail}")
            failures.append(name)

    print("terrain")
    low = QRect(600, FLOOR_Y - int(ph * 0.4), 400, int(ph * 0.4))
    tall = QRect(600, FLOOR_Y - ph * 3, 400, ph * 3)

    t = terrain_with(low)
    check("floor is a ledge", t.ledge_at(300, FLOOR_Y) is not None)
    check("window top is a ledge", t.ledge_at(700, low.top()) is not None)
    check("wall blocks a pet on the floor",
          t.blocking_wall(605, FLOOR_Y) is not None)
    check("wall does not block a pet standing on it",
          t.blocking_wall(700, low.top()) is None)
    check("no wall in open space", t.blocking_wall(300, FLOOR_Y) is None)
    check("ledge_under finds the floor from mid-air",
          (t.ledge_under(300, 100) or Ledge(-1, 0, 0)).y == FLOOR_Y)

    print("climbing a low window edge")
    pet = make_pet(app, assets, 300, FLOOR_Y - ph)
    run(pet, terrain_with(low), 8.0)
    check("ends up standing on the window top",
          abs(pet.bottom - low.top()) < 3 and pet.state is State.CRAWL,
          f"(bottom={pet.bottom:.0f} want={low.top()})")

    print("turning at a tall window edge")
    pet = make_pet(app, assets, 300, FLOOR_Y - ph)
    run(pet, terrain_with(tall), 8.0)
    check("stays on the floor", abs(pet.bottom - FLOOR_Y) < 3,
          f"(bottom={pet.bottom:.0f})")
    check("never crosses into the window",
          pet.center_x < tall.left() + 20, f"(center={pet.center_x:.0f})")

    print("falling")
    pet = make_pet(app, assets, 300, 100)
    pet.state = State.FALL
    run(pet, terrain_with(), 4.0)
    check("lands on the floor", abs(pet.bottom - FLOOR_Y) < 3,
          f"(bottom={pet.bottom:.0f})")
    check("stops falling", pet.state is State.CRAWL)

    print("landing on a window instead of the floor")
    pet = make_pet(app, assets, 700, 50)
    pet.state = State.FALL
    run(pet, terrain_with(low), 4.0)
    check("lands on the window top", abs(pet.bottom - low.top()) < 3,
          f"(bottom={pet.bottom:.0f} want={low.top()})")

    print("walking off a ledge end")
    random.seed(7)
    pet = make_pet(app, assets, low.right() - assets.size[0] // 2,
                   low.top() - ph, facing_right=True)
    fell = False
    for _ in range(400):
        pet.tick(0.033, terrain_with(low))
        if pet.state is State.FALL:
            fell = True
    run(pet, terrain_with(low), 3.0)
    check("either turned back or fell and landed safely",
          abs(pet.bottom - low.top()) < 3 or abs(pet.bottom - FLOOR_Y) < 3,
          f"(bottom={pet.bottom:.0f}, fell={fell})")

    print("staying on screen")
    pet = make_pet(app, assets, 10, FLOOR_Y - ph, facing_right=False)
    run(pet, terrain_with(), 6.0)
    check("does not crawl off the left edge", pet.center_x > FLOOR.left(),
          f"(center={pet.center_x:.0f})")

    print("the speech bubble")
    pet = make_pet(app, assets, 400, FLOOR_Y - ph)
    pet.call_husband()
    head = pet.head_point()
    b = pet.bubble.geometry()
    check("bubble is visible", pet.bubble.isVisible())
    check("bubble has text", bool(pet.bubble._text))
    check("bubble sits beside the head, not on top of it",
          b.right() <= head.x() + 8 or b.left() >= head.x() - 8,
          f"(bubble={b}, head={head})")
    check("bubble is vertically level with the head",
          b.top() - 20 <= head.y() <= b.bottom() + 20,
          f"(bubble={b}, head={head})")
    check("head anchor is inside the sprite",
          0 <= head.x() - pet.x <= pet.width() and 0 <= head.y() - pet.y <= pet.height())

    # regression: the fade-out used to leave a finished->hide connection behind,
    # which then hid the *next* bubble the moment it faded in
    pet.bubble._fade_out()
    pet.call_husband()
    qapp.processEvents()
    check("bubble survives being re-shown after a fade-out", pet.bubble.isVisible())

    print("the bubble follows the pet")
    before = pet.bubble.pos()
    pet.x += 120
    pet.bubble.follow(pet.head_point())
    check("bubble moves with her", pet.bubble.pos() != before)

    print()
    if failures:
        print(f"{len(failures)} FAILED: {', '.join(failures)}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
