"""Small, explicit Windows integration. No hooks or synthetic paste input."""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes
from pathlib import Path

from PySide6.QtCore import QAbstractNativeEventFilter, QTimer

IS_WINDOWS = sys.platform == "win32"


def foreground_app():
    if not IS_WINDOWS:
        return ""
    user32, kernel = ctypes.windll.user32, ctypes.windll.kernel32
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.GetWindowThreadProcessId.argtypes = [
        wintypes.HWND,
        ctypes.POINTER(wintypes.DWORD),
    ]
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    ]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(user32.GetForegroundWindow(), ctypes.byref(pid))
    handle = kernel.OpenProcess(0x1000, False, pid.value)
    if not handle:
        return None  # Fail closed when a configured blacklist cannot be checked.
    try:
        length = wintypes.DWORD(32768)
        buf = ctypes.create_unicode_buffer(length.value)
        if not kernel.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(length)):
            return None
        return Path(buf.value).name.casefold()
    finally:
        kernel.CloseHandle(handle)


def parse_hotkey(text):
    parts = [p.strip().upper() for p in text.split("+")]
    modifiers, key = 0x4000, None  # MOD_NOREPEAT
    for part in parts:
        if part in {"CTRL", "CONTROL", "ALT", "SHIFT", "WIN"}:
            modifiers |= {"CTRL": 2, "CONTROL": 2, "ALT": 1, "SHIFT": 4, "WIN": 8}[part]
        elif len(part) == 1 and part.isascii() and part.isalnum():
            if key is not None:
                raise ValueError("快捷键只能包含一个主键")
            key = ord(part)
        elif part.startswith("F") and part[1:].isdigit() and 1 <= int(part[1:]) <= 24:
            if key is not None:
                raise ValueError("快捷键只能包含一个主键")
            key = 0x70 + int(part[1:]) - 1
        else:
            raise ValueError(
                "快捷键支持 Ctrl / Alt / Shift / Win 加字母、数字或 F1–F24"
            )
    if key is None or not modifiers & 0xF:
        raise ValueError("请至少包含一个修饰键和一个主键")
    if modifiers & 0xD == 0xC and key == ord("S"):
        raise ValueError("Win+Shift+S 由 Windows 截图工具保留")
    return modifiers, key


class Hotkeys(QAbstractNativeEventFilter):
    def __init__(self, app):
        super().__init__()
        self.app = app
        self.callbacks = {}
        app.installNativeEventFilter(self)

    def register(self, bindings):
        parsed = [parse_hotkey(text) for text, _ in bindings]
        if len(set(parsed)) != len(parsed):
            raise ValueError("三个快捷键不能相同")
        if not IS_WINDOWS:
            return ["当前系统仅支持窗口内快捷键；全局快捷键需要 Windows。"]
        # Register candidates first: on failure the old bindings remain usable.
        fresh = {}
        errors = []
        for (text, callback), pair in zip(bindings, parsed):
            existing = next(
                (i for i, item in self.callbacks.items() if item[0] == pair), None
            )
            if existing is not None:
                fresh[existing] = (pair, callback)
                continue
            hotkey_id = next(
                i
                for i in range(1000, 1100)
                if i not in self.callbacks and i not in fresh
            )
            if not ctypes.windll.user32.RegisterHotKey(None, hotkey_id, *pair):
                errors.append(
                    f"{text} 注册失败，可能被系统或其他应用占用，请在设置中修改。"
                )
            else:
                fresh[hotkey_id] = (pair, callback)
        if errors:
            for key in fresh.keys() - self.callbacks.keys():
                ctypes.windll.user32.UnregisterHotKey(None, key)
            return errors
        for key in self.callbacks.keys() - fresh.keys():
            ctypes.windll.user32.UnregisterHotKey(None, key)
        self.callbacks = fresh
        return []

    def nativeEventFilter(self, event_type, message):
        if IS_WINDOWS and event_type in (
            b"windows_generic_MSG",
            b"windows_dispatcher_MSG",
        ):
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == 0x0312 and msg.wParam in self.callbacks:
                callback = self.callbacks[msg.wParam][1]
                QTimer.singleShot(0, callback)
                return True, 0
        return False, 0

    def close(self):
        if IS_WINDOWS:
            for key in self.callbacks:
                ctypes.windll.user32.UnregisterHotKey(None, key)
        self.callbacks.clear()
        self.app.removeNativeEventFilter(self)
