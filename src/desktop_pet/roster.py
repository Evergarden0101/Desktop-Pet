"""Which characters exist, what they are called, and which are on the desktop.

Kept separate from the generated ``meta.json`` files so that rebuilding a
character's frames never loses the name you gave her.
"""

from __future__ import annotations

import json
from pathlib import Path


class Roster:
    def __init__(self, path: Path):
        self.path = path
        self._data: dict[str, dict] = {}
        self.reload()

    def reload(self) -> None:
        if self.path.exists():
            try:
                loaded = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    self._data = {k: v for k, v in loaded.items() if isinstance(v, dict)}
            except (OSError, ValueError):
                self._data = {}

    def save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self._data, ensure_ascii=False, indent=2),
                                 encoding="utf-8")
        except OSError:
            pass

    def _entry(self, key: str) -> dict:
        return self._data.setdefault(key, {})

    def display_name(self, key: str) -> str:
        return self._entry(key).get("name") or key

    def set_display_name(self, key: str, name: str) -> None:
        name = name.strip()
        if name and name != key:
            self._entry(key)["name"] = name
        else:
            self._entry(key).pop("name", None)
        self.save()

    def enabled(self, key: str) -> bool:
        return bool(self._entry(key).get("enabled", True))

    def set_enabled(self, key: str, value: bool) -> None:
        self._entry(key)["enabled"] = bool(value)
        self.save()

    def forget(self, key: str) -> None:
        self._data.pop(key, None)
        self.save()
