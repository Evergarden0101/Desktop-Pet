"""Build a ready-to-animate character from a :class:`CharacterPack`.

This is the glue between the on-disk pack (image + manifest) and the runtime
rig: it constructs the skeleton, runs body-part extraction when the character is
image-based, and caches the cut parts next to the pack so subsequent launches
are instant. It stays free of any GUI dependency - the UI converts the returned
PIL images into ``QPixmap`` itself.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Dict, Optional

from ..config import CharacterPack
from ..core.skeleton import Skeleton
from .body_parts import BodyPart, build_skeleton, default_skeleton, specs_from_json


@dataclass
class LoadedCharacter:
    skeleton: Skeleton
    parts: Dict[str, BodyPart] = field(default_factory=dict)
    render: Dict[str, object] = field(default_factory=lambda: {"mode": "shapes"})
    scale: float = 1.0
    #: Speech-bubble overrides from the pack (``behaviors.phrases``).
    phrases: Optional[Dict[str, list]] = None


def _build_skeleton(pack: CharacterPack, style: Optional[str]) -> Skeleton:
    if pack.skeleton:
        return build_skeleton(specs_from_json(pack.skeleton))
    return default_skeleton(style)


def _wants_images(pack: CharacterPack) -> bool:
    mode = pack.render.get("mode", "auto")
    if mode == "shapes":
        return False
    if mode == "image":
        return True
    return pack.has_texture  # auto


def load_character(
    pack: CharacterPack,
    use_cache: bool = True,
    default_style: Optional[str] = None,
) -> LoadedCharacter:
    """Build a runnable character.

    ``default_style`` is the user's preferred body style (``AppConfig.body_style``)
    and applies only when the pack doesn't pin one itself, so a character author
    can force "human" proportions while everyone else stays cute.
    """
    render = dict(pack.render)
    style = render.get("style") or default_style
    render["style"] = style
    skeleton = _build_skeleton(pack, style)
    parts: Dict[str, BodyPart] = {}

    if _wants_images(pack):
        parts = _load_or_extract_parts(pack, use_cache)
        if not parts:
            # No usable art: fall back to shapes so the pet still appears.
            render["mode"] = "shapes"

    phrases = pack.behavior_overrides.get("phrases") if pack.behavior_overrides else None
    return LoadedCharacter(
        skeleton=skeleton,
        parts=parts,
        render=render,
        scale=pack.scale,
        phrases=phrases if isinstance(phrases, dict) else None,
    )


def _load_or_extract_parts(pack: CharacterPack, use_cache: bool) -> Dict[str, BodyPart]:
    from . import extractor  # local import keeps Pillow optional at import time

    cache_dir = pack.parts_dir
    if use_cache and os.path.isdir(cache_dir) and os.listdir(cache_dir):
        cached = extractor.load_parts_from_dir(cache_dir)
        if cached:
            return cached

    if not pack.has_texture:
        return {}

    try:
        from PIL import Image
    except Exception:
        return {}

    image = Image.open(pack.source_path).convert("RGBA")
    method = pack.extraction.get("method", "auto_humanoid")
    kwargs = {k: v for k, v in pack.extraction.items() if k != "method"}
    result = extractor.extract(image, method=method, **kwargs)

    # Cache the cut parts for next time (best-effort).
    try:
        extractor.save_parts(result, cache_dir)
    except OSError:
        pass
    return result.parts


def load_character_by_name(name: str) -> Optional[LoadedCharacter]:
    from ..config import resolve_character

    directory = resolve_character(name)
    if directory is None:
        return None
    return load_character(CharacterPack.load(directory))
