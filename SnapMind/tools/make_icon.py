from pathlib import Path

from PIL import Image, ImageDraw


def main():
    output = Path(__file__).resolve().parents[1] / "assets"
    output.mkdir(exist_ok=True)
    image = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((4, 4, 252, 252), radius=56, fill="#3e73e8")
    for points in [
        [(62, 100), (62, 62), (100, 62)],
        [(156, 62), (194, 62), (194, 100)],
        [(62, 156), (62, 194), (100, 194)],
        [(156, 194), (194, 194), (194, 156)],
    ]:
        draw.line(points, fill="white", width=12, joint="curve")
    draw.rounded_rectangle((95, 95, 161, 161), radius=14, outline="white", width=10)
    image.save(
        output / "snapmind.ico",
        sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    image.save(output / "snapmind.png")


if __name__ == "__main__":
    main()
