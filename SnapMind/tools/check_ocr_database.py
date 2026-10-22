"""Fail the build unless the packaged executable persisted actual OCR output."""

import sqlite3
import sys
from pathlib import Path


def main():
    path = Path(sys.argv[1])
    if not path.is_file():
        raise FileNotFoundError("Packaged executable did not create app.db")
    con = sqlite3.connect(str(path))
    try:
        assert (
            con.execute(
                "SELECT count(*) FROM records WHERE raw_ocr LIKE ?", ("%0x09F0%",)
            ).fetchone()[0]
            > 0
        )
    finally:
        con.close()
    print("PASS: packaged OCR and persistence")


if __name__ == "__main__":
    main()
