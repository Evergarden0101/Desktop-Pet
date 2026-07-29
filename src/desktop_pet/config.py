"""Tunables, loaded from assets/config.json when present."""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict, fields
from pathlib import Path


def asset_root() -> Path:
    """Where the pet folders live, both in dev and inside a PyInstaller exe.

    A frozen build prefers an ``assets`` folder sitting next to the exe, so you
    can swap in newly extracted figures without rebuilding.  Otherwise it falls
    back to the copy bundled inside the exe.
    """
    import sys

    if getattr(sys, "frozen", False):  # bundled by PyInstaller
        external = Path(sys.executable).resolve().parent / "assets"
        if (external / "pets").is_dir():
            return external
        return Path(sys._MEIPASS) / "assets"  # type: ignore[attr-defined]
    return Path(__file__).resolve().parent.parent.parent / "assets"


def config_path() -> Path:
    """Settings live beside the exe, never inside the read-only bundle."""
    import sys

    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "desktop_pet.json"
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
        path = config_path()
        cfg = cls()
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
        path = config_path()
        try:
            path.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
        except OSError:
            pass
