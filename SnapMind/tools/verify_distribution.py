"""Extract and run the native portable package outside the source checkout."""

import hashlib
import json
import os
import shutil
import sqlite3
import stat
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path


def main():
    if not sys.platform.startswith("linux"):
        raise SystemExit(
            "This verifier is for the Linux validation package. On Windows use tools/build-windows.ps1."
        )
    root = Path(__file__).resolve().parents[1]
    archive = Path(sys.argv[1]).resolve()
    with tempfile.TemporaryDirectory(prefix="瞬知 便携验证 ") as tmp:
        temporary = Path(tmp)
        with zipfile.ZipFile(archive) as z:
            assert z.testzip() is None
            for info in z.infolist():
                if not (temporary / info.filename).resolve().is_relative_to(temporary):
                    raise ValueError("unsafe archive path")
            z.extractall(temporary)
            unpacked = sum(i.file_size for i in z.infolist())
        executable = (
            temporary
            / "SnapMind"
            / ("SnapMind.exe" if sys.platform == "win32" else "SnapMind")
        )
        if sys.platform != "win32":
            executable.chmod(executable.stat().st_mode | stat.S_IXUSR)
        environment = dict(os.environ)
        for key in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV"):
            environment.pop(key, None)
        environment["QT_QPA_PLATFORM"] = "offscreen"
        environment["XDG_CACHE_HOME"] = str(temporary / "cache")
        portable_home = temporary / "用户 数据"
        args = [str(executable), "--data-dir", str(portable_home)]

        def run(command):
            return subprocess.run(
                command,
                cwd=temporary,
                env=environment,
                text=True,
                encoding="utf-8",
                capture_output=True,
                timeout=60,
                check=True,
            )

        run([*args, "--smoke"])
        fixture = temporary / "技术 OCR.png"
        shutil.copy2(root / "tests/fixtures/technical-text.png", fixture)
        trace = temporary / "network.trace"
        command = [*args, "--verify-ocr", str(fixture)]
        tracer = shutil.which("strace") if sys.platform.startswith("linux") else None
        if tracer:
            command = [tracer, "-f", "-e", "trace=network", "-o", str(trace), *command]
        result = run(command)
        recognized = json.loads(result.stdout)
        assert "0x09F0" in recognized["ocr_text"] and "寄存器" in recognized["ocr_text"]
        run([*args, "--smoke"])
        con = sqlite3.connect(portable_home / "data/app.db")
        try:
            assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            assert (
                con.execute(
                    "SELECT count(*) FROM records WHERE raw_ocr LIKE ?", ("%0x09F0%",)
                ).fetchone()[0]
                == 1
            )
        finally:
            con.close()
        network = []
        if tracer:
            contents = trace.read_text()
            network = [
                line
                for line in contents.splitlines()
                if "AF_INET" in line or "connect(" in line
            ]
            assert not network, network
            (root / "docs/network-trace-linux.txt").write_text(contents)
        info = {
            "archive": archive.name,
            "archive_bytes": archive.stat().st_size,
            "executable_sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
            "unpacked_file_bytes": unpacked,
            "platform": sys.platform,
            "relocation": "Chinese path with spaces, outside source checkout",
            "source_python_environment_removed": True,
            "startup_smoke": "passed",
            "packaged_offline_ocr": recognized["ocr_text"],
            "restart_persistence": "passed",
            "sqlite_integrity": "ok",
            "network_syscall_trace": bool(tracer),
            "observed_ip_sockets_or_connects": len(network) if tracer else None,
            "windows_native_validation": False,
        }
        (root / "docs/package-validation-linux.json").write_text(
            json.dumps(info, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(json.dumps(info, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
