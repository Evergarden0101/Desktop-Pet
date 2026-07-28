"""Character library management: import, list, rename, duplicate, delete.

This is the logic behind the in-app *Character Manager*. It is deliberately
GUI-free (only Pillow) so it can be unit-tested headlessly and reused by the
CLI - the dialog in :mod:`desktop_pet.ui.character_dialog` is a thin shell over
these functions.
"""

from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass
from typing import Dict, List, Optional

from .config import (
    CharacterPack,
    characters_dir,
    discover_characters,
    user_characters_dir,
)

#: Image types the import dialog accepts.
SUPPORTED_IMAGE_EXTENSIONS = (".png", ".webp", ".jpg", ".jpeg", ".bmp", ".gif")

_SAFE_NAME = re.compile(r"[^\w\- ]+", re.UNICODE)


class CharacterError(Exception):
    """Raised when an import/edit cannot be completed (message is user-facing)."""


@dataclass
class CharacterInfo:
    """One entry in the character library, as shown in the manager."""

    name: str
    directory: str
    builtin: bool
    render_mode: str
    has_texture: bool
    part_count: int
    author: str = ""

    @property
    def can_delete(self) -> bool:
        return not self.builtin

    @property
    def preview_path(self) -> Optional[str]:
        """Best image to show as a thumbnail, if any."""
        pack_texture = os.path.join(self.directory, "texture.png")
        if os.path.exists(pack_texture):
            return pack_texture
        head = os.path.join(self.directory, "parts", "head.png")
        if os.path.exists(head):
            return head
        return None


def sanitize_name(name: str) -> str:
    """Make ``name`` safe to use as a folder name (keeps unicode letters)."""
    cleaned = _SAFE_NAME.sub("", (name or "").strip())
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned:
        raise CharacterError("Please enter a character name.")
    if len(cleaned) > 48:
        cleaned = cleaned[:48].strip()
    return cleaned


def unique_name(name: str) -> str:
    """Append a counter until ``name`` doesn't collide with an existing pack."""
    existing = set(discover_characters())
    if name not in existing:
        return name
    for i in range(2, 999):
        candidate = f"{name} {i}"
        if candidate not in existing:
            return candidate
    raise CharacterError("Too many characters with that name.")


def list_characters() -> List[CharacterInfo]:
    """Every installed character, bundled ones first."""
    builtin_root = os.path.abspath(characters_dir())
    infos: List[CharacterInfo] = []
    for name, directory in discover_characters().items():
        pack = CharacterPack.load(directory)
        parts_dir = os.path.join(directory, "parts")
        part_count = 0
        if os.path.isdir(parts_dir):
            part_count = len([f for f in os.listdir(parts_dir) if f.endswith(".png")])
        infos.append(
            CharacterInfo(
                name=name,
                directory=directory,
                builtin=os.path.abspath(directory).startswith(builtin_root),
                render_mode=str(pack.render.get("mode", "auto")),
                has_texture=pack.has_texture,
                part_count=part_count,
                author=pack.author,
            )
        )
    infos.sort(key=lambda i: (not i.builtin, i.name.lower()))
    return infos


def import_character(
    image_path: str,
    name: str,
    method: str = "auto_humanoid",
    scale: float = 1.0,
) -> CharacterInfo:
    """Create a character pack from ``image_path``.

    Extracts body parts, caches them, writes ``character.json`` and returns the
    new library entry. Raises :class:`CharacterError` with a user-facing message
    on any problem, so the dialog can just show ``str(exc)``.
    """
    if not image_path or not os.path.exists(image_path):
        raise CharacterError("That image file could not be found.")
    if os.path.splitext(image_path)[1].lower() not in SUPPORTED_IMAGE_EXTENSIONS:
        raise CharacterError(
            "Unsupported image type. Use PNG, WEBP, JPG, BMP or GIF "
            "(a PNG with a transparent background works best)."
        )

    try:
        from PIL import Image
    except Exception as exc:  # pragma: no cover - Pillow is a hard dependency
        raise CharacterError(f"Pillow is required to import characters: {exc}")

    from .rig import extractor

    safe = unique_name(sanitize_name(name))
    directory = os.path.join(user_characters_dir(), safe)

    try:
        image = Image.open(image_path)
        image.load()
        image = image.convert("RGBA")
    except Exception as exc:
        raise CharacterError(f"That image could not be opened: {exc}")

    if image.width < 24 or image.height < 24:
        raise CharacterError("That image is too small to cut into body parts.")

    # Very large images waste memory and slow extraction; a desktop pet never
    # needs more than ~1200px tall.
    if image.height > 1200:
        ratio = 1200 / image.height
        image = image.resize((max(1, int(image.width * ratio)), 1200), Image.LANCZOS)

    try:
        result = extractor.extract(image, method=method)
    except Exception as exc:
        raise CharacterError(f"Body-part extraction failed: {exc}")

    if not result.parts:
        raise CharacterError("No body parts could be extracted from that image.")

    os.makedirs(directory, exist_ok=True)
    try:
        image.save(os.path.join(directory, "texture.png"))
        extractor.save_parts(result, os.path.join(directory, "parts"))
        pack = CharacterPack(
            name=safe,
            directory=directory,
            source_image="texture.png",
            scale=scale,
            extraction={"method": "regions", "regions": result.to_regions_dict()},
            skeleton=result.skeleton or [],
            render={"mode": "image"},
        )
        pack.save_manifest()
    except OSError as exc:
        shutil.rmtree(directory, ignore_errors=True)
        raise CharacterError(f"Could not write the character files: {exc}")

    for info in list_characters():
        if info.name == safe:
            return info
    raise CharacterError("The character was created but could not be loaded.")


def delete_character(name: str) -> None:
    """Remove a user character pack. Bundled characters cannot be deleted."""
    for info in list_characters():
        if info.name != name:
            continue
        if info.builtin:
            raise CharacterError(f"'{name}' is built in and cannot be deleted.")
        shutil.rmtree(info.directory, ignore_errors=True)
        return
    raise CharacterError(f"No character named '{name}'.")


def rename_character(name: str, new_name: str) -> CharacterInfo:
    """Rename a user character pack (folder + manifest)."""
    target = None
    for info in list_characters():
        if info.name == name:
            target = info
            break
    if target is None:
        raise CharacterError(f"No character named '{name}'.")
    if target.builtin:
        raise CharacterError(f"'{name}' is built in and cannot be renamed.")

    safe = sanitize_name(new_name)
    if safe == name:
        return target
    safe = unique_name(safe)
    new_dir = os.path.join(os.path.dirname(target.directory), safe)
    try:
        os.rename(target.directory, new_dir)
    except OSError as exc:
        raise CharacterError(f"Could not rename: {exc}")

    pack = CharacterPack.load(new_dir)
    pack.name = safe
    pack.directory = new_dir
    pack.save_manifest()
    for info in list_characters():
        if info.name == safe:
            return info
    raise CharacterError("Renamed, but the character could not be reloaded.")


def duplicate_character(name: str, new_name: Optional[str] = None) -> CharacterInfo:
    """Copy a character (handy for tweaking a built-in one)."""
    for info in list_characters():
        if info.name != name:
            continue
        safe = unique_name(sanitize_name(new_name or f"{name} copy"))
        new_dir = os.path.join(user_characters_dir(), safe)
        try:
            shutil.copytree(info.directory, new_dir)
        except OSError as exc:
            raise CharacterError(f"Could not copy the character: {exc}")
        pack = CharacterPack.load(new_dir)
        pack.name = safe
        pack.directory = new_dir
        pack.save_manifest()
        for created in list_characters():
            if created.name == safe:
                return created
    raise CharacterError(f"No character named '{name}'.")


def reextract_character(name: str, method: str) -> CharacterInfo:
    """Re-cut an existing character's parts with a different method."""
    for info in list_characters():
        if info.name != name:
            continue
        if info.builtin:
            raise CharacterError(f"'{name}' is built in; duplicate it first.")
        pack = CharacterPack.load(info.directory)
        if not pack.has_texture:
            raise CharacterError(f"'{name}' has no source image to re-extract.")
        return import_character(
            pack.source_path, f"{name} ({method})", method=method, scale=pack.scale
        )
    raise CharacterError(f"No character named '{name}'.")
