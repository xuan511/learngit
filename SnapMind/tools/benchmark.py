"""Measure only this machine. Never report these numbers as Windows results."""

import json
import os
import platform
import statistics
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def main():
    started = time.perf_counter()
    import psutil
    from PySide6.QtGui import QImage
    from PySide6.QtWidgets import QApplication

    from snapmind.paths import Paths, Settings
    from snapmind.ui import MainWindow
    from tools.ocr_fixture import make_fixture

    app = QApplication([])
    with tempfile.TemporaryDirectory(prefix="snapmind-benchmark-") as tmp:
        paths = Paths(Path(tmp))
        settings = Settings(paths)
        settings.update(monitor=False, close_to_tray=False)
        window = MainWindow(paths, settings)
        window.show()
        while window.io.pending:
            app.processEvents()
            time.sleep(0.005)
        startup = time.perf_counter() - started
        process = psutil.Process()
        rss_before = process.memory_info().rss
        cpu_before = process.cpu_times()
        idle_start = time.perf_counter()
        for _ in range(200):
            app.processEvents()
            time.sleep(0.01)
        idle = time.perf_counter() - idle_start
        cpu_after = process.cpu_times()
        idle_cpu = (
            100
            * (
                (cpu_after.user + cpu_after.system)
                - (cpu_before.user + cpu_before.system)
            )
            / idle
        )
        fixture = make_fixture(Path(tmp) / "technical.png")
        rid = window.content.image(QImage(str(fixture)), screenshot=True)
        start = time.perf_counter()
        result = window.ocr.recognize(rid)
        cold = time.perf_counter() - start
        warm = []
        for _ in range(3):
            start = time.perf_counter()
            window.ocr.recognize(rid)
            warm.append(time.perf_counter() - start)
        rss_after = process.memory_info().rss
        cpu_before_ocr_idle = process.cpu_times()
        after_ocr_idle_start = time.perf_counter()
        for _ in range(200):
            app.processEvents()
            time.sleep(0.01)
        after_ocr_idle_seconds = time.perf_counter() - after_ocr_idle_start
        cpu_after_ocr_idle = process.cpu_times()
        after_ocr_idle_cpu = (
            100
            * (
                (cpu_after_ocr_idle.user + cpu_after_ocr_idle.system)
                - (cpu_before_ocr_idle.user + cpu_before_ocr_idle.system)
            )
            / after_ocr_idle_seconds
        )
        # Representative persisted history: 10,000 unique technical notes.
        with window.store.connect() as con:
            from snapmind.store import now

            stamp = now()
            con.executemany(
                "INSERT INTO records(id,kind,title,body,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                [
                    (
                        f"benchmark-{i}",
                        "note",
                        f"技术笔记 {i}",
                        f"控制寄存器 0x{i:04X} configuration {i}",
                        stamp,
                        stamp,
                    )
                    for i in range(10000)
                ],
            )
        search = {}
        for query in ["寄存器", "0x09F0", "09F", "configuration", "不存在的短词"]:
            times = []
            for _ in range(5):
                start = time.perf_counter()
                rows = window.store.search(query)
                times.append(1000 * (time.perf_counter() - start))
            search[query] = {
                "median_ms": round(statistics.median(times), 3),
                "returned": len(rows),
            }
        info = {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "display": "Qt offscreen; not physical Windows desktop",
            "window_ready_seconds": round(startup, 3),
            "idle_rss_mib": round(rss_before / 1024**2, 1),
            "idle_cpu_percent_one_core": round(idle_cpu, 2),
            "idle_sample_seconds": round(idle, 2),
            "ocr_cold_seconds": round(cold, 3),
            "ocr_warm_seconds": [round(x, 3) for x in warm],
            "rss_after_ocr_mib": round(rss_after / 1024**2, 1),
            "idle_after_ocr_cpu_percent_one_core": round(after_ocr_idle_cpu, 2),
            "idle_after_ocr_sample_seconds": round(after_ocr_idle_seconds, 2),
            "fixture_pixels": [1150, 300],
            "recognized_text": result[1],
            "history_count": 10001,
            "search": search,
        }
        Path("docs/benchmark-linux.json").write_text(
            json.dumps(info, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(json.dumps(info, ensure_ascii=False, indent=2))
        window.quit_app()


if __name__ == "__main__":
    main()
