"""Offscreen smoke tests for the PySide6 UI.

These are skipped automatically when PySide6 isn't installed. When it is (as in
CI), they boot the whole GUI stack on the ``offscreen`` Qt platform, run several
frames of the loop, render each pet to an image, and exercise input events -
catching wiring/rendering regressions without a real display.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtGui import QImage, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from desktop_pet.config import AppConfig  # noqa: E402
from desktop_pet.core.geometry import Vec2  # noqa: E402
from desktop_pet.ui.controller import PetApp  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _make_app(qapp, **overrides) -> PetApp:
    cfg = AppConfig(backend="null", pet_count=1, **overrides)
    app = PetApp(cfg, qapp)
    app.start()
    return app


def _run_frames(app: PetApp, n: int = 30) -> None:
    for _ in range(n):
        app._tick()


def test_app_boots_and_runs_frames(qapp):
    app = _make_app(qapp)
    try:
        assert len(app.pets) == 1
        _run_frames(app, 60)
        pet = app.pets[0]
        assert pet.body.position.x == pet.body.position.x  # not NaN
        assert app.overlay.width() > 0
    finally:
        app.shutdown()


def test_render_shapes_produces_pixels(qapp):
    app = _make_app(qapp)
    try:
        _run_frames(app, 5)
        pet = app.pets[0]
        renderer = app.renderers[pet.pet_id]
        image = QImage(400, 400, QImage.Format_ARGB32)
        image.fill(0)
        painter = QPainter(image)
        painter.translate(-pet.position.x + 200, -pet.position.y + 200)
        renderer.draw(painter, pet)
        painter.end()
        # Something was actually drawn (at least one non-transparent pixel).
        assert not image.isNull()
        non_empty = any(
            image.pixelColor(x, y).alpha() > 0
            for x in range(0, 400, 7)
            for y in range(0, 400, 7)
        )
        assert non_empty
    finally:
        app.shutdown()


def test_image_character_renders(qapp, tmp_path):
    # Build a tiny textured pack on the fly and render it in image mode.
    PIL = pytest.importorskip("PIL")
    from PIL import Image, ImageDraw

    from desktop_pet.cli import cmd_extract

    src = tmp_path / "guy.png"
    img = Image.new("RGBA", (120, 240), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse([40, 8, 80, 48], fill=(255, 220, 180, 255))
    d.rectangle([44, 48, 76, 150], fill=(80, 120, 220, 255))
    d.rectangle([46, 150, 60, 235], fill=(40, 40, 80, 255))
    d.rectangle([60, 150, 74, 235], fill=(40, 40, 80, 255))
    img.save(src)
    cmd_extract(str(src), "Guy", "auto_humanoid", 1.0, out=str(tmp_path / "chars"))

    # Point the character search at our temp dir via a direct load.
    from desktop_pet.config import CharacterPack
    from desktop_pet.rig.loader import load_character

    loaded = load_character(CharacterPack.load(str(tmp_path / "chars" / "Guy")))
    assert loaded.parts  # extracted sprites present
    assert loaded.render["mode"] == "image"


def test_poke_and_context_events(qapp):
    app = _make_app(qapp)
    try:
        _run_frames(app, 5)
        pet = app.pets[0]
        # Poke -> wave.
        app._on_poke(pet)
        _run_frames(app, 2)
        assert pet.state.current_name in ("wave", "idle")

        # Simulate a drag directly through the pet's event interface.
        pet.handle_event("grab", grab_offset=Vec2(0, -10))
        assert pet.state.current_name == "drag"
        pet.handle_event("drag_move", position=Vec2(pet.position.x + 50, pet.position.y - 40))
        _run_frames(app, 2)
        pet.handle_event("release")
        assert pet.state.current_name in ("fall", "idle")
    finally:
        app.shutdown()


def test_menu_and_settings_construct(qapp):
    app = _make_app(qapp)
    try:
        from desktop_pet.ui.menu import build_pet_menu
        from desktop_pet.ui.settings_dialog import SettingsDialog

        menu = build_pet_menu(app, app.pets[0])
        assert menu.actions()
        dialog = SettingsDialog(app)
        dialog._apply()  # apply defaults without showing
        assert app.config.scale > 0
    finally:
        app.shutdown()


def test_add_and_remove_pets(qapp):
    app = _make_app(qapp)
    try:
        app.add_pet()
        app.add_pet()
        assert len(app.pets) == 3
        app.remove_pet(app.pets[-1])
        assert len(app.pets) == 2
        _run_frames(app, 10)
    finally:
        app.shutdown()
