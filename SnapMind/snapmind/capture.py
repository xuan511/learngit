from __future__ import annotations

import math

from PySide6.QtCore import QPoint, QPointF, QRect, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)


class SelectionOverlay(QWidget):
    selected = Signal(QImage)
    cancelled = Signal()

    def __init__(self, screen, snapshot):
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool,
        )
        self.snapshot = snapshot
        self.setGeometry(screen.geometry())
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.start = None
        self.end = None
        self.setMouseTracking(True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)

    def paintEvent(self, event):
        p = QPainter(self)
        p.drawImage(self.rect(), self.snapshot)
        p.fillRect(self.rect(), QColor(8, 15, 29, 125))
        if self.start and self.end:
            rect = QRect(self.start, self.end).normalized().intersected(self.rect())
            p.save()
            p.setClipRect(rect)
            p.drawImage(self.rect(), self.snapshot)
            p.restore()
            p.setPen(QPen(QColor("#64a0ff"), 2))
            p.drawRect(rect)
            p.fillRect(
                QRect(rect.left(), max(0, rect.top() - 30), 230, 28), QColor("#19243b")
            )
            p.setPen(Qt.GlobalColor.white)
            p.drawText(
                QRect(rect.left() + 8, max(0, rect.top() - 30), 220, 28),
                Qt.AlignmentFlag.AlignVCenter,
                f"{rect.width()} × {rect.height()}  松开即识别",
            )
        else:
            p.setPen(Qt.GlobalColor.white)
            p.drawText(
                self.rect().adjusted(40, 40, -40, -40),
                Qt.AlignmentFlag.AlignTop,
                "拖动选择区域，松开自动保存并识别文字 · Esc 取消",
            )

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.start = self.end = event.position().toPoint()
            self.grabMouse()
            self.update()
        elif event.button() == Qt.MouseButton.RightButton:
            self.cancelled.emit()

    def mouseMoveEvent(self, event):
        if self.start:
            self.end = event.position().toPoint()
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton or self.start is None:
            return
        self.releaseMouse()
        rect = (
            QRect(self.start, event.position().toPoint())
            .normalized()
            .intersected(self.rect())
        )
        if rect.width() < 3 or rect.height() < 3:
            self.start = self.end = None
            self.update()
            return
        # Convert this monitor's logical coordinates into its own native pixels.
        sx, sy = (
            self.snapshot.width() / self.width(),
            self.snapshot.height() / self.height(),
        )
        physical = QRect(
            round(rect.x() * sx),
            round(rect.y() * sy),
            round(rect.width() * sx),
            round(rect.height() * sy),
        )
        image = self.snapshot.copy(physical)
        image.setDevicePixelRatio(1)
        self.selected.emit(image)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.cancelled.emit()


class ImageCanvas(QWidget):
    changed = Signal()

    def __init__(self, image, parent=None):
        super().__init__(parent)
        self.image = image.copy()
        self.image.setDevicePixelRatio(1)
        self.tool = "查看"
        self.start = self.end = None
        self.last = None
        self.history, self.future = [], []
        self.setMinimumSize(300, 240)
        self.setCursor(Qt.CursorShape.CrossCursor)

    def target(self):
        size = self.image.size()
        size.scale(self.size(), Qt.AspectRatioMode.KeepAspectRatio)
        return QRect(
            (self.width() - size.width()) // 2,
            (self.height() - size.height()) // 2,
            size.width(),
            size.height(),
        )

    def point(self, position):
        r = self.target()
        return QPoint(
            round((position.x() - r.x()) * self.image.width() / max(1, r.width())),
            round((position.y() - r.y()) * self.image.height() / max(1, r.height())),
        )

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor("#e9edf3"))
        p.drawImage(self.target(), self.image)
        if (
            self.start is not None
            and self.end is not None
            and self.tool in ("矩形", "箭头", "马赛克")
        ):
            p.setPen(QPen(QColor("#4178ed"), 2, Qt.PenStyle.DashLine))
            p.drawRect(QRect(self.start, self.end).normalized())

    def remember(self):
        self.history.append(self.image.copy())
        # Bound undo memory, including large multi-megapixel screenshots.
        while (
            len(self.history) > 12
            or sum(i.sizeInBytes() for i in self.history) > 128 * 1024**2
        ):
            self.history.pop(0)
        self.future.clear()

    def undo(self):
        if self.history:
            self.future.append(self.image.copy())
            self.image = self.history.pop()
            self.update()
            self.changed.emit()

    def redo(self):
        if self.future:
            self.history.append(self.image.copy())
            self.image = self.future.pop()
            self.update()
            self.changed.emit()

    def mousePressEvent(self, event):
        if (
            event.button() != Qt.MouseButton.LeftButton
            or self.tool == "查看"
            or not self.target().contains(event.position().toPoint())
        ):
            return
        self.start = self.end = event.position().toPoint()
        self.last = self.point(event.position())
        if self.tool == "文字":
            text, ok = QInputDialog.getText(self, "文字标注", "输入文字")
            if ok and text:
                self.remember()
                p = QPainter(self.image)
                p.setPen(QColor("#eb4b54"))
                font = p.font()
                font.setPixelSize(max(22, self.image.width() // 55))
                p.setFont(font)
                p.drawText(self.last, text)
                p.end()
                self.changed.emit()
            self.start = self.end = None
            self.update()
        elif self.tool == "画笔":
            self.remember()

    def mouseMoveEvent(self, event):
        if self.start is None:
            return
        self.end = event.position().toPoint()
        if self.tool == "画笔":
            point = self.point(event.position())
            p = QPainter(self.image)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setPen(
                QPen(
                    QColor("#eb4b54"),
                    max(3, self.image.width() / 500),
                    Qt.PenStyle.SolidLine,
                    Qt.PenCapStyle.RoundCap,
                )
            )
            p.drawLine(self.last, point)
            p.end()
            self.last = point
        self.update()

    def mouseReleaseEvent(self, event):
        if self.start is None:
            return
        a, b = self.point(self.start), self.point(event.position())
        rect = QRect(a, b).normalized().intersected(self.image.rect())
        if self.tool in ("矩形", "箭头", "马赛克"):
            self.remember()
            if self.tool == "马赛克" and rect.width() and rect.height():
                patch = (
                    self.image.copy(rect)
                    .scaled(
                        max(1, rect.width() // 14),
                        max(1, rect.height() // 14),
                        Qt.AspectRatioMode.IgnoreAspectRatio,
                        Qt.TransformationMode.FastTransformation,
                    )
                    .scaled(
                        rect.size(),
                        Qt.AspectRatioMode.IgnoreAspectRatio,
                        Qt.TransformationMode.FastTransformation,
                    )
                )
                p = QPainter(self.image)
                p.drawImage(rect, patch)
            else:
                p = QPainter(self.image)
                p.setRenderHint(QPainter.RenderHint.Antialiasing)
                p.setPen(QPen(QColor("#eb4b54"), max(3, self.image.width() / 500)))
                if self.tool == "矩形":
                    p.drawRect(rect)
                elif self.tool == "箭头":
                    p.drawLine(a, b)
                    angle = math.atan2(b.y() - a.y(), b.x() - a.x())
                    length = max(15, self.image.width() / 60)
                    for delta in (-0.5, 0.5):
                        p.drawLine(
                            QPointF(b),
                            QPointF(
                                b.x() - length * math.cos(angle + delta),
                                b.y() - length * math.sin(angle + delta),
                            ),
                        )
            p.end()
        self.start = self.end = None
        self.update()
        self.changed.emit()


class CapturePreview(QDialog):
    saved = Signal(QImage)
    noteRequested = Signal()
    favoriteRequested = Signal()
    ocrRequested = Signal()
    copyRequested = Signal(QImage)
    exportRequested = Signal(QImage)
    textCopyRequested = Signal(str)

    def __init__(self, image, parent=None):
        super().__init__(parent)
        self.setWindowTitle("截图预览 · 松开选区后已自动保存")
        self.resize(1100, 680)
        root = QVBoxLayout(self)
        top = QHBoxLayout()
        for name, callback in [
            ("复制图片", lambda: self.copyRequested.emit(self.canvas.image.copy())),
            ("另存为", lambda: self.exportRequested.emit(self.canvas.image.copy())),
            ("OCR 识别", self.ocrRequested.emit),
            ("添加笔记", self.noteRequested.emit),
            ("收藏", self.favoriteRequested.emit),
            ("关闭", self.close),
        ]:
            button = QPushButton(name)
            button.clicked.connect(callback)
            top.addWidget(button)
        root.addLayout(top)
        self.canvas = ImageCanvas(image)
        split = QSplitter()
        split.addWidget(self.canvas)
        text_panel = QWidget()
        text_layout = QVBoxLayout(text_panel)
        text_layout.addWidget(QLabel("OCR 原始结果"))
        self.ocr_state = QLabel("识别在后台完成，无需等待即可继续截图。")
        self.ocr_state.setWordWrap(True)
        text_layout.addWidget(self.ocr_state)
        self.ocr_text = QPlainTextEdit()
        self.ocr_text.setReadOnly(True)
        self.ocr_text.setPlaceholderText(
            "识别结果会自动出现在这里。修正文请在主窗口编辑。"
        )
        text_layout.addWidget(self.ocr_text, 1)
        self.copy_text = QPushButton("复制识别文字")
        self.copy_text.setEnabled(False)
        self.copy_text.clicked.connect(
            lambda: self.textCopyRequested.emit(self.ocr_text.toPlainText())
        )
        text_layout.addWidget(self.copy_text)
        split.addWidget(text_panel)
        split.setSizes([730, 330])
        root.addWidget(split, 1)
        tools = QHBoxLayout()
        for name in ["查看", "矩形", "箭头", "画笔", "文字", "马赛克"]:
            button = QPushButton(name)
            button.clicked.connect(
                lambda checked=False, n=name: setattr(self.canvas, "tool", n)
            )
            tools.addWidget(button)
        for name, callback in [
            ("撤销", self.canvas.undo),
            ("重做", self.canvas.redo),
            ("另存标注副本", lambda: self.saved.emit(self.canvas.image.copy())),
        ]:
            button = QPushButton(name)
            button.clicked.connect(callback)
            tools.addWidget(button)
        root.addLayout(tools)
        root.addWidget(
            QLabel("原图与 OCR 自动保存；标注请保存为副本。马赛克会修改实际像素。")
        )

    def show_ocr(self, text):
        self.ocr_text.setPlainText(text)
        self.ocr_state.setText(
            "识别完成，已保存到截图库。"
            if text
            else "未识别到文字，可重新选取更清晰的区域。"
        )
        self.copy_text.setEnabled(bool(text))
