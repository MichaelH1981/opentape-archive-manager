"""Node-local accounts. Credentials are never replicated with catalog snapshots."""

from __future__ import annotations

import re
import sqlite3
import time
import uuid

from fastapi import HTTPException

from ..common import SafetyError
from .config import password_hash, password_matches
from .control import Control

ROLES = {"admin", "operator", "viewer"}
LOCALES = {"de", "en"}
USERNAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{2,63}\Z")


def public(row: sqlite3.Row | dict) -> dict:
    return {
        "id": row["id"],
        "username": row["username"],
        "role": row["role"],
        "enabled": bool(row["enabled"]),
        "locale": row["locale"],
        "mfa_state": row["mfa_state"],
        "created": row["created"],
        "updated": row["updated"],
    }


def bootstrap(control: Control, username: str, encoded_password: str) -> None:
    """Import the preexisting config administrator only on first startup."""
    with control.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        if db.execute("SELECT 1 FROM users LIMIT 1").fetchone():
            return
        now = time.time()
        db.execute(
            "INSERT INTO users VALUES(?,?,?,?,?,?,?,?,?)",
            (str(uuid.uuid4()), username, encoded_password, "admin", 1, "de", "disabled", now, now),
        )


def list_users(control: Control) -> list[dict]:
    with control.connect() as db:
        return [public(row) for row in db.execute("SELECT * FROM users ORDER BY username COLLATE NOCASE")]


def create_user(control: Control, username: str, password: str, role: str) -> dict:
    if not USERNAME.fullmatch(username) or role not in ROLES:
        raise SafetyError("Ungültiger Benutzername oder Rolle")
    encoded = password_hash(password)
    now = time.time()
    with control.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        if db.execute("SELECT count(*) FROM users").fetchone()[0] >= 100:
            raise SafetyError("Maximal 100 lokale Benutzer")
        ident = str(uuid.uuid4())
        try:
            db.execute(
                "INSERT INTO users VALUES(?,?,?,?,?,?,?,?,?)",
                (ident, username, encoded, role, 1, "de", "disabled", now, now),
            )
        except sqlite3.IntegrityError as error:
            raise HTTPException(409, "Benutzername bereits vergeben") from error
        return public(db.execute("SELECT * FROM users WHERE id=?", (ident,)).fetchone())


def update_user(
    control: Control, ident: str, *, role: str | None = None,
    enabled: bool | None = None, password: str | None = None,
) -> dict:
    if role is not None and role not in ROLES:
        raise SafetyError("Ungültige Rolle")
    if role is None and enabled is None and password is None:
        raise SafetyError("Keine Änderung angegeben")
    encoded = password_hash(password) if password is not None else None
    with control.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        old = db.execute("SELECT * FROM users WHERE id=?", (ident,)).fetchone()
        if old is None:
            raise HTTPException(404, "Benutzer nicht gefunden")
        next_role = role if role is not None else old["role"]
        next_enabled = int(enabled) if enabled is not None else old["enabled"]
        if old["role"] == "admin" and old["enabled"] and (
            next_role != "admin" or not next_enabled
        ):
            admins = db.execute(
                "SELECT count(*) FROM users WHERE role='admin' AND enabled=1"
            ).fetchone()[0]
            if admins <= 1:
                raise SafetyError("Der letzte aktive Administrator darf nicht deaktiviert werden")
        db.execute(
            "UPDATE users SET role=?,enabled=?,password_hash=COALESCE(?,password_hash),updated=? WHERE id=?",
            (next_role, next_enabled, encoded, time.time(), ident),
        )
        if encoded is not None or not next_enabled or next_role != old["role"]:
            db.execute("DELETE FROM sessions WHERE user_id=?", (ident,))
        return public(db.execute("SELECT * FROM users WHERE id=?", (ident,)).fetchone())


def set_locale(control: Control, ident: str, locale: str) -> dict:
    if locale not in LOCALES:
        raise SafetyError("Nicht unterstützte Sprache")
    with control.connect() as db:
        db.execute("UPDATE users SET locale=?,updated=? WHERE id=?", (locale, time.time(), ident))
        row = db.execute("SELECT * FROM users WHERE id=?", (ident,)).fetchone()
    if row is None:
        raise HTTPException(404, "Benutzer nicht gefunden")
    return public(row)


def change_own_password(
    control: Control, ident: str, old_password: str, new_password: str,
    keep_session_hash: str,
) -> None:
    encoded = password_hash(new_password)
    with control.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT password_hash FROM users WHERE id=?", (ident,)).fetchone()
        if row is None or not password_matches(old_password, row[0]):
            raise HTTPException(403, "Aktuelles Passwort ungültig")
        db.execute("UPDATE users SET password_hash=?,updated=? WHERE id=?", (encoded, time.time(), ident))
        db.execute("DELETE FROM sessions WHERE user_id=? AND hash!=?", (ident, keep_session_hash))
