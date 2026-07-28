"""Start-on-login registration.

On Windows this writes an entry under ``HKCU\\...\\Run`` using the stdlib
``winreg`` module (no extra dependency). On other platforms it is a safe no-op
so the settings UI works everywhere.
"""

from __future__ import annotations

import sys

_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_VALUE_NAME = "DesktopPet"


def _launch_command() -> str:
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    # Dev mode: relaunch via the interpreter and module.
    return f'"{sys.executable}" -m desktop_pet'


def set_start_on_login(enabled: bool) -> bool:
    """Enable/disable launching at login. Returns True on success."""
    if not sys.platform.startswith("win"):
        return False
    try:  # pragma: no cover - Windows-only
        import winreg

        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE
        )
        try:
            if enabled:
                winreg.SetValueEx(
                    key, _VALUE_NAME, 0, winreg.REG_SZ, _launch_command()
                )
            else:
                try:
                    winreg.DeleteValue(key, _VALUE_NAME)
                except FileNotFoundError:
                    pass
        finally:
            winreg.CloseKey(key)
        return True
    except OSError:
        return False


def is_start_on_login() -> bool:
    if not sys.platform.startswith("win"):
        return False
    try:  # pragma: no cover - Windows-only
        import winreg

        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_READ)
        try:
            winreg.QueryValueEx(key, _VALUE_NAME)
            return True
        except FileNotFoundError:
            return False
        finally:
            winreg.CloseKey(key)
    except OSError:
        return False
