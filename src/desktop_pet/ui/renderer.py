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

# Capsule half-thickness per part (rig units, multiplied by scale). Tuned so
# the silhouette reads as a human body: shoulders/chest widest, limbs tapering
# from thigh -> shin and upper arm -> forearm, feet small.
_PART_RADIUS: Dict[str, float] = {
    "torso": 15.0,
    "hips": 13.0,
    "upper_arm_l": 6.0,
    "forearm_l": 5.0,
    "hand_l": 5.5,
    "upper_arm_r": 6.0,
    "forearm_r": 5.0,
    "hand_r": 5.5,
    "thigh_l": 8.5,
    "shin_l": 6.5,
    "foot_l": 5.5,
    "thigh_r": 8.5,
    "shin_r": 6.5,
    "foot_r": 5.5,
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

        torso_z = skeleton.bones["torso"].z_order if "torso" in skeleton.bones else 6
        for name in z_ordered_bone_names(skeleton):
            bone = skeleton.bones[name]
            if name == "head":
                continue  # drawn last, with a face
            part = bone.part or name
            color = QColor(palette.get(part, "#8aa0ff"))
            # Darken limbs that sit behind the torso. Without this the left and
            # right leg (same colour, nearly the same angle) merge into one
            # shapeless mass; shading reads instantly as "far side".
            if bone.z_order < torso_z:
                color = color.darker(128)
            base_r = _PART_RADIUS.get(part, 7.0) * scale
            start_r, end_r = self._limb_radii(part, base_r)
            self._tapered_limb(
                painter,
                bone.world_pos,
                skeleton.tip_scaled_of(name),
                start_r,
                end_r,
                color,
                outline,
                outline_w,
            )

        if "head" in skeleton.bones:
            self._draw_head(painter, pet, palette, outline, outline_w, scale)

    @staticmethod
    def _limb_radii(part: str, radius: float) -> tuple:
        """(start, end) thickness for a part, so limbs taper like real ones.

        The torso widens toward the shoulders; arms and legs narrow toward the
        wrist/ankle. Anything unlisted stays a uniform capsule.
        """
        taper = {
            # part            start,  end   (as a multiple of the base radius)
            "torso": (0.86, 1.16),      # waist -> shoulders
            "hips": (1.0, 1.06),
            "upper_arm_l": (1.0, 0.82),
            "upper_arm_r": (1.0, 0.82),
            "forearm_l": (0.95, 0.78),
            "forearm_r": (0.95, 0.78),
            "thigh_l": (1.0, 0.78),
            "thigh_r": (1.0, 0.78),
            "shin_l": (1.0, 0.72),
            "shin_r": (1.0, 0.72),
        }.get(part)
        if taper is None:
            return radius, radius
        return radius * taper[0], radius * taper[1]

    def _tapered_limb(self, painter, a: Vec2, b: Vec2, r0, r1, fill, outline, outline_w) -> None:
        """Draw a limb as a rounded trapezoid from radius ``r0`` to ``r1``."""
        direction = (b - a)
        if direction.length() < 1e-6:
            return
        normal = Vec2(-direction.y, direction.x).normalized()

        def shape(pad: float) -> QPainterPath:
            n0 = normal * (r0 + pad)
            n1 = normal * (r1 + pad)
            path = QPainterPath()
            path.moveTo(a.x + n0.x, a.y + n0.y)
            path.lineTo(b.x + n1.x, b.y + n1.y)
            path.lineTo(b.x - n1.x, b.y - n1.y)
            path.lineTo(a.x - n0.x, a.y - n0.y)
            path.closeSubpath()
            # Round the joints so bends don't show gaps. WindingFill matters:
            # with the default odd-even rule the overlap between each cap and
            # the quad would be punched out as a hole.
            path.setFillRule(Qt.WindingFill)
            caps = QPainterPath()
            caps.setFillRule(Qt.WindingFill)
            caps.addEllipse(QPointF(a.x, a.y), r0 + pad, r0 + pad)
            caps.addEllipse(QPointF(b.x, b.y), r1 + pad, r1 + pad)
            return path.united(caps)

        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(outline))
        painter.drawPath(shape(outline_w * 0.5))
        painter.setBrush(QBrush(fill))
        painter.drawPath(shape(0.0))

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
        radius = head.length * 0.55 * scale

        pen = QPen(outline)
        pen.setWidthF(outline_w)

        # A short neck bridging shoulders to skull, so the head doesn't look
        # like a balloon floating off the torso.
        neck_dir = (center - base)
        if neck_dir.length() > 1e-6:
            neck_end = base + neck_dir.normalized() * (neck_dir.length() * 0.55)
            painter.setPen(Qt.NoPen)
            neck_r = radius * 0.34
            painter.setBrush(QBrush(outline))
            self._thick_line(painter, base, neck_end, neck_r + outline_w * 0.5)
            painter.setBrush(QBrush(QColor(palette.get("head", "#ffd9a0"))))
            self._thick_line(painter, base, neck_end, neck_r)

        painter.setPen(pen)
        painter.setBrush(QBrush(QColor(palette.get("head", "#ffd9a0"))))
        # Slightly taller than wide, like a real skull.
        painter.drawEllipse(QPointF(center.x, center.y), radius * 0.92, radius)

        # Face oriented toward the facing direction. Both eyes sit on the
        # forward side of the head so the pet reads as looking where it walks.
        face_cfg = self.render_cfg.get("face", {})
        eye_color = QColor(face_cfg.get("eye_color", "#2b2b3a"))
        cheek_color = QColor(face_cfg.get("cheek_color", "#ff9e9e"))
        fx = pet.facing
        eye_dx = radius * 0.34
        eye_dy = -radius * 0.08
        eye_r = max(1.4, radius * 0.11)

        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(cheek_color))
        painter.drawEllipse(
            QPointF(center.x + fx * eye_dx * 1.2, center.y + radius * 0.34),
            eye_r * 1.4,
            eye_r,
        )

        painter.setBrush(QBrush(eye_color))
        painter.drawEllipse(QPointF(center.x + fx * eye_dx, center.y + eye_dy), eye_r, eye_r * 1.3)
        painter.drawEllipse(
            QPointF(center.x + fx * eye_dx * 0.15, center.y + eye_dy), eye_r, eye_r * 1.3
        )

    @staticmethod
    def _thick_line(painter, a: Vec2, b: Vec2, radius: float) -> None:
        """Filled round-capped line, drawn with the painter's current brush."""
        path = QPainterPath()
        path.addEllipse(QPointF(a.x, a.y), radius, radius)
        path.addEllipse(QPointF(b.x, b.y), radius, radius)
        direction = b - a
        if direction.length() > 1e-6:
            n = Vec2(-direction.y, direction.x).normalized() * radius
            quad = QPainterPath()
            quad.moveTo(a.x + n.x, a.y + n.y)
            quad.lineTo(b.x + n.x, b.y + n.y)
            quad.lineTo(b.x - n.x, b.y - n.y)
            quad.lineTo(a.x - n.x, a.y - n.y)
            quad.closeSubpath()
            path = path.united(quad)
        painter.drawPath(path)

    # ------------------------------------------------------------- speech
    def _draw_speech(self, painter: QPainter, pet: Pet) -> None:
        text = pet.speech.text
        head = pet.skeleton.bones.get("head")
        if head is None:
            anchor = pet.position
        else:
            anchor = pet.skeleton.tip_scaled_of("head")

        # A font family that actually has CJK glyphs, so Chinese lines don't
        # render as boxes. Qt falls through the list to the first available.
        font = QFont()
        font.setFamilies(["Segoe UI", "Microsoft YaHei", "Noto Sans CJK SC", "sans-serif"])
        font.setPointSize(max(8, int(10 * pet.config.scale)))
        painter.setFont(font)
        metrics = painter.fontMetrics()
        tw = metrics.horizontalAdvance(text) + 18
        th = metrics.height() + 10

        gap = 14 * pet.config.scale
        bounds = pet.env.bounds
        above = anchor.y - th - gap
        # Flip the bubble below the head when there's no room above (e.g. the
        # pet is standing on a window near the top of the screen).
        flipped = above < bounds.top + 4
        y = (anchor.y + gap) if flipped else above
        # Keep the bubble fully on screen horizontally.
        x = min(max(anchor.x - tw / 2, bounds.left + 4), bounds.right - tw - 4)

        path = QPainterPath()
        path.addRoundedRect(QRectF(x, y, tw, th), 8, 8)
        tail_x = min(max(anchor.x, x + 14), x + tw - 14)
        if flipped:
            path.moveTo(tail_x - 6, y)
            path.lineTo(tail_x, y - 9)
            path.lineTo(tail_x + 6, y)
        else:
            path.moveTo(tail_x - 6, y + th)
            path.lineTo(tail_x, y + th + 9)
            path.lineTo(tail_x + 6, y + th)

        painter.setPen(QPen(QColor("#2b2b3a"), 1.5))
        painter.setBrush(QBrush(QColor(255, 255, 255, 240)))
        painter.drawPath(path)
        painter.setPen(QPen(QColor("#2b2b3a")))
        painter.drawText(QRectF(x, y, tw, th), Qt.AlignCenter, text)
