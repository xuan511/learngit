import json
import sqlite3
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from snapmind.paths import Settings
from snapmind.store import Store, classify


@pytest.mark.parametrize(
    "query",
    ["0x09F0", "09F", "寄存器", "存器", "STM32", "寄", "寄存器 0x09F0", '"', "%", "_"],
)
def test_real_search_terms(store, query):
    rid = store.add(
        "screenshot",
        "STM32 寄存器",
        body='控制寄存器 0x09F0; "value" 100% _MASK',
        raw_ocr="原始结果",
    )
    assert rid in [r["id"] for r in store.search(query)]


def test_search_does_not_treat_wildcards_as_matches(store):
    store.add("note", "ordinary", "nothing special")
    assert store.search("%") == []
    assert store.search("_") == []
    assert store.search("' OR 1=1 --") == []


def test_knowledge_contains_saved_notes_documents_and_any_favorite(store):
    ids = {
        store.add("note", "note"),
        store.add("pdf", "manual"),
        store.add("screenshot", "favorite capture", favorite=1),
        store.add("code", "favorite code", favorite=1),
    }
    store.add("text", "ordinary clipboard")
    assert {r["id"] for r in store.search(knowledge=True)} == ids


def test_restore_rejects_inconsistent_manifest_without_touching_current_data(
    store, tmp_path
):
    rid = store.add("note", "keep me")
    valid = tmp_path / "valid.zip"
    broken = tmp_path / "broken.zip"
    store.backup(str(valid))
    with zipfile.ZipFile(valid) as source, zipfile.ZipFile(broken, "w") as target:
        for name in source.namelist():
            data = source.read(name)
            if name == "manifest.json":
                manifest = json.loads(data)
                manifest["records"] = 999
                data = json.dumps(manifest).encode()
            target.writestr(name, data)
    with pytest.raises(ValueError, match="记录数"):
        store.restore(str(broken))
    assert store.get(rid)["title"] == "keep me"


def test_search_filters_dates_and_fuzzy(store):
    rid = store.add(
        "note",
        "Register document",
        "Register configuration",
        tags="STM32,寄存器",
        favorite=1,
    )
    store.add("text", "寄存器", "0x09F0")
    assert [
        r["id"] for r in store.search(tag="寄存器", favorite=True, kinds=["note"])
    ] == [rid]
    assert store.search(tag="寄") == []
    today = datetime.now(timezone.utc).date().isoformat()
    assert len(store.search(after=today, before=today)) == 2
    assert store.search(after="2099-01-01") == []
    result = store.search("Regitser")
    assert result[0]["id"] == rid and result[0]["fuzzy_match"]


def test_pagination_and_pinning(store):
    ids = [store.add("text", str(i), str(i)) for i in range(67)]
    store.update(ids[0], pinned=1)
    a = store.search(limit=60)
    b = store.search(limit=60, offset=60)
    assert a[0]["id"] == ids[0]
    assert len(a) == 60 and len(b) == 7
    assert not set(r["id"] for r in a) & set(r["id"] for r in b)


def test_dedupe_persistence_and_fts_updates(store, paths):
    rid = store.add("text", "test", "before", fingerprint="same")
    assert store.add("text", "test", "before", fingerprint="same") == rid
    store.update(rid, body="after")
    reopened = Store(paths)
    assert reopened.search("before") == []
    assert reopened.search("after")[0]["id"] == rid
    assert len(reopened.search()) == 1


def test_original_ocr_is_preserved(store):
    rid = store.add("screenshot", "image", "0x09FO", raw_ocr="0x09FO")
    store.update(rid, body="0x09F0")
    assert store.get(rid)["raw_ocr"] == "0x09FO"
    assert store.search("0x09F0")[0]["id"] == rid


def test_relationships_and_asset_deletion(store, paths):
    file = paths.resolve("screenshots/test.png")
    file.write_bytes(b"asset")
    image = store.add("screenshot", "register", file_path="screenshots/test.png")
    note = store.add("note", "note")
    pdf = store.add("pdf", "manual", external_path="C:/manual.pdf")
    store.link(note, image)
    store.link(note, pdf, 42)
    assert sorted(r["page"] for r in store.links(note)) == [0, 42]
    with pytest.raises(ValueError, match="关联"):
        store.delete(image)
    assert file.exists()
    store.unlink(note, image)
    store.delete(image)
    assert not file.exists()
    assert store.get(note)
    with pytest.raises(sqlite3.IntegrityError):
        store.link(note, "missing")


def test_shared_asset_not_removed_early(store, paths):
    paths.resolve("screenshots/shared.png").write_bytes(b"asset")
    a = store.add("image", "a", file_path="screenshots/shared.png")
    b = store.add("image", "b", file_path="screenshots/shared.png")
    store.delete(a)
    assert paths.resolve("screenshots/shared.png").exists()
    store.delete(b)
    assert not paths.resolve("screenshots/shared.png").exists()


def test_pruning_respects_protected_records(store):
    plain = store.add("text", "plain")
    fav = store.add("text", "fav", favorite=1)
    pin = store.add("text", "pin", pinned=1)
    linked = store.add("text", "linked")
    note = store.add("note", "note")
    image = store.add("screenshot", "capture")
    store.link(note, linked)
    assert store.prune(clear=True) == 1
    assert store.get(plain) is None
    assert all(store.get(i) for i in (fav, pin, linked, note, image))


def test_age_and_count_retention(store):
    old = store.add("text", "old")
    with store.connect() as con:
        con.execute(
            "UPDATE records SET created_at=? WHERE id=?",
            ((datetime.now(timezone.utc) - timedelta(days=40)).isoformat(), old),
        )
    store.prune(days=30)
    assert store.get(old) is None
    for i in range(5):
        store.add("text", str(i))
    store.prune(maximum=2)
    assert len(store.search()) == 2


def test_backup_restore_attachments_links_and_export(store, paths, tmp_path):
    paths.resolve("screenshots/image.png").write_bytes(b"original-image")
    image = store.add(
        "screenshot", "中文截图", "寄存器 0x09F0", file_path="screenshots/image.png"
    )
    note = store.add("note", "Markdown", "```c\nint value = 42;\n```")
    store.link(note, image)
    archive = tmp_path / "备份.zip"
    store.backup(str(archive))
    with zipfile.ZipFile(archive) as z:
        exported = json.loads(z.read("export/records.json"))
        assert len(exported) == 2
    extra = store.add("text", "not in backup")
    old = Path(store.restore(str(archive)))
    assert old.is_dir()
    assert store.get(extra) is None
    assert store.search("09F0")[0]["id"] == image
    assert store.links(note)[0]["id"] == image
    assert paths.resolve("screenshots/image.png").read_bytes() == b"original-image"
    assert (
        sqlite3.connect(old / "app.db")
        .execute("SELECT count(*) FROM records")
        .fetchone()[0]
        == 3
    )


@pytest.mark.parametrize(
    "name",
    ["../outside.txt", "/tmp/outside.txt", "screenshots/../../x", "C:\\evil.txt"],
)
def test_restore_rejects_unsafe_paths(store, tmp_path, name):
    rid = store.add("note", "keep me")
    archive = tmp_path / "evil.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr(name, "evil")
    with pytest.raises(ValueError):
        store.restore(str(archive))
    assert store.get(rid)


def test_missing_asset_backup_fails_without_destroying_existing_backup(
    store, paths, tmp_path
):
    store.add("image", "missing", file_path="clipboard_images/gone.png")
    dest = tmp_path / "keep.zip"
    dest.write_bytes(b"previous-backup")
    with pytest.raises(FileNotFoundError):
        store.backup(str(dest))
    assert dest.read_bytes() == b"previous-backup"


def test_path_traversal_and_settings_validation(paths):
    with pytest.raises(ValueError):
        paths.resolve("../secret")
    settings = Settings(paths)
    settings.update(theme="dark", monitor=False)
    assert Settings(paths).get("theme") == "dark"
    assert not Settings(paths).get("monitor")
    with pytest.raises(ValueError):
        settings.update(max_item_mb="bad")
    assert Settings(paths).get("max_item_mb") == 10


def test_newer_schema_is_not_overwritten(paths):
    con = sqlite3.connect(paths.db)
    con.execute("PRAGMA user_version=999")
    con.close()
    with pytest.raises(ValueError, match="更高版本"):
        Store(paths)


def test_abnormal_exit_rolls_back_uncommitted_change(store, paths):
    import subprocess
    import sys

    script = """import sqlite3,sys,os
con=sqlite3.connect(sys.argv[1])
con.execute("BEGIN IMMEDIATE")
con.execute("INSERT INTO records(id,kind,title,created_at,updated_at) VALUES('crash','text','not committed','2026-01-01','2026-01-01')")
os._exit(17)
"""
    process = subprocess.run([sys.executable, "-c", script, str(paths.db)])
    assert process.returncode == 17
    reopened = Store(paths)
    assert reopened.get("crash") is None
    with reopened.connect() as con:
        assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


@pytest.mark.parametrize(
    "text,kind,tag",
    [
        ("https://example.com", "url", "链接"),
        ("git status", "code", "代码"),
        ("#include <stdio.h>", "code", "代码"),
        ("0x09F0 error", "text", "寄存器"),
        ("C:\\project\\main.c", "text", "路径"),
    ],
)
def test_local_classification(text, kind, tag):
    found, tags = classify(text)
    assert found == kind and tag in tags
