"""The desktop as terrain.

Every visible top-level window contributes a *ledge* (its title-bar edge, which
the pets crawl along) and two *walls* (its left and right sides, which stop
them).  The bottom of the work area is the floor.

Window enumeration is Win32-only.  On other platforms the pets still crawl,
they just have the screen floor to themselves -- which keeps the app testable
on Linux and macOS.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass

from PySide6.QtCore import QRect
from PySide6.QtGui import QGuiApplication

IS_WINDOWS = sys.platform == "win32"

# window classes that are the desktop itself, or shells we must not stand on
_SKIP_CLASSES = {
    "Progman", "WorkerW", "Shell_TrayWnd", "Button", "SysShadow",
    "Windows.UI.Core.CoreWindow", "ApplicationManager_DesktopShellWindow",
    "MultitaskingViewFrame", "ForegroundStaging", "XamlExplorerHostIslandWindow",
}


@dataclass(frozen=True)
class Ledge:
    """A horizontal surface a pet can crawl along."""
    y: float
    x0: float
    x1: float

    def contains(self, x: float) -> bool:
        return self.x0 <= x <= self.x1


@dataclass
class Terrain:
    ledges: list[Ledge]
    walls: list[QRect]      # full window rectangles, used for side collisions
    floor: QRect            # the work area (screen minus taskbar)

    def ledge_under(self, x: float, y: float, max_drop: float = 1e9) -> Ledge | None:
        """The highest surface strictly below ``y`` that spans ``x``."""
        best: Ledge | None = None
        for ledge in self.ledges:
            if not ledge.contains(x):
                continue
            if ledge.y < y - 1:
                continue
            if ledge.y - y > max_drop:
                continue
            if best is None or ledge.y < best.y:
                best = ledge
        return best

    def ledge_at(self, x: float, y: float, tolerance: float = 6.0) -> Ledge | None:
        """The surface the pet is currently standing on, if any."""
        for ledge in self.ledges:
            if ledge.contains(x) and abs(ledge.y - y) <= tolerance:
                return ledge
        return None

    def blocking_wall(self, lead_x: float, bottom: float) -> QRect | None:
        """The window the pet's leading foot is about to walk into, if any.

        The probe sits just above the pet's feet, so a pet standing *on* a
        window's top edge is never blocked by that same window.
        """
        probe_y = bottom - 4
        for rect in self.walls:
            if (rect.left() <= lead_x <= rect.right()
                    and rect.top() <= probe_y <= rect.bottom()):
                return rect
        return None


# --------------------------------------------------------------------------
# Win32 window enumeration
# --------------------------------------------------------------------------

def _win32_rects(exclude: set[int]) -> list[tuple[int, int, int, int]]:
    import ctypes
    import ctypes.wintypes as wt

    user32 = ctypes.windll.user32
    dwmapi = ctypes.windll.dwmapi

    GWL_EXSTYLE = -20
    WS_EX_TOOLWINDOW = 0x00000080
    WS_EX_NOACTIVATE = 0x08000000
    DWMWA_CLOAKED = 14

    rects: list[tuple[int, int, int, int]] = []

    WNDENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)

    def callback(hwnd, _lparam):
        if int(hwnd) in exclude:
            return True
        if not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd):
            return True

        ex_style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        if ex_style & (WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE):
            return True

        length = user32.GetWindowTextLengthW(hwnd)
        if length == 0:
            return True

        cls = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, cls, 256)
        if cls.value in _SKIP_CLASSES:
            return True

        # UWP windows hang around invisibly; DWM knows they are cloaked
        cloaked = ctypes.c_int(0)
        if dwmapi.DwmGetWindowAttribute(hwnd, DWMWA_CLOAKED,
                                        ctypes.byref(cloaked),
                                        ctypes.sizeof(cloaked)) == 0 and cloaked.value:
            return True

        rect = wt.RECT()
        if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return True
        w, h = rect.right - rect.left, rect.bottom - rect.top
        if w < 120 or h < 80:
            return True
        rects.append((rect.left, rect.top, w, h))
        return True

    user32.EnumWindows(WNDENUMPROC(callback), 0)
    return rects


def enable_dpi_awareness() -> None:
    """Ask Windows for per-monitor DPI, so window rects and Qt agree."""
    if not IS_WINDOWS:
        return
    import ctypes

    try:
        # PER_MONITOR_AWARE_V2
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except (AttributeError, OSError):
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except (AttributeError, OSError):
            pass


def scan(exclude_handles: set[int], obey_windows: bool = True) -> Terrain:
    """Build the current terrain from the screens and the open windows."""
    screen = QGuiApplication.primaryScreen()
    floor = screen.availableGeometry() if screen else QRect(0, 0, 1280, 720)

    ledges: list[Ledge] = []
    walls: list[QRect] = []

    # every screen's work area contributes a floor
    for scr in QGuiApplication.screens():
        area = scr.availableGeometry()
        ledges.append(Ledge(float(area.bottom()), float(area.left()),
                            float(area.right())))

    if obey_windows and IS_WINDOWS:
        try:
            raw = _win32_rects(exclude_handles)
        except (OSError, AttributeError):
            raw = []
        dpr = screen.devicePixelRatio() if screen else 1.0
        for x, y, w, h in raw:
            rect = QRect(int(x / dpr), int(y / dpr), int(w / dpr), int(h / dpr))
            if not rect.intersects(floor):
                continue
            walls.append(rect)
            ledges.append(Ledge(float(rect.top()), float(rect.left()),
                                float(rect.right())))

    return Terrain(ledges=ledges, walls=walls, floor=floor)
