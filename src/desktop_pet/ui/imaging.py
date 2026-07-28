"""Bridge Pillow images into Qt pixmaps (UI-only helper)."""

from __future__ import annotations

from PySide6.QtGui import QImage, QPixmap


def pil_to_qpixmap(image) -> QPixmap:
    """Convert a ``PIL.Image.Image`` to a detached :class:`QPixmap`."""
    rgba = image.convert("RGBA")
    data = rgba.tobytes("raw", "RGBA")
    qimage = QImage(data, rgba.width, rgba.height, QImage.Format_RGBA8888)
    # ``.copy()`` detaches the QImage from the temporary ``data`` buffer.
    return QPixmap.fromImage(qimage.copy())
