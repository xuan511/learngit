"""Expose synthetic CI test failures in the public run summary, without secrets."""

import os
import xml.etree.ElementTree as ET
from pathlib import Path


def escape(value):
    return value.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def main():
    source = Path(__file__).resolve().parents[1]
    report = source / "docs/test-results-windows.xml"
    summary = ["# SnapMind Windows validation"]
    if report.is_file():
        root = ET.parse(report).getroot()
        suites = list(root.iter("testsuite"))
        summary.append(
            "Tests: "
            + ", ".join(
                f"{key}={sum(int(s.attrib.get(key, 0)) for s in suites)}"
                for key in ("tests", "failures", "errors", "skipped")
            )
        )
        for case in root.iter("testcase"):
            for failure in list(case):
                if failure.tag in ("failure", "error"):
                    detail = (failure.text or failure.attrib.get("message", ""))[-3000:]
                    summary.append(
                        f"## {case.attrib.get('name', 'test')}\n```text\n{detail}\n```"
                    )
                    print(
                        f"::error title={escape(case.attrib.get('name', 'Windows test'))}::{escape(detail[-900:])}"
                    )
    else:
        summary.append("No JUnit report was produced; inspect the build output below.")
    log = source.parent / "snapmind-build.log"
    if log.is_file():
        tail = "\n".join(
            log.read_text(encoding="utf-8", errors="replace").splitlines()[-100:]
        )[-14000:]
        summary.append(f"## Build output (last lines)\n```text\n{tail}\n```")
    target = os.environ.get("GITHUB_STEP_SUMMARY")
    if target:
        with open(target, "a", encoding="utf-8") as stream:
            stream.write("\n\n".join(summary) + "\n")
    else:
        print("\n\n".join(summary))


if __name__ == "__main__":
    main()
