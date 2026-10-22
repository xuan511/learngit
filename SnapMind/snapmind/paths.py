from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
from pathlib import Path

DEFAULTS = {
    "theme": "light",
    "monitor": True,
    "image_history": True,
    "max_item_mb": 10,
    "max_history": 5000,
    "retention_days": 30,
    "blacklist": ["keepass.exe", "keepassxc.exe", "1password.exe", "bitwarden.exe"],
    "capture_hotkey": "Ctrl+Alt+A",
    "clipboard_hotkey": "Ctrl+Alt+V",
    "search_hotkey": "Ctrl+Alt+F",
    "auto_ocr": True,
    "close_to_tray": True,
}


class Paths:
    def __init__(self, root: Path | None = None):
        executable_root = (
            Path(sys.executable).parent
            if getattr(sys, "frozen", False)
            else Path(__file__).resolve().parents[1]
        )
        self.root = Path(
            root or os.environ.get("SNAPMIND_HOME", executable_root)
        ).resolve()
        self.data = self.root / "data"
        self.config = self.root / "config"
        self.logs = self.root / "logs"
        for folder in (
            self.data,
            self.config,
            self.logs,
            self.data / "screenshots",
            self.data / "clipboard_images",
            self.data / "documents",
            self.data / "backups",
        ):
            folder.mkdir(parents=True, exist_ok=True)
        self.db = self.data / "app.db"

    def resolve(self, relative: str) -> Path:
        path = (self.data / relative).resolve()
        if not path.is_relative_to(self.data.resolve()):
            raise ValueError("附件路径超出数据目录")
        return path


class Settings:
    def __init__(self, paths: Paths):
        self.path = paths.config / "settings.json"
        self.lock = threading.RLock()
        self.values = dict(DEFAULTS)
        if self.path.exists():
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
            for key, value in loaded.items():
                if key in DEFAULTS and type(value) is type(DEFAULTS[key]):
                    self.values[key] = value

    def get(self, key):
        with self.lock:
            return self.values[key]

    def update(self, **kwargs):
        with self.lock:
            for key, value in kwargs.items():
                if key not in DEFAULTS or type(value) is not type(DEFAULTS[key]):
                    raise ValueError(f"无效设置：{key}")
            new = {**self.values, **kwargs}
            fd, name = tempfile.mkstemp(
                prefix="settings-", suffix=".tmp", dir=self.path.parent
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as stream:
                    json.dump(new, stream, ensure_ascii=False, indent=2)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(name, self.path)
                self.values = new
            finally:
                Path(name).unlink(missing_ok=True)
