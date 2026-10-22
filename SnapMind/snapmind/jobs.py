from __future__ import annotations

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot


class Result(QObject):
    done = Signal(object)
    failed = Signal(str)
    finished = Signal()


class Job(QRunnable):
    def __init__(self, function):
        super().__init__()
        self.function = function
        self.signals = Result()

    @Slot()
    def run(self):
        try:
            self.signals.done.emit(self.function())
        except Exception as exc:
            # Never log clipboard text or exception arguments derived from content.
            self.signals.failed.emit(f"{type(exc).__name__}：{exc}")
        finally:
            self.signals.finished.emit()


class Jobs(QObject):
    changed = Signal(int)

    def __init__(self, threads=1, parent=None):
        super().__init__(parent)
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(threads)
        self.pending = set()

    def submit(self, function, done=None, failed=None):
        job = Job(function)
        self.pending.add(job)
        if done:
            job.signals.done.connect(done)
        if failed:
            job.signals.failed.connect(failed)
        job.signals.finished.connect(lambda: self._finished(job))
        self.changed.emit(len(self.pending))
        self.pool.start(job)
        return job

    def _finished(self, job):
        self.pending.discard(job)
        self.changed.emit(len(self.pending))

    def wait(self):
        self.pool.waitForDone()
