import ctypes
from types import SimpleNamespace

from snapmind import native


class FakeUser32:
    def __init__(self):
        self.active = {}
        self.denied = set()

    def RegisterHotKey(self, window, key, modifiers, vk):
        pair = modifiers, vk
        if pair in self.denied or key in self.active or pair in self.active.values():
            return 0
        self.active[key] = pair
        return 1

    def UnregisterHotKey(self, window, key):
        self.active.pop(key, None)
        return 1


def test_hotkey_conflict_preserves_previous_registration(app, monkeypatch):
    api = FakeUser32()
    monkeypatch.setattr(native, "IS_WINDOWS", True)
    monkeypatch.setattr(ctypes, "windll", SimpleNamespace(user32=api), raising=False)
    keys = native.Hotkeys(app)

    def callback():
        return None

    original = [
        ("Ctrl+Alt+A", callback),
        ("Ctrl+Alt+V", callback),
        ("Ctrl+Alt+F", callback),
    ]
    try:
        assert keys.register(original) == []
        before = dict(api.active)
        api.denied.add(native.parse_hotkey("Ctrl+Alt+Z"))
        errors = keys.register([("Ctrl+Alt+Z", callback), *original[1:]])
        assert errors and "注册失败" in errors[0]
        assert api.active == before
        assert keys.callbacks.keys() == before.keys()
        assert keys.register([("Ctrl+Shift+A", callback), *original[1:]]) == []
        assert native.parse_hotkey("Ctrl+Shift+A") in api.active.values()
    finally:
        keys.close()
    assert api.active == {}
