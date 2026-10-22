"""Generate an honest OCR fixture, not a replacement for OCR output."""

import shutil
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def make_fixture(path):
    bundled = Path(__file__).resolve().parents[1] / "tests/fixtures/technical-text.png"
    if bundled.is_file():
        shutil.copy2(bundled, path)
        return path
    candidates = [
        Path("C:/Windows/Fonts/msyh.ttc"),
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    ]
    font_path = next(p for p in candidates if p.exists())
    font = ImageFont.truetype(str(font_path), 32)
    image = Image.new("RGB", (1150, 300), "white")
    draw = ImageDraw.Draw(image)
    for i, text in enumerate(
        [
            "控制寄存器 0x09F0",
            "Register address: 0x09F0",
            "int value = 42;",
            "git status --short",
        ]
    ):
        draw.text((32, 22 + i * 65), text, font=font, fill="#17233a")
    image.save(path)
    return path


if __name__ == "__main__":
    make_fixture(Path(sys.argv[1]))
