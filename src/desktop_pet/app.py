"""Application bootstrap: create the Qt app and run the pet.

Kept tiny on purpose - all the real logic lives in
:class:`desktop_pet.ui.controller.PetApp`. Importing PySide6 is deferred to
:func:`run` so the non-GUI CLI commands (``extract``, ``list``) work on machines
without a display server.
"""

from __future__ import annotations

import sys

from .config import AppConfig


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
    _require_pyside()

    from PySide6.QtWidgets import QApplication

    from .ui.controller import PetApp
    from .ui.icon import make_app_icon

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
