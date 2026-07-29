"""Application bootstrap: create the Qt app and run the pet.

Kept tiny on purpose - all the real logic lives in
:class:`desktop_pet.ui.controller.PetApp`. Importing PySide6 is deferred to
:func:`run` so the non-GUI CLI commands (``extract``, ``list``) work on machines
without a display server.
"""

from __future__ import annotations

import os
import sys

from .config import AppConfig


def _configure_high_dpi() -> None:
    """Keep Qt's coordinate system in *physical* pixels, matching Win32.

    The desktop snapshot (window rects, taskbar, monitors, cursor) comes from
    the Win32 API in physical pixels. Qt 6 normally applies per-monitor DPI
    scaling, which makes widget geometry/painting *logical* - so on a display
    scaled above 100% (the Windows default on most laptops) everything the pet
    is anchored to shifts: the floor at physical y=1032 is drawn at logical
    y=1032 = 1290+ physical, i.e. below the visible screen, and the pet never
    appears. Disabling Qt's scaling makes both worlds share one unit.

    Must run before the QApplication is created. Set DESKTOP_PET_QT_SCALING=1
    to keep Qt's scaling (escape hatch for debugging).
    """
    if os.environ.get("DESKTOP_PET_QT_SCALING") == "1":
        return
    os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "0"
    os.environ.setdefault("QT_SCALE_FACTOR_ROUNDING_POLICY", "PassThrough")


def _require_pyside() -> None:
    try:
        import PySide6  # noqa: F401
    except Exception as exc:  # pragma: no cover - environment dependent
        raise SystemExit(
            "PySide6 is required to run the desktop pet GUI.\n"
            "Install it with:  pip install PySide6\n"
            f"(import error: {exc})"
        )


def run(config: AppConfig | None = None) -> int:
    """Launch the desktop pet. Returns the Qt exit code."""
    _configure_high_dpi()
    _require_pyside()

    from PySide6.QtWidgets import QApplication

    from .ui import errors
    from .ui.controller import PetApp
    from .ui.icon import make_app_icon

    # Before anything else, make failures leave a trace: a windowed build has
    # no stdout or stderr at all, so without this both Python tracebacks and
    # anything a native library says on its way down are simply lost.
    errors.capture_output()
    errors.install()

    config = config or AppConfig.load()

    qapp = QApplication.instance() or QApplication(sys.argv)
    qapp.setApplicationName("Desktop Pet")
    qapp.setApplicationDisplayName("Desktop Pet")
    # The tray icon keeps the app alive even with no visible top-level window.
    qapp.setQuitOnLastWindowClosed(False)
    qapp.setWindowIcon(make_app_icon())

    app = PetApp(config, qapp)
    app.overlay.setWindowOpacity(config.opacity)
    app.start()
    return qapp.exec()
