"""Windows desktop backend built on the Win32 API via ``ctypes``.

Using ``ctypes`` (standard library) instead of ``pywin32`` keeps the frozen
executable small and removes a native build dependency. Everything here is
guarded so importing the module on a non-Windows box (for linting/testing)
degrades gracefully - :func:`desktop_pet.platform.base.get_backend` only picks
this backend when ``sys.platform`` is Windows.
"""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes
from typing import List

from ..core.geometry import Rect, Vec2
from .base import DesktopSnapshot, Monitor, PlatformBackend, WindowInfo

_IS_WINDOWS = sys.platform.startswith("win")

if _IS_WINDOWS:  # pragma: no cover - Windows-only
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    dwmapi = ctypes.windll.dwmapi

    # Make coordinate queries DPI-correct across mixed-DPI monitor setups.
    try:
        # Per-Monitor-v2 (Windows 10+). Value -4 is the context handle.
        user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except Exception:
        try:
            user32.SetProcessDPIAware()
        except Exception:
            pass

    WNDENUMPROC = ctypes.WINFUNCTYPE(
        wintypes.BOOL, wintypes.HWND, wintypes.LPARAM
    )
    MONITORENUMPROC = ctypes.WINFUNCTYPE(
        wintypes.BOOL,
        wintypes.HMONITOR,
        wintypes.HDC,
        ctypes.POINTER(wintypes.RECT),
        wintypes.LPARAM,
    )

    DWMWA_CLOAKED = 14
    GWL_EXSTYLE = -20
    WS_EX_TOOLWINDOW = 0x00000080
    WS_EX_APPWINDOW = 0x00040000
    MONITORINFOF_PRIMARY = 0x1

    class MONITORINFO(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("rcMonitor", wintypes.RECT),
            ("rcWork", wintypes.RECT),
            ("dwFlags", wintypes.DWORD),
        ]


def _rect_from_win(r: "wintypes.RECT") -> Rect:  # pragma: no cover - Windows-only
    return Rect.from_bounds(r.left, r.top, r.right, r.bottom)


class WindowsBackend(PlatformBackend):
    name = "windows"

    def __init__(self, own_hwnd: int = 0):
        if not _IS_WINDOWS:  # pragma: no cover
            raise RuntimeError("WindowsBackend is only available on Windows")
        self.own_hwnd = own_hwnd

    # ------------------------------------------------------------ internals
    def _is_real_window(self, hwnd) -> bool:  # pragma: no cover - Windows-only
        if not user32.IsWindowVisible(hwnd):
            return False
        if hwnd == self.own_hwnd:
            return False
        length = user32.GetWindowTextLengthW(hwnd)
        if length == 0:
            return False

        ex_style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        if ex_style & WS_EX_TOOLWINDOW and not (ex_style & WS_EX_APPWINDOW):
            return False

        # Skip windows the DWM has "cloaked" (e.g. background UWP apps).
        cloaked = wintypes.DWORD(0)
        dwmapi.DwmGetWindowAttribute(
            hwnd,
            DWMWA_CLOAKED,
            ctypes.byref(cloaked),
            ctypes.sizeof(cloaked),
        )
        if cloaked.value != 0:
            return False
        return True

    def _window_title(self, hwnd) -> str:  # pragma: no cover - Windows-only
        length = user32.GetWindowTextLengthW(hwnd) + 1
        buffer = ctypes.create_unicode_buffer(length)
        user32.GetWindowTextW(hwnd, buffer, length)
        return buffer.value

    def _enumerate_windows(self) -> List[WindowInfo]:  # pragma: no cover - Windows-only
        foreground = user32.GetForegroundWindow()
        results: List[WindowInfo] = []

        def callback(hwnd, _lparam):
            if not self._is_real_window(hwnd):
                return True
            rect = wintypes.RECT()
            if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                return True
            minimized = bool(user32.IsIconic(hwnd))
            results.append(
                WindowInfo(
                    handle=int(hwnd),
                    title=self._window_title(hwnd),
                    rect=_rect_from_win(rect),
                    is_foreground=(hwnd == foreground),
                    is_minimized=minimized,
                )
            )
            return True

        user32.EnumWindows(WNDENUMPROC(callback), 0)
        return results

    def _enumerate_monitors(self) -> List[Monitor]:  # pragma: no cover - Windows-only
        monitors: List[Monitor] = []

        def callback(hmonitor, _hdc, _lprect, _lparam):
            info = MONITORINFO()
            info.cbSize = ctypes.sizeof(MONITORINFO)
            if user32.GetMonitorInfoW(hmonitor, ctypes.byref(info)):
                monitors.append(
                    Monitor(
                        index=len(monitors),
                        bounds=_rect_from_win(info.rcMonitor),
                        work_area=_rect_from_win(info.rcWork),
                        is_primary=bool(info.dwFlags & MONITORINFOF_PRIMARY),
                    )
                )
            return True

        user32.EnumDisplayMonitors(0, 0, MONITORENUMPROC(callback), 0)
        return monitors

    def _taskbars(self, monitors: List[Monitor]) -> List[Rect]:  # pragma: no cover
        """Derive taskbar rectangles by diffing monitor bounds vs work area."""
        bars: List[Rect] = []
        for m in monitors:
            b, w = m.bounds, m.work_area
            if w.bottom < b.bottom:
                bars.append(Rect.from_bounds(b.left, w.bottom, b.right, b.bottom))
            elif w.top > b.top:
                bars.append(Rect.from_bounds(b.left, b.top, b.right, w.top))
            elif w.left > b.left:
                bars.append(Rect.from_bounds(b.left, b.top, w.left, b.bottom))
            elif w.right < b.right:
                bars.append(Rect.from_bounds(w.right, b.top, b.right, b.bottom))
        return bars

    # -------------------------------------------------------------- backend
    def cursor_position(self) -> Vec2:  # pragma: no cover - Windows-only
        point = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(point))
        return Vec2(point.x, point.y)

    def snapshot(self) -> DesktopSnapshot:  # pragma: no cover - Windows-only
        monitors = self._enumerate_monitors()
        return DesktopSnapshot(
            monitors=monitors,
            windows=self._enumerate_windows(),
            cursor=self.cursor_position(),
            taskbars=self._taskbars(monitors),
        )
