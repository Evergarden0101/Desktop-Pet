"""Character library management tests (import / rename / duplicate / delete)."""

from __future__ import annotations

import os

import pytest

PIL = pytest.importorskip("PIL")
from PIL import Image, ImageDraw  # noqa: E402

from desktop_pet import characters  # noqa: E402
from desktop_pet.characters import CharacterError  # noqa: E402


@pytest.fixture()
def library(tmp_path, monkeypatch):
    """Point both the user and bundled character dirs at temp folders."""
    user_dir = tmp_path / "user"
    builtin_dir = tmp_path / "builtin"
    user_dir.mkdir()
    (builtin_dir / "default").mkdir(parents=True)
    (builtin_dir / "default" / "character.json").write_text(
        '{"name": "default", "render": {"mode": "shapes"}}', encoding="utf-8"
    )

    monkeypatch.setattr(characters, "user_characters_dir", lambda: str(user_dir))
    import desktop_pet.config as config_mod

    monkeypatch.setattr(config_mod, "user_characters_dir", lambda: str(user_dir))
    monkeypatch.setattr(config_mod, "characters_dir", lambda: str(builtin_dir))
    monkeypatch.setattr(characters, "characters_dir", lambda: str(builtin_dir))
    return user_dir


def make_image(path, size=(160, 320)):
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    cx = size[0] // 2
    d.ellipse([cx - 28, 10, cx + 28, 66], fill=(255, 220, 180, 255))
    d.rectangle([cx - 34, 66, cx + 34, 190], fill=(70, 130, 220, 255))
    d.rectangle([cx - 30, 190, cx - 4, 310], fill=(40, 40, 80, 255))
    d.rectangle([cx + 4, 190, cx + 30, 310], fill=(40, 40, 80, 255))
    img.save(path)
    return str(path)


def test_import_creates_usable_pack(library, tmp_path):
    src = make_image(tmp_path / "hero.png")
    info = characters.import_character(src, "Hero")

    assert info.name == "Hero"
    assert info.render_mode == "image"
    assert info.part_count >= 9
    assert os.path.exists(os.path.join(info.directory, "character.json"))
    assert os.path.exists(os.path.join(info.directory, "texture.png"))
    assert not info.builtin and info.can_delete

    # And it loads into a real rig.
    from desktop_pet.config import CharacterPack
    from desktop_pet.rig.loader import load_character

    loaded = load_character(CharacterPack.load(info.directory))
    assert loaded.parts
    assert loaded.skeleton.bones


def test_import_rejects_missing_and_bad_files(library, tmp_path):
    with pytest.raises(CharacterError):
        characters.import_character(str(tmp_path / "nope.png"), "Ghost")

    bogus = tmp_path / "notes.txt"
    bogus.write_text("not an image")
    with pytest.raises(CharacterError):
        characters.import_character(str(bogus), "Text")

    corrupt = tmp_path / "corrupt.png"
    corrupt.write_bytes(b"\x89PNG\r\n\x1a\n garbage")
    with pytest.raises(CharacterError):
        characters.import_character(str(corrupt), "Broken")


def test_import_rejects_blank_name(library, tmp_path):
    src = make_image(tmp_path / "x.png")
    with pytest.raises(CharacterError):
        characters.import_character(src, "   ")


def test_duplicate_names_get_suffixed(library, tmp_path):
    src = make_image(tmp_path / "twin.png")
    first = characters.import_character(src, "Twin")
    second = characters.import_character(src, "Twin")
    assert first.name == "Twin"
    assert second.name != "Twin"
    assert {"Twin", second.name} <= {c.name for c in characters.list_characters()}


def test_rename_and_delete(library, tmp_path):
    src = make_image(tmp_path / "a.png")
    info = characters.import_character(src, "Alpha")

    renamed = characters.rename_character("Alpha", "Beta")
    assert renamed.name == "Beta"
    assert "Alpha" not in {c.name for c in characters.list_characters()}

    characters.delete_character("Beta")
    assert "Beta" not in {c.name for c in characters.list_characters()}


def test_builtin_is_protected(library):
    with pytest.raises(CharacterError):
        characters.delete_character("default")
    with pytest.raises(CharacterError):
        characters.rename_character("default", "mine")


def test_duplicate_builtin_then_edit(library):
    copy = characters.duplicate_character("default")
    assert copy.name != "default"
    assert copy.can_delete
    characters.delete_character(copy.name)


def test_unicode_names_supported(library, tmp_path):
    src = make_image(tmp_path / "cn.png")
    info = characters.import_character(src, "小猫")
    assert info.name == "小猫"
    assert "小猫" in {c.name for c in characters.list_characters()}


def test_sanitize_strips_path_separators():
    assert "/" not in characters.sanitize_name("evil/../name")
    assert "\\" not in characters.sanitize_name(r"evil\\name")
    with pytest.raises(CharacterError):
        characters.sanitize_name("")
