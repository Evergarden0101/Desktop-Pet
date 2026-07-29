"""One pet: a small shaped always-on-top window that crawls around."""

from __future__ import annotations

import random
from enum import Enum

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QBitmap, QCursor, QPainter
from PySide6.QtWidgets import QMenu, QMessageBox, QWidget

from .assets import PetAssets
from .bubble import SpeechBubble
from .obstacles import Terrain


class State(Enum):
    CRAWL = "crawl"
    PLAY = "play"
    FALL = "fall"
    DRAG = "drag"
    CLIMB = "climb"


CLIMB_SPEED = 130.0     # pixels per second while pulling up onto a ledge
TURN_CHANCE = 0.72      # at a ledge end: turn around rather than walk off


class Pet(QWidget):
    def __init__(self, assets: PetAssets, app, x: float, y: float):
        super().__init__(None)
        self.assets = assets
        self.app = app
        self.strings = app.strings
        self.cfg = app.cfg

        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
                            | Qt.Tool | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setMouseTracking(True)
        self.resize(*assets.size)

        self.x = float(x)
        self.y = float(y)
        self.facing_right = random.random() < 0.5
        self.state = State.CRAWL
        self.vy = 0.0
        self.climb_target = 0.0
        self.play_left = 0.0

        self.anim_name = "crawl"
        self.frame_index = 0
        self._frame_clock = 0.0
        self._mask_cache: dict[tuple[str, int, bool], QBitmap] = {}
        self._drag_offset = QPoint()

        self.bubble = SpeechBubble()

        self._apply_frame()
        self.move(int(self.x), int(self.y))

    # -- helpers ----------------------------------------------------------

    @property
    def anim(self):
        return self.assets.anims[self.anim_name]

    @property
    def center_x(self) -> float:
        return self.x + self.width() / 2.0

    @property
    def bottom(self) -> float:
        return self.y + self.height()

    def head_point(self) -> QPoint:
        head = self.anim.head(self.frame_index, self.facing_right)
        return QPoint(int(self.x + head.x()), int(self.y + head.y()))

    def set_anim(self, name: str) -> None:
        if name != self.anim_name and name in self.assets.anims:
            self.anim_name = name
            self.frame_index = 0
            self._frame_clock = 0.0

    def set_assets(self, assets: PetAssets) -> None:
        """Swap in rebuilt or rescaled sprites without moving the pet.

        Her feet stay where they were, so a size change does not leave her
        hovering above the ledge or sunk into it.
        """
        feet = self.bottom
        self.assets = assets
        if self.anim_name not in assets.anims:
            self.anim_name = "crawl"
        self.frame_index = 0
        self._frame_clock = 0.0
        self._mask_cache.clear()
        self.resize(*assets.size)
        self.y = feet - self.height()
        self._apply_frame()
        self.move(int(self.x), int(self.y))

    # -- simulation -------------------------------------------------------

    def tick(self, dt: float, terrain: Terrain) -> None:
        if self.state is State.DRAG:
            self._advance_frame(dt)
            self.bubble.follow(self.head_point())
            return

        if self.state is State.FALL:
            self._tick_fall(dt, terrain)
        elif self.state is State.CLIMB:
            self._tick_climb(dt, terrain)
        elif self.state is State.PLAY:
            self.play_left -= dt
            if self.play_left <= 0:
                self.state = State.CRAWL
                self.set_anim("crawl")
        else:
            self._tick_crawl(dt, terrain)

        self._advance_frame(dt)
        self.move(int(self.x), int(self.y))
        self.bubble.follow(self.head_point())

    def _tick_fall(self, dt: float, terrain: Terrain) -> None:
        self.set_anim("crawl")
        self.vy += self.cfg.fall_gravity * dt
        previous_bottom = self.bottom
        self.y += self.vy * dt

        landing = None
        for ledge in terrain.ledges:
            if not ledge.contains(self.center_x):
                continue
            if previous_bottom - 2 <= ledge.y <= self.bottom:
                if landing is None or ledge.y < landing.y:
                    landing = ledge
        if landing is not None:
            self.y = landing.y - self.height()
            self.vy = 0.0
            self.state = State.CRAWL
            return

        # fell past everything: put her back on the work-area floor
        if self.y > terrain.floor.bottom() + 200:
            self.y = terrain.floor.bottom() - self.height()
            self.vy = 0.0
            self.state = State.CRAWL

    def _tick_climb(self, dt: float, terrain: Terrain) -> None:
        self.set_anim("crawl")
        self.y -= CLIMB_SPEED * dt
        if self.bottom <= self.climb_target:
            self.y = self.climb_target - self.height()
            # step over the lip so she is standing on the ledge, not beside it
            self.x += (1 if self.facing_right else -1) * self.width() * 0.30
            self.state = State.CRAWL

    def _tick_crawl(self, dt: float, terrain: Terrain) -> None:
        self.set_anim("crawl")

        if random.random() < self.cfg.play_chance:
            self.state = State.PLAY
            self.play_left = self.cfg.play_seconds
            self.set_anim("play")
            return

        direction = 1 if self.facing_right else -1
        step = self.cfg.speed * dt * direction

        standing = terrain.ledge_at(self.center_x, self.bottom, tolerance=8.0)
        if standing is None:
            self.state = State.FALL
            self.vy = 0.0
            return

        # a window side in the way: climb it if it is low enough, else turn
        lead_x = self.center_x + direction * (self.width() * 0.34 + 6)
        wall = terrain.blocking_wall(lead_x, self.bottom)
        if wall is not None:
            rise = self.bottom - wall.top()
            if 0 < rise <= self.height() * self.cfg.climb_height:
                self.state = State.CLIMB
                self.climb_target = float(wall.top())
                return
            self.facing_right = not self.facing_right
            return

        next_center = self.center_x + step
        if not standing.contains(next_center):
            if random.random() < TURN_CHANCE:
                self.facing_right = not self.facing_right
                return
            # walk off the edge on purpose
            self.x += step
            self.state = State.FALL
            self.vy = 0.0
            return

        # never crawl off the side of the desktop
        floor = terrain.floor
        if next_center < floor.left() + 8 or next_center > floor.right() - 8:
            self.facing_right = not self.facing_right
            return

        self.x += step

    def _advance_frame(self, dt: float) -> None:
        anim = self.anim
        self._frame_clock += dt
        interval = 1.0 / max(1, anim.fps)
        while self._frame_clock >= interval:
            self._frame_clock -= interval
            self.frame_index = (self.frame_index + 1) % len(anim)
        self._apply_frame()

    def _apply_frame(self) -> None:
        key = (self.anim_name, self.frame_index % len(self.anim), self.facing_right)
        mask = self._mask_cache.get(key)
        if mask is None:
            mask = self.anim.frame(self.frame_index, self.facing_right).mask()
            self._mask_cache[key] = mask
        # a shaped window means clicks land on the figure, not on her bounding box
        self.setMask(mask)
        self.update()

    # -- painting ---------------------------------------------------------

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        painter.drawPixmap(0, 0, self.anim.frame(self.frame_index, self.facing_right))

    # -- interaction ------------------------------------------------------

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.state = State.DRAG
            self.set_anim("play")
            self._drag_offset = event.globalPosition().toPoint() - self.pos()
            event.accept()

    def mouseMoveEvent(self, event) -> None:
        if self.state is State.DRAG:
            target = event.globalPosition().toPoint() - self._drag_offset
            self.x, self.y = float(target.x()), float(target.y())
            self.move(target)
            self.bubble.follow(self.head_point())
            event.accept()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self.state is State.DRAG:
            self.state = State.FALL
            self.vy = 0.0
            self.set_anim("crawl")
            event.accept()

    def mouseDoubleClickEvent(self, event) -> None:
        self.call_husband()

    def contextMenuEvent(self, event) -> None:
        menu = QMenu()
        s = self.strings

        call = menu.addAction(s["call_husband"])
        call.triggered.connect(self.call_husband)
        menu.setDefaultAction(call)

        menu.addAction(s["headpat"]).triggered.connect(self.headpat)
        menu.addAction(s["come_here"]).triggered.connect(self.come_here)
        menu.addSeparator()

        label = s["resume"] if self.app.paused else s["pause"]
        menu.addAction(label).triggered.connect(self.app.toggle_pause)
        menu.addAction(s["reset"]).triggered.connect(self.send_to_floor)
        menu.addSeparator()

        menu.addAction(s["add_pet"]).triggered.connect(self.app.spawn_random)
        menu.addAction(s["remove_pet"]).triggered.connect(lambda: self.app.remove(self))
        menu.addSeparator()

        menu.addAction(s["manager"]).triggered.connect(self.app.open_manager)

        menu.addAction(s["about"]).triggered.connect(self.show_about)
        menu.addAction(s["quit"]).triggered.connect(self.app.quit)

        menu.exec(event.globalPos())
        event.accept()

    # -- menu actions -----------------------------------------------------

    def say(self, text: str) -> None:
        """Pop the bubble beside her head, on whichever side has more room."""
        head = self.head_point()
        self.bubble.show_text(text, head, self.cfg.bubble_seconds,
                              prefer_right=self.facing_right)

    def call_husband(self) -> None:
        self.say(self.strings.husband())
        self.state = State.PLAY
        self.play_left = max(self.cfg.play_seconds, self.cfg.bubble_seconds)
        self.set_anim("play")
        self.app.echo_husband(self)

    def headpat(self) -> None:
        self.say(self.strings.headpat())
        self.state = State.PLAY
        self.play_left = self.cfg.play_seconds
        self.set_anim("play")

    def come_here(self) -> None:
        pos = QCursor.pos()
        self.x = float(pos.x() - self.width() / 2)
        self.y = float(pos.y() - self.height())
        self.move(int(self.x), int(self.y))
        self.state = State.FALL
        self.vy = 0.0

    def send_to_floor(self) -> None:
        floor = self.app.terrain.floor
        self.x = float(random.randint(floor.left() + 20, max(floor.left() + 21,
                                                             floor.right() - self.width() - 20)))
        self.y = float(floor.bottom() - self.height())
        self.state = State.CRAWL
        self.move(int(self.x), int(self.y))

    def show_about(self) -> None:
        QMessageBox.information(None, self.strings["tray"], self.strings["about_text"])

    def closeEvent(self, event) -> None:
        self.bubble.close()
        super().closeEvent(event)
