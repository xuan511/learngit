from __future__ import annotations

import difflib
import json
import re
import shutil
import sqlite3
import tempfile
import uuid
import zipfile
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .paths import Paths

KINDS = {
    "text": "文本",
    "code": "代码",
    "url": "链接",
    "html": "网页",
    "files": "文件",
    "image": "图片",
    "screenshot": "截图",
    "note": "笔记",
    "pdf": "PDF",
    "snippet": "片段",
}
CLIP_KINDS = ("text", "code", "url", "html", "files", "image")


def now():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def classify(text: str):
    tags = []
    if re.search(r"\b0x[\da-fA-F]+\b", text):
        tags.append("寄存器")
    if re.search(r"https?://\S+", text):
        tags.append("链接")
    code = bool(
        re.search(
            r"(^|\n)\s*(def |class |#include|import |sudo |git |[\w:*<> ]+\([^\n]*\)\s*\{|\$ )",
            text,
        )
    )
    if code:
        tags.append("代码")
    if re.search(r"(?im)(error|exception|traceback|错误)", text):
        tags.append("日志")
    if re.search(r"(?:[A-Za-z]:\\|/(?:home|usr|etc|var)/)", text):
        tags.append("路径")
    kind = (
        "url"
        if re.fullmatch(r"https?://\S+", text.strip())
        else "code"
        if code
        else "text"
    )
    return kind, tags


class Store:
    def __init__(self, paths: Paths):
        self.paths = paths
        self.initialize()

    @contextmanager
    def connect(self):
        con = sqlite3.connect(self.paths.db, timeout=15)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys=ON")
        con.execute("PRAGMA busy_timeout=15000")
        try:
            with con:
                yield con
        finally:
            con.close()

    def initialize(self):
        with self.connect() as con:
            version = con.execute("PRAGMA user_version").fetchone()[0]
            if version > 1:
                raise ValueError("数据来自更高版本，请使用新版 SnapMind")
            con.execute("PRAGMA journal_mode=WAL")
            con.executescript("""
                CREATE TABLE IF NOT EXISTS records (
                    id TEXT PRIMARY KEY, kind TEXT NOT NULL, title TEXT NOT NULL,
                    body TEXT NOT NULL DEFAULT '', raw_ocr TEXT NOT NULL DEFAULT '',
                    notes TEXT NOT NULL DEFAULT '', tags TEXT NOT NULL DEFAULT '',
                    html TEXT NOT NULL DEFAULT '', file_path TEXT NOT NULL DEFAULT '',
                    external_path TEXT NOT NULL DEFAULT '',
                    favorite INTEGER NOT NULL DEFAULT 0, pinned INTEGER NOT NULL DEFAULT 0,
                    private INTEGER NOT NULL DEFAULT 0, fingerprint TEXT,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_fingerprint ON records(fingerprint) WHERE fingerprint IS NOT NULL;
                CREATE INDEX IF NOT EXISTS idx_kind_date ON records(kind, updated_at DESC);
                CREATE INDEX IF NOT EXISTS idx_favorites ON records(favorite, pinned, updated_at DESC);
                CREATE TABLE IF NOT EXISTS links (
                    source TEXT NOT NULL REFERENCES records(id) ON DELETE CASCADE,
                    target TEXT NOT NULL REFERENCES records(id) ON DELETE RESTRICT,
                    page INTEGER NOT NULL DEFAULT 0 CHECK(page>=0),
                    PRIMARY KEY(source,target), CHECK(source!=target)
                );
                CREATE VIRTUAL TABLE IF NOT EXISTS records_fts USING fts5(
                    title,body,raw_ocr,notes,tags,content='records',content_rowid='rowid',tokenize='unicode61'
                );
                CREATE TRIGGER IF NOT EXISTS records_ai AFTER INSERT ON records BEGIN
                    INSERT INTO records_fts(rowid,title,body,raw_ocr,notes,tags) VALUES(new.rowid,new.title,new.body,new.raw_ocr,new.notes,new.tags);
                END;
                CREATE TRIGGER IF NOT EXISTS records_ad AFTER DELETE ON records BEGIN
                    INSERT INTO records_fts(records_fts,rowid,title,body,raw_ocr,notes,tags) VALUES('delete',old.rowid,old.title,old.body,old.raw_ocr,old.notes,old.tags);
                END;
                CREATE TRIGGER IF NOT EXISTS records_au AFTER UPDATE ON records BEGIN
                    INSERT INTO records_fts(records_fts,rowid,title,body,raw_ocr,notes,tags) VALUES('delete',old.rowid,old.title,old.body,old.raw_ocr,old.notes,old.tags);
                    INSERT INTO records_fts(rowid,title,body,raw_ocr,notes,tags) VALUES(new.rowid,new.title,new.body,new.raw_ocr,new.notes,new.tags);
                END;
                PRAGMA user_version=1;
            """)

    def add(self, kind, title, body="", **fields):
        if kind not in KINDS:
            raise ValueError("未知记录类型")
        allowed = {
            "raw_ocr",
            "notes",
            "tags",
            "html",
            "file_path",
            "external_path",
            "favorite",
            "pinned",
            "private",
            "fingerprint",
        }
        if fields.keys() - allowed:
            raise ValueError("未知记录字段")
        if fields.get("file_path"):
            self.paths.resolve(fields["file_path"])
        record = dict(
            id=uuid.uuid4().hex,
            kind=kind,
            title=title[:300] or KINDS[kind],
            body=body,
            created_at=now(),
            updated_at=now(),
            **fields,
        )
        with self.connect() as con:
            fingerprint = fields.get("fingerprint")
            if fingerprint:
                old = con.execute(
                    "SELECT id FROM records WHERE fingerprint=?", (fingerprint,)
                ).fetchone()
                if old:
                    con.execute(
                        "UPDATE records SET updated_at=? WHERE id=?", (now(), old[0])
                    )
                    return old[0]
            columns = ",".join(record)
            con.execute(
                f"INSERT INTO records ({columns}) VALUES ({','.join('?' for _ in record)})",
                tuple(record.values()),
            )
        return record["id"]

    def get(self, record_id):
        with self.connect() as con:
            row = con.execute(
                "SELECT * FROM records WHERE id=?", (record_id,)
            ).fetchone()
            return dict(row) if row else None

    def update(self, record_id, **fields):
        allowed = {
            "title",
            "body",
            "raw_ocr",
            "notes",
            "tags",
            "favorite",
            "pinned",
            "private",
            "external_path",
        }
        if not fields or fields.keys() - allowed:
            raise ValueError("无效更新")
        fields["updated_at"] = now()
        with self.connect() as con:
            con.execute(
                f"UPDATE records SET {','.join(k + '=?' for k in fields)} WHERE id=?",
                (*fields.values(), record_id),
            )

    def apply_ocr(self, record_id, text):
        with self.connect() as con:
            con.execute("BEGIN IMMEDIATE")
            row = con.execute(
                "SELECT body,raw_ocr,tags FROM records WHERE id=?", (record_id,)
            ).fetchone()
            if row is None:
                return
            _, tags = classify(text)
            merged = ",".join(
                dict.fromkeys([t for t in row["tags"].split(",") if t] + tags)
            )
            body = (
                text
                if not row["body"] or row["body"] == row["raw_ocr"]
                else row["body"]
            )
            con.execute(
                "UPDATE records SET body=?,raw_ocr=?,tags=?,updated_at=? WHERE id=?",
                (body, text, merged, now(), record_id),
            )

    def search(
        self,
        query="",
        kinds=None,
        favorite=False,
        tag="",
        after="",
        before="",
        limit=60,
        offset=0,
        fuzzy=True,
        knowledge=False,
    ):
        limit, offset = min(max(int(limit), 1), 200), max(int(offset), 0)
        clauses, args = [], []
        if knowledge:
            clauses.append("(kind IN ('note','pdf') OR favorite=1)")
        if kinds:
            clauses.append(f"kind IN ({','.join('?' for _ in kinds)})")
            args.extend(kinds)
        if favorite:
            clauses.append("favorite=1")
        if tag:
            clauses.append("(',' || tags || ',') LIKE ? ESCAPE '\\'")
            args.append("%," + self.escape(tag.strip()) + ",%")
        if after:
            clauses.append("created_at>=?")
            args.append(after)
        if before:
            clauses.append("created_at<?")
            args.append(
                (datetime.fromisoformat(before) + timedelta(days=1)).isoformat()
            )
        base_clauses, base_args = list(clauses), list(args)
        tokens = query.strip().split()[:12]
        if tokens:
            # FTS indexes normal English words. LIKE covers Chinese substrings,
            # short queries, symbols and register fragments which unicode61 misses.
            exact_clauses = []
            for token in tokens:
                exact_clauses.append(
                    "(title || char(10) || body || char(10) || raw_ocr || char(10) || notes || char(10) || tags) LIKE ? ESCAPE '\\'"
                )
            fts = " AND ".join('"' + t.replace('"', '""') + '"' for t in tokens)
            clauses.append(
                "(rowid IN (SELECT rowid FROM records_fts WHERE records_fts MATCH ?) OR ("
                + " AND ".join(exact_clauses)
                + "))"
            )
            args.extend([fts, *["%" + self.escape(t) + "%" for t in tokens]])
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with self.connect() as con:
            rows = [
                dict(row)
                for row in con.execute(
                    "SELECT * FROM records"
                    + where
                    + " ORDER BY pinned DESC,updated_at DESC,id LIMIT ? OFFSET ?",
                    (*args, limit, offset),
                )
            ]
            if rows or not tokens or not fuzzy or offset:
                return rows
            base_where = " WHERE " + " AND ".join(base_clauses) if base_clauses else ""
            candidates = [
                dict(r)
                for r in con.execute(
                    "SELECT * FROM records"
                    + base_where
                    + " ORDER BY updated_at DESC LIMIT 1000",
                    base_args,
                )
            ]
            scored = []
            for r in candidates:
                words = re.findall(
                    r"[\w]+", r["title"] + " " + r["body"][:20000] + " " + r["tags"]
                )
                score = min(
                    (
                        max(
                            (
                                difflib.SequenceMatcher(
                                    None, t.casefold(), w.casefold()
                                ).ratio()
                                for w in words
                            ),
                            default=0,
                        )
                        for t in tokens
                    ),
                    default=0,
                )
                if score >= 0.79 and all(len(t) >= 4 for t in tokens):
                    scored.append((score, r))
            return [
                dict(r, fuzzy_match=True)
                for _, r in sorted(scored, key=lambda x: x[0], reverse=True)[:limit]
            ]

    @staticmethod
    def escape(value):
        return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

    def link(self, source, target, page=0):
        with self.connect() as con:
            con.execute(
                "INSERT INTO links(source,target,page) VALUES(?,?,?) ON CONFLICT(source,target) DO UPDATE SET page=excluded.page",
                (source, target, page),
            )

    def links(self, source):
        with self.connect() as con:
            return [
                dict(r)
                for r in con.execute(
                    "SELECT r.*,l.page FROM links l JOIN records r ON r.id=l.target WHERE l.source=?",
                    (source,),
                )
            ]

    def unlink(self, source, target):
        with self.connect() as con:
            con.execute(
                "DELETE FROM links WHERE source=? AND target=?", (source, target)
            )

    def delete(self, record_id):
        with self.connect() as con:
            row = con.execute(
                "SELECT file_path FROM records WHERE id=?", (record_id,)
            ).fetchone()
            try:
                con.execute("DELETE FROM records WHERE id=?", (record_id,))
            except sqlite3.IntegrityError as exc:
                raise ValueError("内容已被笔记关联，请先移除关联后再删除") from exc
            used = (
                row
                and row[0]
                and con.execute(
                    "SELECT 1 FROM records WHERE file_path=?", (row[0],)
                ).fetchone()
            )
        if row and row[0] and not used:
            self.paths.resolve(row[0]).unlink(missing_ok=True)

    def prune(self, days=30, maximum=5000, clear=False):
        cutoff = (datetime.now(timezone.utc) - timedelta(days=max(1, days))).isoformat()
        with self.connect() as con:
            placeholders = ",".join("?" for _ in CLIP_KINDS)
            eligible = f"kind IN ({placeholders}) AND favorite=0 AND pinned=0 AND id NOT IN (SELECT target FROM links)"
            if clear:
                ids = [
                    r[0]
                    for r in con.execute(
                        f"SELECT id FROM records WHERE {eligible}", CLIP_KINDS
                    )
                ]
            else:
                ids = [
                    r[0]
                    for r in con.execute(
                        f"SELECT id FROM records WHERE {eligible} AND created_at<?",
                        (*CLIP_KINDS, cutoff),
                    )
                ]
                ids += [
                    r[0]
                    for r in con.execute(
                        f"SELECT id FROM records WHERE {eligible} ORDER BY updated_at DESC LIMIT -1 OFFSET ?",
                        (*CLIP_KINDS, max(1, maximum)),
                    )
                ]
        for item in set(ids):
            self.delete(item)
        return len(set(ids))

    def backup(self, destination: str):
        destination = Path(destination).resolve()
        if (
            destination.is_relative_to(self.paths.data / "screenshots")
            or destination == self.paths.db
        ):
            raise ValueError("备份位置无效")
        with tempfile.TemporaryDirectory(prefix="snapmind-backup-") as tmp:
            snapshot = Path(tmp) / "app.db"
            with self.connect() as source:
                target = sqlite3.connect(snapshot)
                try:
                    source.backup(target)
                finally:
                    target.close()
            connection = sqlite3.connect(snapshot)
            try:
                records = [
                    dict(zip([c[0] for c in cursor.description], row))
                    for cursor in [connection.execute("SELECT * FROM records")]
                    for row in cursor
                ]
            finally:
                connection.close()
            pending = destination.with_suffix(
                destination.suffix + ".tmp-" + uuid.uuid4().hex
            )
            try:
                with zipfile.ZipFile(pending, "w", zipfile.ZIP_DEFLATED) as z:
                    z.write(snapshot, "app.db")
                    z.writestr(
                        "manifest.json",
                        json.dumps(
                            {"format": 1, "created_at": now(), "records": len(records)}
                        ),
                    )
                    z.writestr(
                        "export/records.json",
                        json.dumps(records, ensure_ascii=False, indent=2),
                    )
                    for relative in {r["file_path"] for r in records if r["file_path"]}:
                        path = self.paths.resolve(relative)
                        if not path.is_file():
                            raise FileNotFoundError(f"附件缺失，备份已取消：{relative}")
                        z.write(path, relative)
                pending.replace(destination)
            finally:
                pending.unlink(missing_ok=True)
        return str(destination)

    def restore(self, archive: str):
        # Called only with queues idle; validate everything before replacing data.
        with tempfile.TemporaryDirectory(prefix="restore-", dir=self.paths.root) as tmp:
            staging = Path(tmp)
            with zipfile.ZipFile(archive) as z:
                if sum(i.file_size for i in z.infolist()) > 4 * 1024**3:
                    raise ValueError("备份解压大小超过 4 GB")
                if len(z.namelist()) != len(set(z.namelist())):
                    raise ValueError("备份含重复路径")
                for info in z.infolist():
                    dest = (staging / info.filename).resolve()
                    if (
                        "\\" in info.filename
                        or ":" in info.filename
                        or not dest.is_relative_to(staging)
                        or (info.external_attr >> 16) & 0o170000 == 0o120000
                    ):
                        raise ValueError("不安全的备份路径")
                    first = (
                        Path(info.filename).parts[0]
                        if Path(info.filename).parts
                        else ""
                    )
                    if first not in {
                        "app.db",
                        "manifest.json",
                        "export",
                        "screenshots",
                        "clipboard_images",
                        "documents",
                    }:
                        raise ValueError("未知备份文件")
                z.extractall(staging)
            manifest = json.loads((staging / "manifest.json").read_text())
            if manifest.get("format") != 1:
                raise ValueError("备份版本不受支持")
            con = sqlite3.connect(staging / "app.db")
            try:
                if (
                    con.execute("PRAGMA integrity_check").fetchone()[0] != "ok"
                    or con.execute("PRAGMA user_version").fetchone()[0] != 1
                ):
                    raise ValueError("备份数据库无效")
                if con.execute("PRAGMA foreign_key_check").fetchall():
                    raise ValueError("备份关联关系损坏")
                con.execute(
                    "SELECT id,kind,title,body,raw_ocr,notes,tags,html,file_path,external_path,favorite,pinned,private,fingerprint,created_at,updated_at FROM records LIMIT 0"
                )
                con.execute("SELECT source,target,page FROM links LIMIT 0")
                if con.execute("SELECT count(*) FROM records").fetchone()[
                    0
                ] != manifest.get("records"):
                    raise ValueError("备份记录数与清单不符")
                for (relative,) in con.execute(
                    "SELECT file_path FROM records WHERE file_path!=''"
                ):
                    path = (staging / relative).resolve()
                    if (
                        not path.is_relative_to(staging)
                        or not path.is_file()
                        or Path(relative).parts[0]
                        not in {"screenshots", "clipboard_images", "documents"}
                    ):
                        raise ValueError("备份附件不完整")
                # Force FTS to read all index pages before installing the database.
                con.execute(
                    "INSERT INTO records_fts(records_fts,rank) VALUES('integrity-check',1)"
                )
            finally:
                con.close()
            old = self.paths.root / ("data-before-restore-" + uuid.uuid4().hex)
            with self.connect() as con:
                con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            self.paths.data.rename(old)
            try:
                staging.rename(self.paths.data)
                self.initialize()
            except Exception:
                shutil.rmtree(self.paths.data, ignore_errors=True)
                old.rename(self.paths.data)
                raise
            # Preserve a recoverable copy until the user explicitly removes it.
            for folder in ("screenshots", "clipboard_images", "documents", "backups"):
                (self.paths.data / folder).mkdir(exist_ok=True)
            return str(old)
