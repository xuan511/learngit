"""Collect original dependency notices into the portable distribution."""

import importlib.metadata as metadata
import json
import shutil
import sys
from pathlib import Path


def collect(destination):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    inventory = []
    excluded = {
        "pip",
        "setuptools",
        "pytest",
        "iniconfig",
        "pluggy",
        "pyinstaller",
        "pyinstaller-hooks-contrib",
        "altgraph",
        "ruff",
        "psutil",
        "pefile",
        "pywin32-ctypes",
    }
    for dist in metadata.distributions():
        name = dist.metadata["Name"]
        if name.casefold() in excluded:
            continue
        inventory.append(
            {
                "name": name,
                "version": dist.version,
                "license": dist.metadata.get("License-Expression")
                or dist.metadata.get("License")
                or "See upstream notices",
                "project_urls": dist.metadata.get_all("Project-URL") or [],
            }
        )
        for entry in dist.files or []:
            if any(
                term in entry.name.upper() for term in ("LICENSE", "COPYING", "NOTICE")
            ):
                source = Path(dist.locate_file(entry))
                if source.is_file():
                    target = destination / name / str(entry)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, target)
    (destination / "DEPENDENCIES.json").write_text(
        json.dumps(inventory, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return inventory


if __name__ == "__main__":
    collect(sys.argv[1] if len(sys.argv) > 1 else "build/dependency-licenses")
