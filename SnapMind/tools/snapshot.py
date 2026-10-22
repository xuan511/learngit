"""Render the real desktop UI with isolated sample data for visual inspection."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import sys
import tempfile
import time
from pathlib import Path

from PySide6.QtWidgets import QApplication

from snapmind.paths import Paths, Settings
from snapmind.ui import MainWindow


def settle(app, window):
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
        if not window.io.pending:
            app.processEvents()
            return
    raise RuntimeError("UI snapshot timed out")


def main():
    app = QApplication([])
    with tempfile.TemporaryDirectory(prefix="snapmind-visual-") as tmp:
        paths = Paths(Path(tmp))
        settings = Settings(paths)
        settings.update(monitor=False, close_to_tray=False)
        window = MainWindow(paths, settings)
        for kind, title, body, tags, favorite in [
            (
                "note",
                "Flash 命令寄存器说明",
                "控制寄存器 0x09F0 · 读写时序与位定义",
                "嵌入式,寄存器",
                1,
            ),
            (
                "code",
                "Linux 串口调试笔记",
                "sudo stty -F /dev/ttyUSB0 115200\n串口调试与日志记录",
                "Linux,串口",
                0,
            ),
            (
                "snippet",
                "Git 常用命令",
                "git status --short\ngit log --oneline -10",
                "Git,命令",
                1,
            ),
            (
                "note",
                "把灵感留在这里",
                "截图、代码和笔记，都能在本地轻松找回。",
                "学习",
                0,
            ),
        ]:
            window.store.add(kind, title, body, tags=tags, favorite=favorite)
        window.show()
        window.refresh()
        settle(app, window)
        assert window.recent.count() == 4
        output = Path(sys.argv[1] if len(sys.argv) > 1 else "docs/screenshots")
        output.mkdir(parents=True, exist_ok=True)
        window.grab().save(str(output / "home-light.png"))
        window.toggle_theme()
        app.processEvents()
        window.grab().save(str(output / "home-dark.png"))
        window.toggle_theme()
        window.navigate("all")
        settle(app, window)
        window.records.setCurrentRow(3)
        settle(app, window)
        window.grab().save(str(output / "library.png"))
        from PySide6.QtGui import QImage

        from tools.ocr_fixture import make_fixture

        fixture = make_fixture(Path(tmp) / "capture.png")
        window.capture_selected(QImage(str(fixture)))
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.01)
            if window.previews and window.previews[0].ocr_text.toPlainText():
                break
        assert window.previews and "0x09F0" in window.previews[0].ocr_text.toPlainText()
        window.previews[0].grab().save(str(output / "ocr-result.png"))
        for preview in list(window.previews):
            preview.close()
        window.quit_app()


if __name__ == "__main__":
    main()
