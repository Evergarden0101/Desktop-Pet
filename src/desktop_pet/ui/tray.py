"""System-tray icon and its menu."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtWidgets import QSystemTrayIcon

from .icon import make_app_icon
from .menu import build_pet_menu

if TYPE_CHECKING:  # pragma: no cover
    from .controller import PetApp


class PetTray(QSystemTrayIcon):
    def __init__(self, app: "PetApp"):
        super().__init__(make_app_icon())
        self.app = app
        self.setToolTip("Desktop Pet")
        self._menu = build_pet_menu(app, pet=None)
        self.setContextMenu(self._menu)
        self.activated.connect(self._on_activated)

    def _on_activated(self, reason) -> None:
        # Double-clicking the tray icon summons the pets to the main screen -
        # the quickest recovery if they've wandered somewhere invisible.
        if reason == QSystemTrayIcon.DoubleClick and self.app.pets:
            self.app.summon()

    def rebuild_menu(self) -> None:
        self._menu = build_pet_menu(self.app, pet=None)
        self.setContextMenu(self._menu)
