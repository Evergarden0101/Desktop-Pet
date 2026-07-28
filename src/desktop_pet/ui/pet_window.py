"""The transparent, always-on-top overlay the pets live in.

A single frameless, per-pixel-translucent, tool-style window spans the whole
virtual desktop and paints every pet. To let normal clicks pass through the
empty regions (so the pet doesn't block the apps underneath), the window's input
mask is rebuilt every frame from the pets' bounding rectangles - only the pixels
around a pet actually receive mouse events.
"""

from __future__ import annotations

from typing import Callable, Dict, List, Optional

from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import QPainter, QRegion
from PySide6.QtWidgets import QWidget

from ..core.geometry import Rect, Vec2
from ..core.pet import Pet
from .renderer import PetRenderer

# Movement past this many pixels turns a press into a drag (vs. a poke).
_DRAG_THRESHOLD = 6.0


class PetOverlay(QWidget):
    context_requested = Signal(object, QPoint)  # (pet, global_pos)

    def __init__(self):
        super().__init__(None)
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
            | Qt.WindowDoesNotAcceptFocus
            | Qt.MaximizeUsingFullscreenGeometryHint
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WA_AlwaysStackOnTop, True)
        self.setMouseTracking(True)

        self.pets: List[Pet] = []
        self.renderers: Dict[int, PetRenderer] = {}
        self.origin = Vec2(0, 0)

        self._dragging: Optional[Pet] = None
        self._press_pos: Optional[Vec2] = None
        self._press_started_drag = False
        self.poke_callback: Optional[Callable[[Pet], None]] = None

    # ---------------------------------------------------------------- setup
    def set_pets(self, pets: List[Pet], renderers: Dict[int, PetRenderer]) -> None:
        self.pets = pets
        self.renderers = renderers

    def set_geometry_from_bounds(self, bounds: Rect) -> None:
        self.origin = Vec2(bounds.left, bounds.top)
        self.setGeometry(
            int(bounds.left), int(bounds.top), int(bounds.width), int(bounds.height)
        )

    # -------------------------------------------------------------- drawing
    def paintEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        painter = QPainter(self)
        painter.translate(-self.origin.x, -self.origin.y)
        for pet in self.pets:
            renderer = self.renderers.get(pet.pet_id)
            if renderer is not None:
                renderer.draw(painter, pet)
        painter.end()

    def refresh(self) -> None:
        """Repaint and rebuild the input mask for the current frame."""
        self._update_input_mask()
        self.update()

    def _update_input_mask(self) -> None:
        region = QRegion()
        for pet in self.pets:
            r = pet.bounding_rect()
            region += QRect(
                int(r.left - self.origin.x),
                int(r.top - self.origin.y),
                int(r.width),
                int(r.height),
            )
        # An empty mask would make the whole window click-through *and* hide it
        # on some platforms; guarantee at least a 1px sliver when pets exist.
        if region.isEmpty():
            region = QRegion(0, 0, 1, 1)
        self.setMask(region)

    # ---------------------------------------------------------------- input
    def _to_virtual(self, pos: QPoint) -> Vec2:
        return Vec2(pos.x() + self.origin.x, pos.y() + self.origin.y)

    def _pet_at(self, virtual: Vec2) -> Optional[Pet]:
        # Front-most pet wins (last drawn = last in list).
        for pet in reversed(self.pets):
            if pet.contains_point(virtual.x, virtual.y):
                return pet
        return None

    def mousePressEvent(self, event) -> None:  # noqa: N802
        virtual = self._to_virtual(event.position().toPoint())
        pet = self._pet_at(virtual)
        if pet is None:
            event.ignore()
            return
        if event.button() == Qt.RightButton:
            self.context_requested.emit(pet, event.globalPosition().toPoint())
            return
        if event.button() == Qt.LeftButton:
            self._dragging = pet
            self._press_pos = virtual
            self._press_started_drag = False

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._dragging is None or self._press_pos is None:
            return
        virtual = self._to_virtual(event.position().toPoint())
        if not self._press_started_drag:
            if virtual.distance_to(self._press_pos) < _DRAG_THRESHOLD:
                return
            # Begin an actual drag.
            self._press_started_drag = True
            offset = self._dragging.body.position - virtual
            self._dragging.handle_event("grab", grab_offset=offset)
        self._dragging.handle_event("drag_move", position=virtual)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if self._dragging is None:
            return
        pet = self._dragging
        started = self._press_started_drag
        self._dragging = None
        self._press_pos = None
        self._press_started_drag = False
        if started:
            pet.handle_event("release")
        elif self.poke_callback is not None:
            self.poke_callback(pet)  # a click without drag = a poke
