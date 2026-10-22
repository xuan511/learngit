"""Create a clean source delivery without virtualenvs, databases or build caches."""

import hashlib
import zipfile
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[1]
    ignored = {
        ".venv",
        "__pycache__",
        ".pytest_cache",
        ".ruff_cache",
        "build",
        "dist",
        "data",
        "config",
        "logs",
    }
    output = root / "dist/SnapMind-0.1.0-source.zip"
    output.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as z:
        for path in sorted(root.rglob("*")):
            relative = path.relative_to(root)
            if (
                path.is_file()
                and not ignored.intersection(relative.parts)
                and path.suffix != ".pyc"
            ):
                z.write(path, "SnapMind/" + relative.as_posix())
        workflow = root.parent / ".github/workflows/snapmind-windows.yml"
        if workflow.is_file():
            z.write(workflow, ".github/workflows/snapmind-windows.yml")
    with zipfile.ZipFile(output) as z:
        assert z.testzip() is None
        for required in [
            "SnapMind/run.py",
            "SnapMind/requirements.txt",
            "SnapMind/tools/build-windows.ps1",
            "SnapMind/snapmind/models-manifest.json",
            ".github/workflows/snapmind-windows.yml",
        ]:
            assert required in z.namelist()
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_suffix(".zip.sha256").write_text(
        f"{digest}  {output.name}\n", encoding="ascii"
    )
    print(
        f"Source delivery: {output} ({output.stat().st_size:,} bytes)\nSHA-256: {digest}"
    )


if __name__ == "__main__":
    main()
