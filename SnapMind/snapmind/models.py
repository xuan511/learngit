import hashlib
import json
from pathlib import Path


def verify_models():
    import rapidocr_onnxruntime

    manifest = json.loads((Path(__file__).parent / "models-manifest.json").read_text())
    folder = Path(rapidocr_onnxruntime.__file__).parent / "models"
    for name, expected in manifest.items():
        path = folder / name
        if (
            not path.is_file()
            or path.stat().st_size != expected["bytes"]
            or hashlib.sha256(path.read_bytes()).hexdigest() != expected["sha256"]
        ):
            raise ValueError(f"OCR 模型校验失败：{name}")
    return manifest
