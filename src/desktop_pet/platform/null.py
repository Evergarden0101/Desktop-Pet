"""A synthetic desktop backend for development, CI and tests.

On non-Windows machines (and in headless CI) there is no real desktop to query,
so this backend fabricates a plausible one: a single monitor with a bottom
taskbar and a couple of windows. Tests can also drive it directly by mutating
:attr:`NullBackend.windows` to script window movements.
"""

from __future__ import annotations

from typing import List

from ..core.geometry import Rect, Vec2
from .base import DesktopSnapshot, Monitor, PlatformBackend, WindowInfo


class NullBackend(PlatformBackend):
    name = "null"

    def __init__(
        self,
        width: int = 1920,
        height: int = 1080,
        taskbar_height: int = 48,
    ):
        self.width = width
        self.height = height
        self.taskbar_height = taskbar_height
        self.cursor = Vec2(width / 2, height / 2)
        self.windows: List[WindowInfo] = [
            WindowInfo(
                handle=1,
                title="Sample Editor",
                rect=Rect(300, 200, 700, 480),
                is_foreground=True,
                process="editor",
            ),
            WindowInfo(
                handle=2,
                title="Browser",
                rect=Rect(1050, 120, 620, 700),
                process="browser",
            ),
        ]

    def _monitor(self) -> Monitor:
        bounds = Rect(0, 0, self.width, self.height)
        work = Rect(0, 0, self.width, self.height - self.taskbar_height)
        return Monitor(index=0, bounds=bounds, work_area=work, is_primary=True)

    def _taskbar(self) -> Rect:
        return Rect(0, self.height - self.taskbar_height, self.width, self.taskbar_height)

    def snapshot(self) -> DesktopSnapshot:
        return DesktopSnapshot(
            monitors=[self._monitor()],
            windows=list(self.windows),
            cursor=self.cursor,
            taskbars=[self._taskbar()],
        )

    def cursor_position(self) -> Vec2:
        return self.cursor

    def supports_window_interaction(self) -> bool:
        return True
