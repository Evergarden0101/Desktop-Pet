"""Render a solved skeleton with QPainter.

Two render modes share the same rig:

* **shapes** - each bone is drawn as a coloured capsule and the head as a face.
  Needs no art at all, so the pet works the moment you launch it and the
  skeleton (climbing, creeping, ...) is clearly visible.
* **image** - each bone draws its extracted body-part sprite, rotated to the
  bone's world angle and scaled to its length. This is what makes "drop in any
  character PNG" work.

Coordinates are the virtual desktop's; the overlay window translates the painter
so this module can draw in absolute space.
"""

from __future__ import annotations

import math
from typing import Dict, Optional

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPainterPath, QPen, QPixmap

from ..core.geometry import Vec2
from ..core.pet import Pet
from ..core.skeleton import Skeleton
from ..rig.body_parts import z_ordered_bone_names

# Capsule half-thickness per part (rig units, multiplied by scale).
_PART_RADIUS: Dict[str, float] = {
    "torso": 17.0,
    "hips": 16.0,
    "upper_arm_l": 7.5,
    "forearm_l": 6.5,
    "hand_l": 7.0,
    "upper_arm_r": 7.5,
    "forearm_r": 6.5,
    "hand_r": 7.0,
    "thigh_l": 9.5,
    "shin_l": 7.5,
    "foot_l": 6.0,
    "thigh_r": 9.5,
    "shin_r": 7.5,
    "foot_r": 6.0,
}


class PetRenderer:
    def __init__(self, render_cfg: Optional[dict] = None):
        self.render_cfg = render_cfg or {"mode": "shapes"}
        self.mode = self.render_cfg.get("mode", "shapes")
        self._pixmaps: Dict[str, QPixmap] = {}
        self._pixmaps_built = False

    # ------------------------------------------------------------- pixmaps
    def set_part_pixmaps(self, pixmaps: Dict[str, QPixmap]) -> None:
        self._pixmaps = pixmaps
        self._pixmaps_built = True

    def _effective_mode(self, pet: Pet) -> str:
        if self.mode == "image":
            return "image"
        if self.mode == "auto":
            return "image" if self._pixmaps else "shapes"
        return "shapes"

    # -------------------------------------------------------------- public
    def draw(self, painter: QPainter, pet: Pet) -> None:
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        if self._effective_mode(pet) == "image":
            self._draw_images(painter, pet)
        else:
            self._draw_shapes(painter, pet)
        if pet.speech.visible:
            self._draw_speech(painter, pet)

    # --------------------------------------------------------- image mode
    def _draw_images(self, painter: QPainter, pet: Pet) -> None:
        skeleton = pet.skeleton
        scale = pet.config.scale
        for name in z_ordered_bone_names(skeleton):
            bone = skeleton.bones[name]
            part = bone.part or name
            pixmap = self._pixmaps.get(part)
            if pixmap is None or pixmap.isNull():
                continue
            self._draw_part_pixmap(painter, bone, pixmap, scale)

    def _draw_part_pixmap(self, painter, bone, pixmap: QPixmap, scale: float) -> None:
        # Map the sprite's pivot onto the bone joint and align its long axis
        # (pivot -> child_anchor, nominally +Y) with the bone's world direction.
        pw, ph = pixmap.width(), pixmap.height()
        pivot_px = QPointF(bone.pivot.x * pw, bone.pivot.y * ph)
        span = max(1e-3, (0.9 - bone.pivot.y)) * ph  # sprite units along the bone
        target = bone.length * scale
        s = target / span

        painter.save()
        painter.translate(bone.world_pos.x, bone.world_pos.y)
        painter.rotate(math.degrees(bone.world_angle - math.pi / 2))
        painter.scale(s, s)
        painter.drawPixmap(QPointF(-pivot_px.x(), -pivot_px.y()), pixmap)
        painter.restore()

    # --------------------------------------------------------- shape mode
    def _draw_shapes(self, painter: QPainter, pet: Pet) -> None:
        skeleton = pet.skeleton
        scale = pet.config.scale
        cfg = self.render_cfg
        palette = cfg.get("palette", {})
        outline = QColor(cfg.get("outline", "#2b2b3a"))
        outline_w = float(cfg.get("outline_width", 3.0))

        for name in z_ordered_bone_names(skeleton):
            bone = skeleton.bones[name]
            if name == "head":
                continue  # drawn last, with a face
            color = QColor(palette.get(bone.part or name, "#8aa0ff"))
            radius = _PART_RADIUS.get(bone.part or name, 7.0) * scale
            self._capsule(painter, bone.world_pos, skeleton.tip_scaled_of(name), radius, color, outline, outline_w)

        if "head" in skeleton.bones:
            self._draw_head(painter, pet, palette, outline, outline_w, scale)

    def _capsule(self, painter, a: Vec2, b: Vec2, radius, fill, outline, outline_w) -> None:
        pen = QPen(outline)
        pen.setWidthF(outline_w)
        pen.setJoinStyle(Qt.RoundJoin)
        pen.setCapStyle(Qt.RoundCap)

        # Outline pass: a thick round-capped line slightly larger than the fill.
        outline_pen = QPen(outline)
        outline_pen.setWidthF(radius * 2 + outline_w)
        outline_pen.setCapStyle(Qt.RoundCap)
        painter.setPen(outline_pen)
        painter.drawLine(QPointF(a.x, a.y), QPointF(b.x, b.y))

        fill_pen = QPen(fill)
        fill_pen.setWidthF(radius * 2)
        fill_pen.setCapStyle(Qt.RoundCap)
        painter.setPen(fill_pen)
        painter.drawLine(QPointF(a.x, a.y), QPointF(b.x, b.y))

    def _draw_head(self, painter, pet, palette, outline, outline_w, scale) -> None:
        skeleton = pet.skeleton
        head = skeleton.bones["head"]
        base = head.world_pos
        tip = skeleton.tip_scaled_of("head")
        center = Vec2((base.x + tip.x) / 2, (base.y + tip.y) / 2)
        radius = head.length * 0.62 * scale

        pen = QPen(outline)
        pen.setWidthF(outline_w)
        painter.setPen(pen)
        painter.setBrush(QBrush(QColor(palette.get("head", "#ffd9a0"))))
        painter.drawEllipse(QPointF(center.x, center.y), radius, radius)

        # Face oriented toward the facing direction.
        face_cfg = self.render_cfg.get("face", {})
        eye_color = QColor(face_cfg.get("eye_color", "#2b2b3a"))
        cheek_color = QColor(face_cfg.get("cheek_color", "#ff9e9e"))
        fx = pet.facing
        eye_dx = radius * 0.34
        eye_dy = -radius * 0.05
        eye_r = max(1.6, radius * 0.12)

        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(cheek_color))
        painter.drawEllipse(QPointF(center.x + fx * eye_dx * 1.15, center.y + radius * 0.32), eye_r * 1.4, eye_r)

        painter.setBrush(QBrush(eye_color))
        painter.drawEllipse(QPointF(center.x + fx * eye_dx, center.y + eye_dy), eye_r, eye_r * 1.3)
        painter.drawEllipse(QPointF(center.x + fx * eye_dx * 0.15, center.y + eye_dy), eye_r, eye_r * 1.3)

    # ------------------------------------------------------------- speech
    def _draw_speech(self, painter: QPainter, pet: Pet) -> None:
        text = pet.speech.text
        head = pet.skeleton.bones.get("head")
        if head is None:
            top = pet.position
        else:
            top = pet.skeleton.tip_scaled_of("head")

        font = QFont("Segoe UI", max(8, int(10 * pet.config.scale)))
        painter.setFont(font)
        metrics = painter.fontMetrics()
        tw = metrics.horizontalAdvance(text) + 18
        th = metrics.height() + 10
        x = top.x - tw / 2
        y = top.y - th - 14 * pet.config.scale

        path = QPainterPath()
        path.addRoundedRect(QRectF(x, y, tw, th), 8, 8)
        path.moveTo(top.x - 6, y + th)
        path.lineTo(top.x, y + th + 9)
        path.lineTo(top.x + 6, y + th)

        painter.setPen(QPen(QColor("#2b2b3a"), 1.5))
        painter.setBrush(QBrush(QColor(255, 255, 255, 235)))
        painter.drawPath(path)
        painter.setPen(QPen(QColor("#2b2b3a")))
        painter.drawText(QRectF(x, y, tw, th), Qt.AlignCenter, text)
