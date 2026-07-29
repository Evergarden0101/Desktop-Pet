"""The speech bubble that pops up beside a pet's head."""

from __future__ import annotations

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, QTimer, QPropertyAnimation
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

PAD_X = 14
PAD_Y = 10
RADIUS = 12
TAIL = 12
MARGIN = 8          # transparent breathing room for the drop shadow
MAX_TEXT_W = 220


class SpeechBubble(QWidget):
    """A frameless rounded bubble with a tail pointing at the pet's head.

    It is a real top-level window rather than something painted into the pet,
    so it can extend past the pet's own (small) window without being clipped.
    """

    def __init__(self):
        super().__init__(None)  # a top-level window, so it is never clipped
                                # by the pet's own small window
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
                            | Qt.Tool | Qt.WindowTransparentForInput
                            | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)

        self._text = ""
        self._tail_left = True     # tail on the left edge => bubble sits right of head
        self._font = QFont()
        self._font.setPointSizeF(10.5)
        self._font.setBold(True)

        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self._fade_out)

        self._fade = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade.setDuration(180)
        self._hide_on_finish = False

    # -- geometry ---------------------------------------------------------

    def _text_size(self):
        metrics = QFontMetrics(self._font)
        rect = metrics.boundingRect(0, 0, MAX_TEXT_W, 1000,
                                    Qt.TextWordWrap | Qt.AlignCenter, self._text)
        return max(rect.width(), 24), max(rect.height(), metrics.height())

    def show_text(self, text: str, head: QPoint, seconds: float,
                  prefer_right: bool = True) -> None:
        self._text = text
        tw, th = self._text_size()
        w = tw + PAD_X * 2 + TAIL + MARGIN * 2
        h = th + PAD_Y * 2 + MARGIN * 2
        self.resize(int(w), int(h))

        self._tail_left = prefer_right
        self.move(self._place(head, int(w), int(h)))

        self.setWindowOpacity(0.0)
        self.show()
        self.raise_()
        self._fade.stop()
        self._clear_fade_handlers()   # or a pending fade-out would hide us again
        self._fade.setStartValue(0.0)
        self._fade.setEndValue(1.0)
        self._fade.start()
        self._hide_timer.start(int(seconds * 1000))

    def _place(self, head: QPoint, w: int, h: int) -> QPoint:
        """Put the tail tip on the head, keeping the bubble on screen."""
        from PySide6.QtGui import QGuiApplication

        if self._tail_left:
            pos = QPoint(head.x() + 4, head.y() - h // 2)
        else:
            pos = QPoint(head.x() - w - 4, head.y() - h // 2)

        screen = QGuiApplication.screenAt(head) or QGuiApplication.primaryScreen()
        if screen:
            area = screen.availableGeometry()
            if pos.x() + w > area.right() and self._tail_left:
                self._tail_left = False
                pos.setX(head.x() - w - 4)
            elif pos.x() < area.left() and not self._tail_left:
                self._tail_left = True
                pos.setX(head.x() + 4)
            pos.setX(max(area.left(), min(pos.x(), area.right() - w)))
            pos.setY(max(area.top(), min(pos.y(), area.bottom() - h)))
        return pos

    def follow(self, head: QPoint) -> None:
        """Keep the bubble glued to the head while the pet moves."""
        if self.isVisible():
            self.move(self._place(head, self.width(), self.height()))

    # -- painting ---------------------------------------------------------

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        body = QRectF(MARGIN + (TAIL if self._tail_left else 0), MARGIN,
                      self.width() - MARGIN * 2 - TAIL,
                      self.height() - MARGIN * 2)

        path = QPainterPath()
        path.addRoundedRect(body, RADIUS, RADIUS)

        mid = body.center().y()
        tail = QPainterPath()
        if self._tail_left:
            tip = QPointF(MARGIN, mid)
            tail.moveTo(body.left() + 1, mid - TAIL * 0.62)
            tail.lineTo(tip)
            tail.lineTo(body.left() + 1, mid + TAIL * 0.62)
        else:
            tip = QPointF(self.width() - MARGIN, mid)
            tail.moveTo(body.right() - 1, mid - TAIL * 0.62)
            tail.lineTo(tip)
            tail.lineTo(body.right() - 1, mid + TAIL * 0.62)
        tail.closeSubpath()
        path = path.united(tail)

        painter.setPen(QPen(QColor(236, 142, 170), 2))
        painter.setBrush(QColor(255, 252, 253, 245))
        painter.drawPath(path)

        painter.setFont(self._font)
        painter.setPen(QColor(84, 58, 70))
        painter.drawText(body.adjusted(PAD_X, PAD_Y, -PAD_X, -PAD_Y),
                         Qt.TextWordWrap | Qt.AlignCenter, self._text)

    # -- lifecycle --------------------------------------------------------

    def _clear_fade_handlers(self) -> None:
        if self._hide_on_finish:
            self._fade.finished.disconnect(self.hide)
            self._hide_on_finish = False

    def _fade_out(self) -> None:
        self._fade.stop()
        self._clear_fade_handlers()
        self._fade.setStartValue(self.windowOpacity())
        self._fade.setEndValue(0.0)
        self._fade.finished.connect(self.hide)
        self._hide_on_finish = True
        self._fade.start()
