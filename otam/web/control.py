"""Private control database: sessions, command queue and replication pointers."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from ..common import SafetyError


def boot_id() -> str:
    path = Path("/proc/sys/kernel/random/boot_id")
    return path.read_text().strip() if path.is_file() else "non-linux-test-boot"


def current_shutdown(value: dict[str, Any]) -> bool:
    stamp = value.get("time")
    return (value.get("boot_id") == boot_id()
            and type(stamp) in (int, float)
            and 0 <= time.time() - stamp <= 120)

CONTROL_SCHEMA = """
CREATE TABLE IF NOT EXISTS commands(
 id TEXT PRIMARY KEY, kind TEXT NOT NULL, state TEXT NOT NULL,
 created REAL NOT NULL, updated REAL NOT NULL, payload TEXT NOT NULL,
 result TEXT, error TEXT, idempotency TEXT UNIQUE);
CREATE TABLE IF NOT EXISTS users(
 id TEXT PRIMARY KEY, username TEXT NOT NULL UNIQUE COLLATE NOCASE,
 password_hash TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('admin','operator','viewer')),
 enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0,1)),
 locale TEXT NOT NULL DEFAULT 'de' CHECK(locale IN ('de','en')),
 mfa_state TEXT NOT NULL DEFAULT 'disabled',
 created REAL NOT NULL, updated REAL NOT NULL);
CREATE TABLE IF NOT EXISTS sessions(
 hash TEXT PRIMARY KEY, csrf TEXT NOT NULL, expires REAL NOT NULL,
 user_id TEXT NOT NULL REFERENCES users(id));
CREATE TABLE IF NOT EXISTS attempts(ip TEXT NOT NULL,time REAL NOT NULL);
CREATE TABLE IF NOT EXISTS resources(id TEXT PRIMARY KEY,path TEXT NOT NULL UNIQUE);
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sync_log(
 id INTEGER PRIMARY KEY, time REAL NOT NULL, direction TEXT NOT NULL,
 state TEXT NOT NULL, sequence INTEGER, details TEXT NOT NULL);
PRAGMA user_version=2;
"""


class Control:
    def __init__(self, state: Path):
        state.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = state / "control.sqlite"
        with self.connect() as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1, 2):
                raise SafetyError("Unbekannte Steuerdatenbank-Version")
            if version == 0:
                db.executescript(CONTROL_SCHEMA)
            elif version == 1:
                # Old sessions have no user identity. Invalidate them rather than
                # silently assigning elevated privileges during migration.
                db.execute("BEGIN IMMEDIATE")
                db.execute("""CREATE TABLE users(
                    id TEXT PRIMARY KEY, username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL CHECK(role IN ('admin','operator','viewer')),
                    enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0,1)),
                    locale TEXT NOT NULL DEFAULT 'de' CHECK(locale IN ('de','en')),
                    mfa_state TEXT NOT NULL DEFAULT 'disabled',
                    created REAL NOT NULL, updated REAL NOT NULL)""")
                db.execute("DROP TABLE sessions")
                db.execute("""CREATE TABLE sessions(
                    hash TEXT PRIMARY KEY, csrf TEXT NOT NULL, expires REAL NOT NULL,
                    user_id TEXT NOT NULL REFERENCES users(id))""")
                db.execute("PRAGMA user_version=2")

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA synchronous=FULL")
        db.execute("PRAGMA journal_mode=WAL")
        try:
            with db:
                yield db
        finally:
            db.close()

    def get(self, key: str, default: Any = None) -> Any:
        with self.connect() as db:
            row = db.execute(
                "SELECT value FROM settings WHERE key=?", (key,)
            ).fetchone()
            return json.loads(row[0]) if row else default

    def set(self, key: str, value: Any) -> None:
        with self.connect() as db:
            db.execute(
                "INSERT INTO settings VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, json.dumps(value)),
            )

    def next_sequence(self) -> int:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT value FROM settings WHERE key='outgoing_sequence'"
            ).fetchone()
            n = int(json.loads(row[0])) + 1 if row else 1
            db.execute(
                "INSERT INTO settings VALUES('outgoing_sequence',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (str(n),),
            )
            return n

    def shutdown_pending(self) -> bool:
        return current_shutdown(self.get("shutdown_pending", {}))

    def begin_shutdown(self, user_id: str) -> dict[str, Any]:
        request = {"id": str(uuid.uuid4()), "boot_id": boot_id(),
                   "user_id": user_id, "time": time.time()}
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT value FROM settings WHERE key='shutdown_pending'").fetchone()
            if row and current_shutdown(json.loads(row[0])):
                raise SafetyError("Herunterfahren wurde bereits angefordert")
            busy = db.execute("""SELECT 1 FROM commands WHERE state='RUNNING'
                OR (state='QUEUED' AND COALESCE(idempotency,'') NOT LIKE 'scheduled-%')
                LIMIT 1""").fetchone()
            if busy:
                raise SafetyError("Ein OTAM-Auftrag läuft oder wartet; Herunterfahren gesperrt")
            db.execute(
                """INSERT INTO settings VALUES('shutdown_pending',?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value""",
                (json.dumps(request),),
            )
        return request

    def clear_shutdown(self, request_id: str) -> None:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT value FROM settings WHERE key='shutdown_pending'").fetchone()
            if row and json.loads(row[0]).get("id") == request_id:
                db.execute("DELETE FROM settings WHERE key='shutdown_pending'")

    def enqueue(self, kind: str, payload: dict[str, Any], key: str) -> dict[str, Any]:
        if not 8 <= len(key) <= 128:
            raise SafetyError("Idempotency-Key muss 8–128 Zeichen enthalten")
        serialized = json.dumps(payload, sort_keys=True)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            pending = db.execute("SELECT value FROM settings WHERE key='shutdown_pending'").fetchone()
            if pending and current_shutdown(json.loads(pending[0])):
                raise SafetyError("Herunterfahren läuft; neue Aufträge sind gesperrt")
            old = db.execute(
                "SELECT * FROM commands WHERE idempotency=?", (key,)
            ).fetchone()
            if old:
                if old["kind"] != kind or old["payload"] != serialized:
                    raise SafetyError(
                        "Idempotency-Key bereits für einen anderen Auftrag verwendet"
                    )
                return dict(old)
            ident = str(uuid.uuid4())
            now = time.time()
            db.execute(
                "INSERT INTO commands VALUES(?,?, 'QUEUED',?,?,?,?,NULL,?)",
                (ident, kind, now, now, serialized, None, key),
            )
            return dict(
                db.execute("SELECT * FROM commands WHERE id=?", (ident,)).fetchone()
            )

    def commands(self, limit: int = 100) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = [
                dict(r)
                for r in db.execute(
                    "SELECT * FROM commands ORDER BY created DESC LIMIT ?", (limit,)
                )
            ]
        for row in rows:
            for key in ("payload", "result"):
                if row[key] is not None:
                    row[key] = json.loads(row[key])
        return rows

    def interrupt_running(self) -> None:
        with self.connect() as db:
            db.execute(
                "UPDATE commands SET state='INTERRUPTED',updated=?,error='Worker wurde unterbrochen; Zustand und Medium vor Wiederaufnahme prüfen' WHERE state='RUNNING'",
                (time.time(),),
            )

    def claim(self) -> dict[str, Any] | None:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            pending = db.execute("SELECT value FROM settings WHERE key='shutdown_pending'").fetchone()
            if pending and current_shutdown(json.loads(pending[0])):
                return None
            row = db.execute(
                "SELECT * FROM commands WHERE state='QUEUED' ORDER BY created,id LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            db.execute(
                "UPDATE commands SET state='RUNNING',updated=? WHERE id=?",
                (time.time(), row["id"]),
            )
            result = dict(row)
            result["payload"] = json.loads(row["payload"])
            return result

    def complete(
        self, ident: str, result: Any = None, error: str | None = None
    ) -> None:
        with self.connect() as db:
            db.execute(
                "UPDATE commands SET state=?,updated=?,result=?,error=? WHERE id=?",
                (
                    "FAILED" if error else "SUCCEEDED",
                    time.time(),
                    json.dumps(result),
                    error,
                    ident,
                ),
            )

    def resource(self, ident: str) -> Path:
        with self.connect() as db:
            row = db.execute(
                "SELECT path FROM resources WHERE id=?", (ident,)
            ).fetchone()
        if row is None:
            raise SafetyError("Medium ist auf diesem Node nicht eingebunden")
        return Path(row[0])

    def register(self, ident: str, path: Path) -> None:
        with self.connect() as db:
            db.execute(
                "INSERT INTO resources VALUES(?,?) ON CONFLICT(id) DO NOTHING",
                (ident, str(path)),
            )

    def sync_event(
        self, direction: str, state: str, sequence: int | None, details: str
    ) -> None:
        with self.connect() as db:
            db.execute(
                "INSERT INTO sync_log(time,direction,state,sequence,details) VALUES(?,?,?,?,?)",
                (time.time(), direction, state, sequence, details),
            )
