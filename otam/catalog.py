"""Versioned SQLite catalog; media is the recovery source of truth."""
from __future__ import annotations

import json
from contextlib import nullcontext
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any

from .common import SafetyError, encode

SCHEMA = """
CREATE TABLE media (
 id TEXT PRIMARY KEY, label TEXT NOT NULL, class TEXT NOT NULL,
 generation INTEGER NOT NULL DEFAULT 4, capacity INTEGER NOT NULL,
 manufacturer TEXT, serial TEXT, first_use REAL, last_use REAL,
 writes INTEGER NOT NULL DEFAULT 0, last_verified REAL,
 location TEXT NOT NULL DEFAULT '', state TEXT NOT NULL DEFAULT 'READY',
 used INTEGER NOT NULL DEFAULT 0, header_json TEXT NOT NULL
);
CREATE TABLE jobs (
 id TEXT PRIMARY KEY, kind TEXT NOT NULL, state TEXT NOT NULL,
 media_id TEXT REFERENCES media(id), created REAL NOT NULL,
 updated REAL NOT NULL, plan_json TEXT, report_json TEXT, error TEXT
);
CREATE TABLE archives (
 id TEXT PRIMARY KEY, media_id TEXT NOT NULL REFERENCES media(id),
 job_id TEXT REFERENCES jobs(id), tape_file INTEGER NOT NULL,
 state TEXT NOT NULL, bytes INTEGER, sha256 TEXT, created REAL NOT NULL,
 manifest_json TEXT NOT NULL, UNIQUE(media_id,tape_file)
);
CREATE TABLE files (
 archive_id TEXT NOT NULL REFERENCES archives(id), path TEXT NOT NULL,
 name TEXT NOT NULL, size INTEGER NOT NULL, mtime_ns INTEGER NOT NULL,
 type TEXT NOT NULL, sha256 TEXT NOT NULL, tar_offset INTEGER,
 PRIMARY KEY(archive_id,path)
);
CREATE INDEX files_hash ON files(sha256);
CREATE INDEX files_name ON files(name);
CREATE INDEX files_size ON files(size);
CREATE TABLE events (
 seq INTEGER PRIMARY KEY, job_id TEXT REFERENCES jobs(id),
 time REAL NOT NULL, level TEXT NOT NULL, event TEXT NOT NULL, details_json TEXT NOT NULL
);
CREATE TABLE verifications (
 id TEXT PRIMARY KEY, job_id TEXT REFERENCES jobs(id), archive_id TEXT REFERENCES archives(id),
 time REAL NOT NULL, state TEXT NOT NULL, error TEXT
);
CREATE TABLE restores (
 id TEXT PRIMARY KEY, job_id TEXT REFERENCES jobs(id), target TEXT NOT NULL,
 selection_json TEXT NOT NULL, state TEXT NOT NULL
);
PRAGMA user_version=1;
"""


MIGRATION_2 = """
ALTER TABLE jobs ADD COLUMN phase TEXT;
CREATE TABLE staged_archives (
 job_id TEXT NOT NULL REFERENCES jobs(id), archive_id TEXT NOT NULL,
 root TEXT, phase TEXT NOT NULL DEFAULT 'INVENTORY', state TEXT NOT NULL DEFAULT 'PENDING',
 path TEXT, sha256 TEXT, bytes INTEGER, fingerprint_json TEXT,
 progress_bytes INTEGER NOT NULL DEFAULT 0, total_bytes INTEGER NOT NULL,
 updated REAL NOT NULL, error TEXT, PRIMARY KEY(job_id,archive_id)
);
CREATE TABLE staging_artifacts (
 job_id TEXT NOT NULL, archive_id TEXT NOT NULL, name TEXT NOT NULL,
 device INTEGER NOT NULL, inode INTEGER NOT NULL,
 PRIMARY KEY(job_id,archive_id,name),
 FOREIGN KEY(job_id,archive_id) REFERENCES staged_archives(job_id,archive_id)
);
CREATE TABLE storage_benchmarks (
 id TEXT PRIMARY KEY, time REAL NOT NULL, root TEXT NOT NULL, report_json TEXT NOT NULL
);
PRAGMA user_version=2;
"""


class Catalog:
    def __init__(self, path: Path):
        self.path = path.resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, timeout=10)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        version = self.db.execute("PRAGMA user_version").fetchone()[0]
        if version > 2:
            self.db.close()
            raise SafetyError("Catalog schema is newer than this application")
        if version == 0:
            self.db.executescript("BEGIN IMMEDIATE;\n" + SCHEMA + "\nCOMMIT;")
        if version < 2:
            self.db.executescript("BEGIN IMMEDIATE;\n" + MIGRATION_2 + "\nCOMMIT;")

    def close(self) -> None:
        self.db.close()

    def interrupt_unfinished(self, media: str | None = None) -> int:
        """Record process loss locally; never infer a safe tape position or resume.

        Call only after obtaining exclusive ownership of the executor/catalog.
        This deliberately preserves staged files, hashes and pending markers.
        Physical inspection is still required before any recovery or append.
        """
        reason = "Process ended without a terminal result; inspect medium"
        now = time.time()
        scope, args = ("", ()) if media is None else (" AND media_id=?", (media,))
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            rows = self.db.execute(
                "SELECT id FROM jobs WHERE state IN ('RUNNING','PLANNING')" + scope, args
            ).fetchall()
            for row in rows:
                self.db.execute("UPDATE jobs SET state='INTERRUPTED',updated=?,error=? WHERE id=?",
                                (now, reason, row["id"]))
                self.db.execute("INSERT INTO events(job_id,time,level,event,details_json) VALUES(?,?,?,?,?)",
                                (row["id"], now, "ERROR", "job_interrupted",
                                 encode({"state": "INTERRUPTED", "error": reason,
                                         "automatic_resume": False}).decode()))
            self.db.execute("UPDATE archives SET state='INCOMPLETE' WHERE state='WRITING'" + scope, args)
            self.db.execute("UPDATE media SET state='SUSPECT' WHERE id IN "
                            "(SELECT media_id FROM archives WHERE state='INCOMPLETE'" + scope + ")", args)
            self.db.execute("UPDATE restores SET state='INTERRUPTED' WHERE state='RUNNING' AND job_id IN "
                            "(SELECT id FROM jobs WHERE state='INTERRUPTED'" + scope + ")", args)
            self.db.execute("UPDATE staged_archives SET state='INTERRUPTED',updated=?,error=? "
                            "WHERE state='RUNNING' AND job_id IN "
                            "(SELECT id FROM jobs WHERE state='INTERRUPTED'" + scope + ")",
                            (now, "Process ended; phase must be rechecked", *args))
        return len(rows)

    def event(self, job: str, event: str, level: str = "INFO", **details: Any) -> None:
        with self.db:
            self.db.execute("INSERT INTO events(job_id,time,level,event,details_json) VALUES(?,?,?,?,?)",
                            (job, time.time(), level, event, encode(details).decode()))

    def job(self, kind: str, media: str | None, state: str = "RUNNING", plan: Any = None) -> str:
        ident = str(uuid.uuid4())
        now = time.time()
        with self.db:
            self.db.execute("INSERT INTO jobs(id,kind,state,media_id,created,updated,plan_json) VALUES(?,?,?,?,?,?,?)",
                            (ident, kind, state, media, now, now,
                             encode(plan).decode() if plan is not None else None))
        self.event(ident, "job_created", kind=kind, state=state)
        return ident

    def finish(self, job: str, state: str, error: str | None = None, report: Any = None) -> None:
        with self.db:
            self.db.execute("UPDATE jobs SET state=?,updated=?,error=?,report_json=? WHERE id=?",
                            (state, time.time(), error, encode(report).decode(), job))
        self.event(job, "job_finished", "ERROR" if error else "INFO", state=state, error=error)

    def register(self, header: dict[str, Any], used: int) -> None:
        with self.db:
            old = self.db.execute("SELECT header_json FROM media WHERE id=?", (header["media_id"],)).fetchone()
            if old and json.loads(old[0]) != header:
                raise SafetyError("Media header conflicts with catalog")
            self.db.execute("""INSERT INTO media(id,label,class,capacity,header_json,used)
                VALUES(?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET used=excluded.used""",
                            (header["media_id"], header["label"], header["class"], header["capacity"],
                             encode(header).decode(), used))

    def record_archive(self, manifest: dict[str, Any], job: str, position: int,
                       state: str, size: int | None = None, checksum: str | None = None,
                       *, transaction: bool = True) -> None:
        old = self.db.execute("SELECT media_id,tape_file,manifest_json FROM archives WHERE id=?",
                              (manifest["archive_id"],)).fetchone()
        if old and (old["media_id"] != manifest["media_id"] or old["tape_file"] != position
                    or json.loads(old["manifest_json"]) != manifest):
            raise SafetyError("Archive identity conflicts with existing catalog")
        with (self.db if transaction else nullcontext()):
            self.db.execute("""INSERT INTO archives(id,media_id,job_id,tape_file,state,bytes,sha256,created,manifest_json)
                VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
                state=excluded.state,bytes=excluded.bytes,sha256=excluded.sha256""",
                            (manifest["archive_id"], manifest["media_id"], job, position, state, size,
                             checksum, manifest["created"], encode(manifest).decode()))
            for entry in manifest["files"]:
                self.db.execute("""INSERT OR IGNORE INTO files
                    (archive_id,path,name,size,mtime_ns,type,sha256) VALUES(?,?,?,?,?,?,?)""",
                                (manifest["archive_id"], entry["path"], Path(entry["path"]).name,
                                 entry["size"], entry["mtime_ns"], entry["type"], entry["sha256"]))

    def search(self, query: str = "", checksum: str | None = None) -> list[dict[str, Any]]:
        sql = """SELECT f.*,a.media_id,a.tape_file,a.state,a.created FROM files f
            JOIN archives a ON a.id=f.archive_id WHERE instr(f.path,?)>0"""
        args: list[Any] = [query]
        if checksum:
            sql += " AND f.sha256=?"
            args.append(checksum)
        return [dict(row) for row in self.db.execute(sql + " ORDER BY f.path,a.created", args)]

    def export(self) -> dict[str, Any]:
        return {"schema_version": 2, **{table: [dict(r) for r in self.db.execute(f"SELECT * FROM {table}")]
                for table in ("media", "archives", "files", "jobs", "events", "verifications", "restores", "staged_archives", "staging_artifacts", "storage_benchmarks")}}
