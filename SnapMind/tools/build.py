"""Portable folder packaging with explicit OS guard and dependency notices."""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from tools.collect_licenses import collect
from tools.make_icon import main as make_icon
from tools.verify_models import verify


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", choices=["windows", "native"], default="native")
    args = parser.parse_args()
    if args.target == "windows" and sys.platform != "win32":
        parser.error(
            "Windows EXE requires Windows x64 + Python 3.12; cross-compilation is unsupported. Run tools/build-windows.ps1 on Windows."
        )
    root = Path(__file__).resolve().parents[1]
    os.chdir(root)
    verify()
    make_icon()
    collect(root / "build/dependency-licenses")
    subprocess.run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "SnapMind.spec",
        ],
        check=True,
    )
    folder = root / "dist/SnapMind"
    for name in ("README.md", "LICENSE", "THIRD_PARTY_NOTICES.md"):
        shutil.copy2(root / name, folder / name)
    shutil.copytree(root / "licenses", folder / "licenses", dirs_exist_ok=True)
    shutil.copytree(
        root / "build/dependency-licenses",
        folder / "licenses/dependencies",
        dirs_exist_ok=True,
    )
    shutil.copytree(
        root / "docs",
        folder / "docs",
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns(
            "package-validation-linux.json", "network-trace-linux.txt"
        ),
    )
    tag = "Windows-x64" if sys.platform == "win32" else "Linux-x64-validation"
    archive = Path(
        shutil.make_archive(
            str(root / "dist" / f"SnapMind-0.1.0-{tag}"),
            "zip",
            root / "dist",
            "SnapMind",
        )
    )
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    (archive.with_suffix(".zip.sha256")).write_text(
        f"{digest}  {archive.name}\n", encoding="ascii"
    )
    print(
        json.dumps(
            {"archive": str(archive), "bytes": archive.stat().st_size, "sha256": digest}
        )
    )


if __name__ == "__main__":
    main()
