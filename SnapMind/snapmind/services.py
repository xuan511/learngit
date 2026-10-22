from __future__ import annotations

import hashlib
import shutil
import uuid
from pathlib import Path

from PySide6.QtCore import QBuffer, QIODevice, QMimeData, QObject, QUrl, Signal
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from .native import IS_WINDOWS, foreground_app
from .store import classify


def image_bytes(image: QImage) -> bytes:
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    if not image.save(buffer, "PNG"):
        raise ValueError("无法编码图片")
    return bytes(buffer.data())


class ContentService:
    def __init__(self, store):
        self.store = store
        self.paths = store.paths

    def text(self, text, html="", files=None):
        kind, tags = classify(text)
        if files:
            kind = "files"
            text = "\n".join(files)
        elif html:
            kind = "html"
        fingerprint = hashlib.sha256(
            (kind + "\0" + text + "\0" + html).encode()
        ).hexdigest()
        return self.store.add(
            kind,
            text.splitlines()[0][:90] if text else "网页内容",
            text,
            html=html,
            tags=",".join(tags),
            fingerprint=fingerprint,
        )

    def image(self, image: QImage, screenshot=False):
        png = image_bytes(image)
        fingerprint = (
            None if screenshot else hashlib.sha256(b"image\0" + png).hexdigest()
        )
        if fingerprint:
            with self.store.connect() as con:
                row = con.execute(
                    "SELECT id FROM records WHERE fingerprint=?", (fingerprint,)
                ).fetchone()
            if row:
                self.store.update(row[0], title=self.store.get(row[0])["title"])
                return row[0]
        folder = "screenshots" if screenshot else "clipboard_images"
        relative = f"{folder}/{uuid.uuid4().hex}.png"
        path = self.paths.resolve(relative)
        path.write_bytes(png)
        try:
            return self.store.add(
                "screenshot" if screenshot else "image",
                "区域截图" if screenshot else "剪贴板图片",
                file_path=relative,
                fingerprint=fingerprint,
            )
        except Exception:
            path.unlink(missing_ok=True)
            raise

    def import_file(self, filename, copy=True):
        source = Path(filename).resolve()
        suffix = source.suffix.lower()
        if suffix in {".png", ".jpg", ".jpeg", ".bmp", ".webp"}:
            image = QImage(str(source))
            if image.isNull():
                raise ValueError("无法读取图片")
            return self.image(image, screenshot=True)
        if suffix != ".pdf":
            return self.store.add(
                "files", source.name, str(source), external_path=str(source)
            )
        from pypdf import PdfReader

        reader = PdfReader(str(source))
        if reader.is_encrypted:
            raise ValueError("暂不支持加密 PDF，请导入未加密副本")
        # A large PDF is processed off the GUI thread; never fetch external resources.
        pages = [page.extract_text() or "" for page in reader.pages]
        text = "\n\n".join(f"【第 {i + 1} 页】\n{page}" for i, page in enumerate(pages))
        relative = ""
        if copy:
            relative = f"documents/{uuid.uuid4().hex}.pdf"
            shutil.copy2(source, self.paths.resolve(relative))
        try:
            return self.store.add(
                "pdf",
                source.stem,
                text,
                file_path=relative,
                external_path="" if copy else str(source),
                notes=f"{len(reader.pages)} 页；"
                + (
                    "未提取到文字，可能为扫描版 PDF。"
                    if not any(page.strip() for page in pages)
                    else "本地提取文字"
                ),
            )
        except Exception:
            if relative:
                self.paths.resolve(relative).unlink(missing_ok=True)
            raise


class OcrService:
    def __init__(self, store):
        self.store = store
        self.engine = None

    def recognize(self, record_id):
        if self.engine is None:
            # rapidocr_onnxruntime's wheel contains all three ONNX models.
            # This engine has no downloader; model loading happens on the OCR worker.
            import cv2
            import onnxruntime
            from rapidocr_onnxruntime import RapidOCR

            onnxruntime.disable_telemetry_events()
            cv2.setNumThreads(2)
            cv2.ocl.setUseOpenCL(False)
            from .models import verify_models

            verify_models()
            self.engine = RapidOCR(intra_op_num_threads=2, inter_op_num_threads=1)
        record = self.store.get(record_id)
        if not record:
            return None
        image = self.store.paths.resolve(record["file_path"])
        if not image.is_file():
            raise FileNotFoundError("图片已丢失，请重新导入")
        result, elapsed = self.engine(str(image))
        text = "\n".join(line[1] for line in result) if result else ""
        # Re-read inside a write transaction so edits made DURING inference survive.
        self.store.apply_ocr(record_id, text)
        return record_id, text, elapsed


class ClipboardMonitor(QObject):
    captured = Signal(str)
    error = Signal(str)
    privacy = Signal(str)

    def __init__(self, settings, content, jobs, parent=None):
        super().__init__(parent)
        self.settings, self.content, self.jobs = settings, content, jobs
        self.clipboard = QApplication.clipboard()
        self.own = False
        self.marker = uuid.uuid4().hex.encode("ascii")
        self.suspended = False
        self.clipboard.dataChanged.connect(self.capture)

    def capture(self):
        if self.own or self.suspended or not self.settings.get("monitor"):
            return
        if IS_WINDOWS:
            active = foreground_app()
            blacklist = {
                p.strip().casefold()
                for p in self.settings.get("blacklist")
                if p.strip()
            }
            if active is None and blacklist:
                self.privacy.emit("无法确认前台应用，本次剪贴板未记录")
                return
            if active in blacklist:
                return
        mime = self.clipboard.mimeData()
        if mime is None:
            return
        if bytes(mime.data("application/x-snapmind-source")) == self.marker:
            return
        maximum = self.settings.get("max_item_mb") * 1024**2
        if mime.hasUrls() and any(u.isLocalFile() for u in mime.urls()):
            files = [u.toLocalFile() for u in mime.urls() if u.isLocalFile()]
            if sum(len(p.encode()) for p in files) > maximum:
                self.privacy.emit("文件列表超过单条大小限制，未记录")
                return
            self.jobs.submit(
                lambda: self.content.text("", files=files),
                self.captured.emit,
                self.error.emit,
            )
        elif mime.hasImage():
            if not self.settings.get("image_history"):
                return
            image = QImage(self.clipboard.image()).copy()
            if image.isNull() or image.sizeInBytes() > maximum:
                self.privacy.emit("图片超过大小限制，或无法读取，未记录")
                return
            self.jobs.submit(
                lambda: self.content.image(image), self.captured.emit, self.error.emit
            )
        elif mime.hasText():
            text, html = mime.text(), mime.html() if mime.hasHtml() else ""
            if not text.strip():
                return
            if len(text.encode()) + len(html.encode()) > maximum:
                self.privacy.emit("内容超过单条大小限制，未记录")
                return
            self.jobs.submit(
                lambda: self.content.text(text, html),
                self.captured.emit,
                self.error.emit,
            )

    def copy(self, record, image=False):
        self.own = True
        try:
            mime = QMimeData()
            mime.setData("application/x-snapmind-source", self.marker)
            if image and record["file_path"]:
                picture = QImage(str(self.content.paths.resolve(record["file_path"])))
                if picture.isNull():
                    raise FileNotFoundError("图片文件已丢失")
                mime.setImageData(picture)
            elif record["kind"] == "files":
                files = record["body"].splitlines()
                mime.setUrls([QUrl.fromLocalFile(f) for f in files])
                mime.setText(record["body"])
            elif record["kind"] == "html" and record["html"]:
                mime.setText(record["body"])
                mime.setHtml(record["html"])
            else:
                mime.setText(record["body"] or record["raw_ocr"] or record["title"])
            self.clipboard.setMimeData(mime)
        finally:
            self.own = False

    def copy_image(self, image):
        self.own = True
        try:
            mime = QMimeData()
            mime.setData("application/x-snapmind-source", self.marker)
            mime.setImageData(image)
            self.clipboard.setMimeData(mime)
        finally:
            self.own = False
