"""Tunables, and working out where the assets live."""

from __future__ import annotations

import json
import os
import shutil
import sys
from dataclasses import dataclass, asdict, fields
from pathlib import Path

_resolved_root: Path | None = None


def frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def bundled_root() -> Path:
    """The read-only assets shipped inside the exe (or the repo, in dev)."""
    if frozen():
        return Path(sys._MEIPASS) / "assets"  # type: ignore[attr-defined]
    return Path(__file__).resolve().parent.parent.parent / "assets"


def _writable(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".write-test"
        probe.write_text("", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


def asset_root() -> Path:
    """A writable assets folder.

    In dev this is just ``<repo>/assets``.  In a frozen build the bundle lives
    in a temp directory that is wiped on exit, so characters imported from the
    Character Manager would not survive a restart.  We therefore keep assets
    beside the exe -- or under LOCALAPPDATA when the exe sits somewhere
    read-only like Program Files -- and seed it from the bundle on first run.
    """
    global _resolved_root
    if _resolved_root is not None:
        return _resolved_root

    if not frozen():
        _resolved_root = bundled_root()
        return _resolved_root

    candidates = [Path(sys.executable).resolve().parent / "assets"]
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("XDG_DATA_HOME")
    candidates.append(Path(base or Path.home()) / "DesktopPet" / "assets")

    for candidate in candidates:
        if _writable(candidate):
            _seed_from_bundle(candidate)
            _resolved_root = candidate
            return _resolved_root

    _resolved_root = bundled_root()  # read-only, but at least the pets show up
    return _resolved_root


def _seed_from_bundle(dest: Path) -> None:
    """Copy the bundled characters across the first time we run."""
    src = bundled_root() / "pets"
    target = dest / "pets"
    if target.exists() and any(target.glob("*/meta.json")):
        return
    if not src.exists():
        return
    try:
        shutil.copytree(src, target, dirs_exist_ok=True)
    except OSError:
        pass


def pets_dir() -> Path:
    return asset_root() / "pets"


def config_path() -> Path:
    return asset_root() / "config.json"


@dataclass
class Config:
    scale: float = 0.42           # sprite scale relative to the generated frames
    speed: float = 62.0           # crawl speed, screen pixels per second
    fall_gravity: float = 1500.0  # pixels per second squared
    tick_ms: int = 33             # simulation + repaint interval
    window_scan_ms: int = 400     # how often to re-read window rectangles
    climb_height: float = 0.55    # ledges up to this fraction of pet height are climbable
    play_chance: float = 0.004    # chance per tick of stopping to play
    play_seconds: float = 3.0
    bubble_seconds: float = 3.5
    max_pets: int = 8
    language: str = "auto"        # "auto" | "zh" | "en"
    obey_window_edges: bool = True

    @classmethod
    def load(cls) -> "Config":
        cfg = cls()
        path = config_path()
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return cfg
            known = {f.name for f in fields(cls)}
            for key, value in data.items():
                if key in known:
                    setattr(cfg, key, value)
        return cfg

    def save(self) -> None:
        try:
            config_path().write_text(json.dumps(asdict(self), indent=2),
                                     encoding="utf-8")
        except OSError:
            pass
