from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="SnapMind 瞬知 · 本地截图与知识收纳")
    parser.add_argument(
        "--data-dir", type=Path, help="便携根目录（包含 data/、config/、logs/）"
    )
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="创建窗口后验证事件循环并退出，不开始屏幕捕获",
    )
    parser.add_argument(
        "--verify-ocr",
        type=Path,
        help="对指定本地图片运行离线 OCR 并输出结果，用于验证打包产物",
    )
    args = parser.parse_args()
    if args.verify_ocr:
        import json

        from PySide6.QtGui import QImage

        from .paths import Paths
        from .services import ContentService, OcrService
        from .store import Store

        paths = Paths(args.data_dir)
        store = Store(paths)
        image = QImage(str(args.verify_ocr))
        if image.isNull():
            parser.error("无法读取验证图片")
        rid = ContentService(store).image(image, screenshot=True)
        result = OcrService(store).recognize(rid)
        print(json.dumps({"record_id": rid, "ocr_text": result[1]}, ensure_ascii=False))
        return 0
    # OpenCV's wheel may inject its own Qt plugins; always prefer PySide's.
    from PySide6.QtCore import QLibraryInfo, QLockFile, Qt, QTimer
    from PySide6.QtGui import QFont
    from PySide6.QtWidgets import QApplication, QMessageBox

    os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = QLibraryInfo.path(
        QLibraryInfo.LibraryPath.PluginsPath
    )
    from .paths import Paths, Settings

    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv[:1])
    app.setApplicationName("SnapMind")
    app.setOrganizationName("SnapMind")
    app.setFont(
        QFont(
            "Microsoft YaHei UI" if sys.platform == "win32" else "Noto Sans CJK SC", 10
        )
    )
    app.setQuitOnLastWindowClosed(False)
    try:
        paths = Paths(args.data_dir)
        lock = QLockFile(str(paths.config / "instance.lock"))
        lock.setStaleLockTime(30000)
        if not lock.tryLock(50):
            QMessageBox.information(
                None,
                "SnapMind 已运行",
                "同一数据目录已有一个 SnapMind 实例。请从系统托盘打开。",
            )
            return 2
        from .ui import MainWindow

        window = MainWindow(paths, Settings(paths))
        window.show()
        if args.smoke:
            QTimer.singleShot(1200, window.quit_app)
        status = app.exec()
        lock.unlock()
        return status
    except Exception as exc:
        QMessageBox.critical(
            None,
            "SnapMind 无法启动",
            f"{type(exc).__name__}：{exc}\n\n请检查数据目录是否可写；可使用 --data-dir 指定其他目录。",
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
