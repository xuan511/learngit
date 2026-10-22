"""Verify bundled ONNX artifacts against the checked-in trusted-wheel manifest."""

import hashlib
import json
import sys
from pathlib import Path


def verify(base=None):
    import rapidocr_onnxruntime

    root = Path(__file__).resolve().parents[1]
    if getattr(sys, "frozen", False):
        root = Path(sys._MEIPASS)
    manifest = json.loads((root / "models-manifest.json").read_text())
    folder = (
        Path(base) if base else Path(rapidocr_onnxruntime.__file__).parent / "models"
    )
    for name, expected in manifest.items():
        path = folder / name
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != expected["sha256"] or path.stat().st_size != expected["bytes"]:
            raise ValueError(f"OCR 模型校验失败：{name}")
    return manifest


if __name__ == "__main__":
    manifest = verify()
    print(
        f"PASS: {len(manifest)} offline ONNX models; {sum(v['bytes'] for v in manifest.values()):,} bytes"
    )
