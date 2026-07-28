"""Generate the app/tray icon at runtime (no bundled image needed)."""

from __future__ import annotations

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QBrush, QColor, QIcon, QPainter, QPen, QPixmap


def make_app_icon(size: int = 64) -> QIcon:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)

    # Rounded blue badge.
    painter.setPen(Qt.NoPen)
    painter.setBrush(QBrush(QColor("#4f8cff")))
    painter.drawRoundedRect(4, 4, size - 8, size - 8, size * 0.28, size * 0.28)

    # A little face.
    cx, cy = size / 2, size / 2
    painter.setBrush(QBrush(QColor("#ffd9a0")))
    painter.drawEllipse(QPointF(cx, cy - size * 0.02), size * 0.26, size * 0.26)

    painter.setBrush(QBrush(QColor("#2b2b3a")))
    eye_dx = size * 0.10
    eye_r = size * 0.035
    painter.drawEllipse(QPointF(cx - eye_dx, cy - size * 0.04), eye_r, eye_r * 1.3)
    painter.drawEllipse(QPointF(cx + eye_dx, cy - size * 0.04), eye_r, eye_r * 1.3)

    painter.setBrush(QBrush(QColor("#ff9e9e")))
    painter.drawEllipse(QPointF(cx - eye_dx * 1.5, cy + size * 0.05), eye_r * 1.3, eye_r)
    painter.drawEllipse(QPointF(cx + eye_dx * 1.5, cy + size * 0.05), eye_r * 1.3, eye_r)
    painter.end()
    return QIcon(pixmap)
