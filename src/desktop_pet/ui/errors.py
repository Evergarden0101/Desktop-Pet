"""Keep an unexpected error from taking the whole app down.

PySide6 does not let a Python exception escape a slot quietly: since Qt 6.5 an
unhandled exception inside a signal handler calls ``qFatal``, which aborts the
process. To the user that is indistinguishable from a crash - the pet simply
vanishes mid-click, with nothing written down anywhere.

So two things live here:

* :func:`install` - a global ``sys.excepthook`` that records the traceback and
  keeps going, so nothing reaches Qt's fatal path.
* :func:`guard` - a decorator for widget callbacks. It shows the user what went
  wrong and where the log is, then returns normally.

Both append to a single log file in the config directory, which is the first
thing to ask for in a bug report.
"""

from __future__ import annotations

import functools
import os
import sys
import traceback
from datetime import datetime
from typing import Callable, Optional

_LOG_NAME = "errors.log"
_SESSION_LOG = "session.log"
#: Start a new session log once the old one passes this size.
_MAX_LOG_BYTES = 1_000_000
_installed = False


def log_path() -> str:
    from ..config import config_dir

    return os.path.join(config_dir(), _LOG_NAME)


def session_log_path() -> str:
    from ..config import config_dir

    return os.path.join(config_dir(), _SESSION_LOG)


def _needs_capture() -> bool:
    """True when this process has nowhere to write diagnostics."""
    if not getattr(sys, "frozen", False):
        return False
    for stream in (sys.stdout, sys.stderr):
        if stream is None:
            return True
        try:
            if stream.fileno() < 0:
                return True
        except Exception:
            return True
    return False


def capture_output() -> Optional[str]:
    """Give a windowed build somewhere to write, and return the log path.

    A GUI PyInstaller build starts with ``sys.stdout``/``sys.stderr`` set to
    ``None`` and file descriptors 1 and 2 closed. Python shrugs that off, but
    everything the app and its *native* libraries would have said is discarded
    - which is why a failure inside MediaPipe leaves no trace at all. Pointing
    the Python objects and the underlying descriptors at a file gives native
    code a valid handle to write to, and leaves us its last words if it dies.
    """
    if not _needs_capture():
        return None
    try:
        path = session_log_path()
        if os.path.exists(path) and os.path.getsize(path) > _MAX_LOG_BYTES:
            os.replace(path, path + ".1")
        handle = open(path, "a", buffering=1, encoding="utf-8", errors="replace")
    except Exception:
        return None

    try:
        from .. import __version__

        handle.write(
            f"\n=== {datetime.now().isoformat(timespec='seconds')} "
            f"desktop-pet {__version__} started ===\n"
        )
        sys.stdout = handle
        sys.stderr = handle
        # Native libraries write to the descriptors, not to the Python objects.
        for fd in (1, 2):
            try:
                os.dup2(handle.fileno(), fd)
            except Exception:
                pass
        return path
    except Exception:
        return None


def record(context: str, exc: BaseException) -> str:
    """Append a traceback to the log. Returns the path, or "" if it couldn't."""
    text = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    try:
        from .. import __version__

        path = log_path()
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(
                f"\n=== {datetime.now().isoformat(timespec='seconds')} "
                f"desktop-pet {__version__} - {context} ===\n{text}"
            )
        return path
    except Exception:
        # Logging must never be the thing that fails; the console is enough.
        sys.stderr.write(f"[desktop-pet] {context}: {text}")
        return ""


def install() -> None:
    """Route unhandled exceptions to the log instead of Qt's fatal handler."""
    global _installed
    if _installed:
        return
    _installed = True

    previous = sys.excepthook

    def hook(kind, value, tb) -> None:
        if issubclass(kind, KeyboardInterrupt):
            previous(kind, value, tb)
            return
        value.__traceback__ = tb
        record("unhandled exception", value)

    sys.excepthook = hook


def guard(context: str, title: str = "Something went wrong") -> Callable:
    """Wrap a widget callback so a failure is reported, not fatal."""

    def decorate(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(self, *args, **kwargs):
            try:
                return func(self, *args, **kwargs)
            except Exception as exc:  # noqa: BLE001 - this is the safety net
                show(self, title, context, exc)
                return None

        return wrapper

    return decorate


def show(parent, title: str, context: str, exc: BaseException) -> None:
    """Log ``exc`` and tell the user, without letting the failure propagate."""
    path = record(context, exc)
    detail = f"{type(exc).__name__}: {exc}".strip()
    message = f"{context.capitalize()} failed.\n\n{detail}"
    if path:
        message += f"\n\nDetails were written to:\n{path}"
    try:
        from PySide6.QtWidgets import QMessageBox

        QMessageBox.warning(_widget(parent), title, message)
    except Exception:
        sys.stderr.write(message + "\n")


def _widget(candidate) -> Optional[object]:
    """Only pass a real widget to Qt as a dialog parent."""
    try:
        from PySide6.QtWidgets import QWidget

        return candidate if isinstance(candidate, QWidget) else None
    except Exception:
        return None
