"""Session authentication, CSRF and bounded JSON requests."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from urllib.parse import urlsplit

from fastapi import HTTPException, Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from .config import WebConfig, password_matches
from .control import Control


def cookie_name(config: WebConfig) -> str:
    return (
        ("__Host-" if config.secure_cookie else "")
        + "otam_"
        + config.node_id.replace("-", "")
    )


class SecurityMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            if request.url.path != "/api/v1/replication/snapshot":
                try:
                    length = int(request.headers.get("content-length", "-1"))
                except ValueError:
                    return JSONResponse(
                        {"error": "Ungültige Anfragegröße"}, status_code=400
                    )
                if length < 0 or length > 65536:
                    return JSONResponse(
                        {
                            "error": "JSON-Anfragen benötigen Content-Length und höchstens 64 KiB"
                        },
                        status_code=413,
                    )
                origin = request.headers.get("origin")
                if origin:
                    parsed = urlsplit(origin)
                    if (
                        parsed.scheme != request.url.scheme
                        or parsed.netloc.lower()
                        != request.headers.get("host", "").lower()
                    ):
                        return JSONResponse(
                            {"error": "Fremde Origin verweigert"}, status_code=403
                        )
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        )
        response.headers["Cache-Control"] = (
            "no-store" if request.url.path.startswith("/api/") else "no-cache"
        )
        return response


def session(request: Request) -> dict:
    control: Control = request.app.state.control
    value = request.cookies.get(cookie_name(request.app.state.config), "")
    if not value or len(value) > 256:
        raise HTTPException(401, "Bitte anmelden")
    hashed = hashlib.sha256(value.encode()).hexdigest()
    with control.connect() as db:
        row = db.execute(
            """SELECT s.hash,s.csrf,s.expires,s.user_id,
                      u.username,u.role,u.locale,u.mfa_state
               FROM sessions s JOIN users u ON u.id=s.user_id
               WHERE s.hash=? AND s.expires>? AND u.enabled=1 AND u.mfa_state='disabled'""",
            (hashed, time.time()),
        ).fetchone()
    if row is None:
        raise HTTPException(401, "Sitzung abgelaufen; bitte erneut anmelden")
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        if not hmac.compare_digest(
            request.headers.get("x-csrf-token", "").encode(), row["csrf"].encode()
        ):
            raise HTTPException(403, "CSRF-Prüfung fehlgeschlagen")
        if row["role"] == "viewer" and request.url.path not in {
            "/api/v1/logout", "/api/v1/account/locale", "/api/v1/account/password"
        }:
            raise HTTPException(403, "Nur lesender Zugriff")
    return dict(row)


def require_admin(request: Request) -> dict:
    current = session(request)
    if current["role"] != "admin":
        raise HTTPException(403, "Administratorrechte erforderlich")
    return current


def login(
    config: WebConfig, control: Control, username: str, password: str, ip: str
) -> tuple[str, str, dict]:
    now = time.time()
    with control.connect() as db:
        db.execute("DELETE FROM attempts WHERE time<?", (now - 900,))
        if (
            db.execute("SELECT count(*) FROM attempts WHERE ip=?", (ip,)).fetchone()[0]
            >= 10
        ):
            raise HTTPException(
                429, "Zu viele Anmeldeversuche; nach 15 Minuten erneut versuchen"
            )
        db.execute("INSERT INTO attempts VALUES(?,?)", (ip, now))
    with control.connect() as db:
        user = db.execute("SELECT * FROM users WHERE username=? COLLATE NOCASE", (username,)).fetchone()
    valid = password_matches(password, user["password_hash"] if user else config.password)
    if not valid or user is None or not user["enabled"]:
        raise HTTPException(401, "Benutzername oder Passwort ungültig")
    # An unsupported future factor must never silently fall back to password-only.
    if user["mfa_state"] != "disabled":
        raise HTTPException(403, "Zusätzlicher Anmeldefaktor wird noch nicht unterstützt")
    token = secrets.token_urlsafe(48)
    csrf = secrets.token_urlsafe(32)
    with control.connect() as db:
        db.execute("DELETE FROM attempts WHERE ip=?", (ip,))
        db.execute("DELETE FROM sessions WHERE expires<?", (now,))
        db.execute(
            "INSERT INTO sessions VALUES(?,?,?,?)",
            (
                hashlib.sha256(token.encode()).hexdigest(),
                csrf,
                now + config.session_seconds,
                user["id"],
            ),
        )
    return token, csrf, {
        "id": user["id"], "username": user["username"],
        "role": user["role"], "locale": user["locale"],
        "mfa_state": user["mfa_state"],
    }
