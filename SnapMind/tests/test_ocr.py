import socket
import time

from PySide6.QtGui import QImage

from snapmind.services import ContentService, OcrService
from tools.ocr_fixture import make_fixture


def test_real_offline_chinese_code_ocr_and_persistence(
    store, paths, tmp_path, monkeypatch
):
    source = make_fixture(tmp_path / "中文技术截图.png")

    def no_network(*args, **kwargs):
        raise AssertionError("network access forbidden during offline OCR test")

    monkeypatch.setattr(socket.socket, "connect", no_network)
    monkeypatch.setattr(socket, "create_connection", no_network)
    service = ContentService(store)
    rid = service.image(QImage(str(source)), screenshot=True)
    engine = OcrService(store)
    started = time.perf_counter()
    result = engine.recognize(rid)
    elapsed = time.perf_counter() - started
    text = result[1]
    print(f"\nReal offline OCR cold inference: {elapsed:.3f}s\n{text}")
    assert "0x09F0" in text
    assert "寄存器" in text
    assert "42" in text
    assert "git" in text
    assert store.search("0x09F0")[0]["id"] == rid
    assert store.search("寄存器")[0]["id"] == rid
    store.update(rid, body="手工修正值 0x09F0")
    engine.recognize(rid)
    assert store.get(rid)["body"] == "手工修正值 0x09F0"
    assert store.get(rid)["raw_ocr"] == text


def test_failed_ocr_job_can_be_retried_without_restarting(store, paths, tmp_path):
    source = make_fixture(tmp_path / "valid.png")
    rid = ContentService(store).image(QImage(str(source)), screenshot=True)
    engine = OcrService(store)
    engine.engine = lambda path: (_ for _ in ()).throw(
        RuntimeError("simulated engine failure")
    )
    try:
        engine.recognize(rid)
    except RuntimeError:
        pass
    else:
        raise AssertionError("failure must propagate to the job error signal")
    engine.engine = lambda path: ([[[], "recovered 0x09F0", 0.99]], [0.01])
    engine.recognize(rid)
    assert store.get(rid)["raw_ocr"] == "recovered 0x09F0"


def test_edit_during_ocr_is_not_overwritten(store, paths, tmp_path):
    source = make_fixture(tmp_path / "valid.png")
    rid = ContentService(store).image(QImage(str(source)), screenshot=True)
    engine = OcrService(store)

    def infer(path):
        store.update(rid, body="User correction made during inference", tags="保留标签")
        return [[[], "detected 0x09F0", 0.99]], [0.01]

    engine.engine = infer
    engine.recognize(rid)
    r = store.get(rid)
    assert r["body"] == "User correction made during inference"
    assert r["raw_ocr"] == "detected 0x09F0"
    assert "保留标签" in r["tags"] and "寄存器" in r["tags"]


def test_missing_models_are_reported_before_inference(tmp_path, monkeypatch):
    import pytest
    import rapidocr_onnxruntime

    from snapmind.models import verify_models

    monkeypatch.setattr(rapidocr_onnxruntime, "__file__", str(tmp_path / "__init__.py"))
    with pytest.raises(ValueError, match="模型校验失败"):
        verify_models()
