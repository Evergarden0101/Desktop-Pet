"""Platform abstraction for querying the desktop.

The simulation never talks to the OS directly; it asks a :class:`PlatformBackend`
for the current monitors, open windows, cursor position and taskbar. This keeps
the physics/behaviour code portable and unit-testable: tests inject a
:class:`desktop_pet.platform.null.NullBackend` with a scripted desktop, while
Windows uses :class:`desktop_pet.platform.windows.WindowsBackend`.
"""

from __future__ import annotations

import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional

from ..core.geometry import Rect, Vec2


@dataclass
class WindowInfo:
    """A top-level application window."""

    handle: int
    title: str
    rect: Rect
    is_foreground: bool = False
    is_minimized: bool = False
    process: str = ""


@dataclass
class Monitor:
    """A physical display."""

    index: int
    bounds: Rect          # full monitor rectangle in virtual-desktop space
    work_area: Rect       # bounds minus taskbar/docks
    is_primary: bool = False


@dataclass
class DesktopSnapshot:
    """Everything the simulation needs about the desktop for one frame."""

    monitors: List[Monitor] = field(default_factory=list)
    windows: List[WindowInfo] = field(default_factory=list)
    cursor: Vec2 = field(default_factory=Vec2)
    taskbars: List[Rect] = field(default_factory=list)

    def virtual_bounds(self) -> Rect:
        if not self.monitors:
            return Rect(0, 0, 1920, 1080)
        left = min(m.bounds.left for m in self.monitors)
        top = min(m.bounds.top for m in self.monitors)
        right = max(m.bounds.right for m in self.monitors)
        bottom = max(m.bounds.bottom for m in self.monitors)
        return Rect.from_bounds(left, top, right, bottom)

    def primary(self) -> Optional[Monitor]:
        for m in self.monitors:
            if m.is_primary:
                return m
        return self.monitors[0] if self.monitors else None


class PlatformBackend(ABC):
    """Interface every OS backend implements."""

    name = "base"

    @abstractmethod
    def snapshot(self) -> DesktopSnapshot:
        """Return a fresh :class:`DesktopSnapshot`."""

    @abstractmethod
    def cursor_position(self) -> Vec2:
        """Return the current mouse position in virtual-desktop coordinates."""

    def supports_window_interaction(self) -> bool:
        """Whether real window edges are available to climb/sit on."""
        return True

    def foreground_title(self) -> str:
        snap = self.snapshot()
        for w in snap.windows:
            if w.is_foreground:
                return w.title
        return ""


def get_backend(prefer: Optional[str] = None) -> PlatformBackend:
    """Return the best backend for the current OS (or ``prefer`` if given)."""
    from .null import NullBackend

    if prefer == "null":
        return NullBackend()

    if prefer == "windows" or (prefer is None and sys.platform.startswith("win")):
        try:
            from .windows import WindowsBackend

            return WindowsBackend()
        except Exception:  # pragma: no cover - Windows-only path
            return NullBackend()

    # Non-Windows (development / CI): a synthetic desktop so the app still runs.
    return NullBackend()
