"""Configuration: global app settings plus per-character packs.

Two layers of customisation:

``AppConfig``
    User-level preferences (scale, physics feel, which behaviours are enabled,
    autonomy timing, window interaction, start-on-login, ...). Persisted as JSON
    under the OS config directory so it survives restarts.

``CharacterPack``
    A self-contained character: source image, how to extract its body sections,
    the skeleton, and any per-character behaviour overrides. Users make new pets
    by dropping a folder next to the app - no code required.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

APP_NAME = "DesktopPet"


# --------------------------------------------------------------------------- #
# Paths
# --------------------------------------------------------------------------- #
def config_dir() -> str:
    """Return the per-user configuration directory, creating it if needed."""
    if sys.platform.startswith("win"):
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
    elif sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    path = os.path.join(base, APP_NAME)
    os.makedirs(path, exist_ok=True)
    return path


def config_path() -> str:
    return os.path.join(config_dir(), "config.json")


def bundled_assets_dir() -> str:
    """Locate the bundled ``assets`` directory in dev and frozen builds."""
    if getattr(sys, "frozen", False):  # PyInstaller onefile/onedir
        base = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
        return os.path.join(base, "assets")
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(os.path.dirname(os.path.dirname(here)), "assets")


def characters_dir() -> str:
    return os.path.join(bundled_assets_dir(), "characters")


def user_characters_dir() -> str:
    path = os.path.join(config_dir(), "characters")
    os.makedirs(path, exist_ok=True)
    return path


# --------------------------------------------------------------------------- #
# App configuration
# --------------------------------------------------------------------------- #
@dataclass
class AppConfig:
    # Appearance / scale
    character: str = "default"
    scale: float = 1.0
    opacity: float = 1.0
    always_on_top: bool = True
    flip_with_direction: bool = True

    # Simulation feel
    fps: int = 60
    gravity: float = 2200.0
    walk_speed: float = 90.0
    run_speed: float = 240.0
    climb_speed: float = 70.0
    creep_speed: float = 55.0

    # Autonomy: how often the pet decides to do something new (seconds).
    autonomy_min: float = 4.0
    autonomy_max: float = 12.0
    autonomy_enabled: bool = True

    # Behaviour mode - the "personality" preset the autonomy brain runs under.
    #   "free"     : the default; wanders, climbs windows, naps, does its thing
    #   "mischief" : strongly prefers climbing/creeping over your windows
    #   "calm"     : mostly stays put, gentle idling only
    #   "follow"   : sticks close to the mouse cursor
    mode: str = "free"

    # Chance (0..1) that bumping into a window edge starts a climb.
    climb_chance: float = 0.75

    # Interaction
    interact_with_windows: bool = True
    follow_cursor: bool = False
    gravity_enabled: bool = True
    draggable: bool = True
    throwable: bool = True

    # Which behaviours the autonomy brain may pick from.
    enabled_behaviors: List[str] = field(
        default_factory=lambda: [
            "idle",
            "walk",
            "run",
            "climb",
            "creep",
            "sit",
            "sleep",
            "wave",
            "cheer",
            "chase_cursor",
        ]
    )

    # Virtual-pet stats (Tamagotchi-style). Set enabled False to ignore.
    stats_enabled: bool = True
    stat_decay_per_min: float = 1.5

    # Extras
    sound_enabled: bool = False
    start_on_login: bool = False
    show_speech_bubbles: bool = True
    pet_count: int = 1

    # Platform backend override: "auto", "windows" or "null".
    backend: str = "auto"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AppConfig":
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        filtered = {k: v for k, v in data.items() if k in known}
        return cls(**filtered)

    def save(self, path: Optional[str] = None) -> None:
        path = path or config_path()
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self.to_dict(), fh, indent=2)

    @classmethod
    def load(cls, path: Optional[str] = None) -> "AppConfig":
        path = path or config_path()
        if not os.path.exists(path):
            cfg = cls()
            cfg.save(path)
            return cfg
        try:
            with open(path, "r", encoding="utf-8") as fh:
                return cls.from_dict(json.load(fh))
        except (json.JSONDecodeError, OSError):
            return cls()


# --------------------------------------------------------------------------- #
# Character packs
# --------------------------------------------------------------------------- #
@dataclass
class CharacterPack:
    name: str
    directory: str
    source_image: str = "texture.png"
    scale: float = 1.0
    extraction: Dict[str, Any] = field(default_factory=lambda: {"method": "auto_humanoid"})
    skeleton: List[Dict[str, Any]] = field(default_factory=list)
    poses: Dict[str, Any] = field(default_factory=dict)
    behavior_overrides: Dict[str, Any] = field(default_factory=dict)
    # ``render`` controls how the pet is drawn:
    #   {"mode": "shapes", "palette": {...}}  -> procedural, no art needed
    #   {"mode": "image"}                     -> use extracted part sprites
    #   {"mode": "auto"}                      -> image if a texture exists, else shapes
    render: Dict[str, Any] = field(default_factory=lambda: {"mode": "auto"})
    author: str = ""
    version: str = "1.0"

    @property
    def has_texture(self) -> bool:
        import os as _os

        return _os.path.exists(self.source_path)

    @property
    def source_path(self) -> str:
        return os.path.join(self.directory, self.source_image)

    @property
    def parts_dir(self) -> str:
        return os.path.join(self.directory, "parts")

    @classmethod
    def load(cls, directory: str) -> "CharacterPack":
        manifest = os.path.join(directory, "character.json")
        data: Dict[str, Any] = {}
        if os.path.exists(manifest):
            with open(manifest, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        return cls(
            name=data.get("name", os.path.basename(directory)),
            directory=directory,
            source_image=data.get("source_image", "texture.png"),
            scale=float(data.get("scale", 1.0)),
            extraction=data.get("extraction", {"method": "auto_humanoid"}),
            skeleton=data.get("skeleton", []),
            poses=data.get("poses", {}),
            behavior_overrides=data.get("behaviors", {}),
            render=data.get("render", {"mode": "auto"}),
            author=data.get("author", ""),
            version=str(data.get("version", "1.0")),
        )

    def save_manifest(self) -> None:
        manifest = os.path.join(self.directory, "character.json")
        payload = {
            "name": self.name,
            "author": self.author,
            "version": self.version,
            "source_image": self.source_image,
            "scale": self.scale,
            "extraction": self.extraction,
            "skeleton": self.skeleton,
            "poses": self.poses,
            "behaviors": self.behavior_overrides,
            "render": self.render,
        }
        os.makedirs(self.directory, exist_ok=True)
        with open(manifest, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)


def discover_characters() -> Dict[str, str]:
    """Map character name -> directory across bundled and user packs."""
    found: Dict[str, str] = {}
    for root in (characters_dir(), user_characters_dir()):
        if not os.path.isdir(root):
            continue
        for entry in sorted(os.listdir(root)):
            path = os.path.join(root, entry)
            if os.path.isdir(path):
                found[entry] = path
    return found


def resolve_character(name: str) -> Optional[str]:
    return discover_characters().get(name)
