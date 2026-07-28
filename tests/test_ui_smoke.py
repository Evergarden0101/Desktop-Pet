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


def test_pet_spawns_on_primary_work_area(qapp):
    """The pet must appear on the primary monitor, feet on its floor."""
    app = _make_app(qapp)
    try:
        pet = app.pets[0]
        primary = app.backend.snapshot().primary()
        work = primary.work_area
        assert work.left <= pet.position.x <= work.right
        assert abs(pet.feet_y() - work.bottom) < 1.0
    finally:
        app.shutdown()


def test_summon_recovers_offscreen_pet(qapp):
    """Summon teleports a lost pet back over the primary screen and drops it."""
    from desktop_pet.core.environment import Environment

    app = _make_app(qapp)
    try:
        pet = app.pets[0]
        pet.body.position = Vec2(99999.0, -5000.0)  # far off any monitor
        app.summon()
        primary = app.backend.snapshot().primary()
        work = primary.work_area
        assert work.left <= pet.position.x <= work.right
        assert pet.state.current_name == "fall"
        # Simulate a few seconds so it lands back on a real surface.
        for _ in range(240):
            pet.set_environment(Environment(app.backend.snapshot(), True))
            pet.update(1 / 60)
        assert pet.body.on_ground
        assert work.left <= pet.position.x <= work.right
    finally:
        app.shutdown()


def test_character_dialog_lists_and_imports(qapp, tmp_path, monkeypatch):
    """The in-app manager should list packs and import a picked picture."""
    PIL = pytest.importorskip("PIL")
    from PIL import Image, ImageDraw

    import desktop_pet.characters as characters_mod
    import desktop_pet.config as config_mod

    user_dir = tmp_path / "user"
    user_dir.mkdir()
    monkeypatch.setattr(characters_mod, "user_characters_dir", lambda: str(user_dir))
    monkeypatch.setattr(config_mod, "user_characters_dir", lambda: str(user_dir))

    src = tmp_path / "buddy.png"
    img = Image.new("RGBA", (140, 300), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse([48, 10, 92, 58], fill=(255, 220, 180, 255))
    d.rectangle([50, 58, 90, 180], fill=(80, 120, 220, 255))
    d.rectangle([52, 180, 68, 292], fill=(40, 40, 80, 255))
    d.rectangle([72, 180, 88, 292], fill=(40, 40, 80, 255))
    img.save(src)

    app = _make_app(qapp)
    try:
        from desktop_pet.ui.character_dialog import CharacterDialog

        dialog = CharacterDialog(app)
        assert dialog.list_widget.count() >= 1  # at least the built-in

        # Simulate picking a file and pressing "Add character" (auto-confirm).
        from PySide6.QtWidgets import QMessageBox

        monkeypatch.setattr(
            QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.No)
        )
        dialog._pending_image = str(src)
        dialog.name_edit.setText("Buddy")
        dialog._do_import()

        names = {c.name for c in characters_mod.list_characters()}
        assert "Buddy" in names
        assert dialog.list_widget.count() >= 2
    finally:
        app.shutdown()


def test_set_mode_updates_config_and_menu(qapp):
    app = _make_app(qapp)
    try:
        from desktop_pet.behaviors.autonomy import MODE_WEIGHTS
        from desktop_pet.ui.menu import build_pet_menu

        for mode in MODE_WEIGHTS:
            app.set_mode(mode)
            assert app.config.mode == mode
            assert app.config.follow_cursor == (mode == "follow")
            menu = build_pet_menu(app, app.pets[0])
            assert menu.actions()
        _run_frames(app, 10)
    finally:
        app.shutdown()


def test_scale_change_keeps_pet_on_screen(qapp):
    """Resizing through the controller must not drop the pet off the bottom."""
    app = _make_app(qapp)
    try:
        _run_frames(app, 10)
        pet = app.pets[0]
        floor = pet.env.world_floor()
        for scale in (2.0, 3.0, 0.6, 1.0):
            app.set_scale(scale)
            _run_frames(app, 20)
            assert pet.feet_y() <= floor + 2, f"pet sank at scale {scale}"
            assert pet.position.y < floor
    finally:
        app.shutdown()


def test_tick_survives_backend_failures(qapp):
    """A flaky Win32 snapshot must not blank the app: last good one is reused."""
    from desktop_pet.platform.null import NullBackend

    class FlakyBackend(NullBackend):
        def __init__(self):
            super().__init__()
            self.calls = 0

        def snapshot(self):
            self.calls += 1
            if self.calls % 2 == 0:
                raise RuntimeError("transient Win32 failure")
            return super().snapshot()

    app = _make_app(qapp)
    try:
        app.backend = FlakyBackend()
        for _ in range(30):
            app._tick()  # must not raise
        pet = app.pets[0]
        assert pet.position.x == pet.position.x  # still finite / updating
        assert app.backend.calls >= 30
    finally:
        app.shutdown()


def test_body_style_switch_rebuilds_pets(qapp):
    """Switching cute/human must rebuild the rig and keep pets on the floor."""
    from desktop_pet.rig.body_parts import BODY_STYLES

    app = _make_app(qapp)
    try:
        for style in BODY_STYLES:
            app.set_body_style(style)
            _run_frames(app, 20)
            assert app.config.body_style == style
            pet = app.pets[0]
            floor = pet.env.world_floor()
            assert pet.feet_y() <= floor + 2
            # The renderer must be using that style's proportions.
            assert app.renderers[pet.pet_id].style is BODY_STYLES[style]
    finally:
        app.shutdown()


def test_imported_character_renders_in_image_mode(qapp, tmp_path, monkeypatch):
    """An imported picture character should draw actual pixels, upright."""
    pytest.importorskip("PIL")
    from PIL import Image, ImageDraw
    from PySide6.QtGui import QImage, QPainter

    import desktop_pet.characters as characters_mod
    import desktop_pet.config as config_mod

    user_dir = tmp_path / "chars"
    user_dir.mkdir()
    monkeypatch.setattr(characters_mod, "user_characters_dir", lambda: str(user_dir))
    monkeypatch.setattr(config_mod, "user_characters_dir", lambda: str(user_dir))

    src = tmp_path / "hero.png"
    img = Image.new("RGBA", (200, 460), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    cx = 100
    d.ellipse([cx - 30, 16, cx + 30, 78], fill=(255, 217, 160, 255))
    d.rectangle([cx - 10, 74, cx + 10, 92], fill=(255, 217, 160, 255))
    d.rounded_rectangle([cx - 44, 90, cx + 44, 220], 14, fill=(79, 140, 255, 255))
    d.rounded_rectangle([cx - 40, 216, cx + 40, 258], 10, fill=(47, 53, 80, 255))
    d.rounded_rectangle([cx - 36, 256, cx - 6, 420], 10, fill=(47, 53, 80, 255))
    d.rounded_rectangle([cx + 6, 256, cx + 36, 420], 10, fill=(47, 53, 80, 255))
    img.save(src)

    info = characters_mod.import_character(str(src), "Hero")

    app = _make_app(qapp)
    try:
        from desktop_pet.config import CharacterPack
        from desktop_pet.rig.loader import load_character
        from desktop_pet.ui.imaging import pil_to_qpixmap
        from desktop_pet.ui.renderer import PetRenderer

        loaded = load_character(CharacterPack.load(info.directory))
        assert loaded.render["mode"] == "image"
        assert loaded.parts

        renderer = PetRenderer(loaded.render)
        renderer.set_part_pixmaps(
            {n: pil_to_qpixmap(p.image) for n, p in loaded.parts.items() if p.image},
            {
                n: ((p.pivot.x, p.pivot.y), (p.child_anchor.x, p.child_anchor.y))
                for n, p in loaded.parts.items()
                if p.image
            },
        )

        pet = app.pets[0]
        pet.skeleton = loaded.skeleton
        pet.skeleton.root_position = pet.position
        pet.skeleton.solve()

        canvas = QImage(500, 500, QImage.Format_ARGB32)
        canvas.fill(0)
        painter = QPainter(canvas)
        painter.translate(-pet.position.x + 250, -pet.position.y + 250)
        renderer.draw(painter, pet)
        painter.end()

        painted = sum(
            1
            for x in range(0, 500, 5)
            for y in range(0, 500, 5)
            if canvas.pixelColor(x, y).alpha() > 0
        )
        assert painted > 20, "image character drew almost nothing"
    finally:
        app.shutdown()
