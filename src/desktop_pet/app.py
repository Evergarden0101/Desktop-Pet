"""Application controller: owns the pets, the clock and the terrain scan."""

from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QSystemTrayIcon

from . import obstacles
from .assets import PetAssets, discover
from .config import Config, asset_root
from .obstacles import Terrain
from .pet import Pet
from .strings import Strings


class PetApp:
    def __init__(self, cfg: Config, pets_dir: Path, count: int | None):
        self.cfg = cfg
        self.strings = Strings(cfg.language)
        self.paused = False
        self.pets: list[Pet] = []

        self.assets: list[PetAssets] = discover(pets_dir, cfg.scale)
        if not self.assets:
            raise SystemExit(
                f"No pets found in {pets_dir}.\n"
                f"Run:  python tools/make_demo_figures.py && python tools/make_frames.py\n"
                f"or extract your own:  python tools/extract_figures.py <image>")

        self.terrain: Terrain = obstacles.scan(set(), cfg.obey_window_edges)

        wanted = count if count is not None else len(self.assets)
        wanted = max(1, min(wanted, cfg.max_pets))
        for i in range(wanted):
            self.spawn(self.assets[i % len(self.assets)])

        self.tray = self._build_tray()

        self.timer = QTimer()
        self.timer.timeout.connect(self._tick)
        self.timer.start(cfg.tick_ms)

        self.scan_timer = QTimer()
        self.scan_timer.timeout.connect(self._rescan)
        self.scan_timer.start(cfg.window_scan_ms)

    # -- pets -------------------------------------------------------------

    def spawn(self, assets: PetAssets) -> Pet:
        floor = self.terrain.floor
        span = max(1, floor.width() - assets.size[0] - 40)
        x = floor.left() + 20 + random.randint(0, span)
        y = floor.bottom() - assets.size[1]
        pet = Pet(assets, self, x, y)
        pet.show()
        self.pets.append(pet)
        return pet

    def spawn_random(self) -> None:
        if len(self.pets) >= self.cfg.max_pets:
            return
        self.spawn(random.choice(self.assets))

    def remove(self, pet: Pet) -> None:
        if pet in self.pets:
            self.pets.remove(pet)
            pet.close()
            pet.deleteLater()
        if not self.pets:
            self.quit()

    def echo_husband(self, origin: Pet) -> None:
        """The other pets answer a moment later, so they feel like a group."""
        others = [p for p in self.pets if p is not origin]
        for i, other in enumerate(others[:3]):
            delay = 450 + i * 380
            QTimer.singleShot(delay, lambda p=other: p.say(self.strings.husband()))

    # -- clock ------------------------------------------------------------

    def _tick(self) -> None:
        if self.paused:
            return
        dt = self.cfg.tick_ms / 1000.0
        for pet in list(self.pets):
            pet.tick(dt, self.terrain)

    def _rescan(self) -> None:
        if self.paused:
            return
        exclude = set()
        for pet in self.pets:
            exclude.add(int(pet.winId()))
            exclude.add(int(pet.bubble.winId()))
        self.terrain = obstacles.scan(exclude, self.cfg.obey_window_edges)

    def toggle_pause(self) -> None:
        self.paused = not self.paused

    # -- tray -------------------------------------------------------------

    def _build_tray(self) -> QSystemTrayIcon:
        icon = QIcon(self.assets[0].icon_pixmap())
        tray = QSystemTrayIcon(icon)
        tray.setToolTip(self.strings["tray"])

        menu = QMenu()
        menu.addAction(self.strings["call_husband"]).triggered.connect(
            self._tray_call_husband)
        menu.addAction(self.strings["add_pet"]).triggered.connect(self.spawn_random)
        menu.addAction(self.strings["reset"]).triggered.connect(self._reset_all)
        menu.addSeparator()
        menu.addAction(self.strings["pause"]).triggered.connect(self.toggle_pause)
        menu.addAction(self.strings["about"]).triggered.connect(self._about)
        menu.addSeparator()
        menu.addAction(self.strings["quit"]).triggered.connect(self.quit)
        tray.setContextMenu(menu)
        tray.show()
        return tray

    def _tray_call_husband(self) -> None:
        if self.pets:
            random.choice(self.pets).call_husband()

    def _reset_all(self) -> None:
        for pet in self.pets:
            pet.send_to_floor()

    def _about(self) -> None:
        QMessageBox.information(None, self.strings["tray"], self.strings["about_text"])

    def quit(self) -> None:
        self.timer.stop()
        self.scan_timer.stop()
        for pet in list(self.pets):
            pet.close()
        self.tray.hide()
        QApplication.quit()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="desktop-pet")
    parser.add_argument("--pets", default=None, help="folder of pet sprite folders")
    parser.add_argument("--scale", type=float, default=None, help="sprite scale")
    parser.add_argument("--count", type=int, default=None, help="how many pets to spawn")
    parser.add_argument("--lang", choices=["auto", "zh", "en"], default=None)
    parser.add_argument("--no-window-edges", action="store_true",
                        help="ignore application windows, crawl on the desktop floor only")
    args = parser.parse_args(argv)

    obstacles.enable_dpi_awareness()

    cfg = Config.load()
    if args.scale is not None:
        cfg.scale = args.scale
    if args.lang is not None:
        cfg.language = args.lang
    if args.no_window_edges:
        cfg.obey_window_edges = False

    QApplication.setAttribute(Qt.AA_DontShowIconsInMenus, False)
    app = QApplication(sys.argv[:1])
    app.setApplicationName("Desktop Pet")
    app.setQuitOnLastWindowClosed(False)

    pets_dir = Path(args.pets) if args.pets else asset_root() / "pets"
    PetApp(cfg, pets_dir, args.count)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
