import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("XDG_CACHE_HOME", "/tmp/snapmind-test-cache")

import pytest
from PySide6.QtWidgets import QApplication

from snapmind.paths import Paths
from snapmind.store import Store


@pytest.fixture(scope="session")
def app():
    instance = QApplication.instance() or QApplication([])
    instance.setQuitOnLastWindowClosed(False)
    yield instance
    # Qt's offscreen clipboard keeps Python-owned MIME objects until shutdown.
    # Release them while the QApplication and wrapper types are still alive.
    instance.clipboard().clear()
    instance.processEvents()


@pytest.fixture
def paths(tmp_path):
    return Paths(tmp_path / "瞬知 portable")


@pytest.fixture
def store(paths):
    return Store(paths)
