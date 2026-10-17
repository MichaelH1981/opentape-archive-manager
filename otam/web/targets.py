"""Optional publication destinations. The primary catalog is never a target."""

from __future__ import annotations

import uuid
from pathlib import Path
from urllib.parse import urlsplit
from typing import Any

from ..common import SafetyError
from .config import WebConfig
from .control import Control

REGISTRY = "publication_targets"


def targets(config: WebConfig, control: Control) -> list[dict[str, Any]]:
    configured = control.get(REGISTRY)
    if configured is not None:
        return configured
    # Legacy node files remain usable until the first explicit UI configuration.
    result = []
    for kind, address in (
        ("catalog", config.peer_url),
        ("directory", config.nas_backup),
    ):
        if address:
            result.append(
                dict(
                    id="legacy-" + kind,
                    label=(
                        "Katalogdienst" if kind == "catalog" else "Snapshot-Verzeichnis"
                    ),
                    kind=kind,
                    address=str(address),
                    enabled=True,
                    interval=config.sync_interval,
                    allow_http=config.allow_http_peer,
                    key_file=str(config.peer_key_file),
                    revision=1,
                )
            )
    return result


def enabled_targets(config: WebConfig, control: Control) -> list[dict[str, Any]]:
    return [t for t in targets(config, control) if t["enabled"]]


def public_targets(config: WebConfig, control: Control) -> list[dict[str, Any]]:
    result = []
    for t in targets(config, control):
        status = control.get("target_status:" + t["id"])
        if status and status.get("revision") != t["revision"]:
            status = None
        result.append(
            {k: v for k, v in t.items() if k not in ("key", "key_file")}
            | {
                "key_configured": bool(t.get("key") or t.get("key_file")),
                "status": status,
            }
        )
    return result


def key_for(config: WebConfig, target: dict[str, Any]) -> bytes:
    if target.get("key_file"):
        from dataclasses import replace

        return replace(config, peer_key_file=Path(target["key_file"])).peer_key()
    return target["key"].encode("ascii")


def save_target(
    config: WebConfig, control: Control, ident: str, data: dict[str, Any]
) -> None:
    if config.role != "archive":
        raise SafetyError("Nur Archive Nodes verwalten Veröffentlichungsziele")
    if ident not in ("legacy-catalog", "legacy-directory"):
        uuid.UUID(ident)
    allowed = {"label", "kind", "address", "enabled", "interval", "allow_http", "key"}
    if set(data) - allowed:
        raise SafetyError("Unbekannte Zielparameter")
    current = targets(config, control)
    old = next((t for t in current if t["id"] == ident), {})
    t = {**old, **data, "id": ident, "revision": old.get("revision", 0) + 1}
    if t.get("kind") not in ("catalog", "directory"):
        raise SafetyError("Zieltyp muss Katalogdienst oder Snapshot-Verzeichnis sein")
    if not isinstance(t.get("label"), str) or not 1 <= len(t["label"].strip()) <= 100:
        raise SafetyError("Ziel benötigt eine Bezeichnung (1–100 Zeichen)")
    if (
        type(t.get("enabled")) is not bool
        or type(t.get("allow_http", False)) is not bool
    ):
        raise SafetyError("Aktivierung und HTTP-Freigabe müssen boolesch sein")
    if type(t.get("interval")) is not int or not 30 <= t["interval"] <= 86400:
        raise SafetyError("Zielintervall muss 30–86400 Sekunden betragen")
    address = t.get("address")
    if not isinstance(address, str) or not 1 <= len(address) <= 4096:
        raise SafetyError("Ungültige Zieladresse")
    if t["kind"] == "catalog":
        p = urlsplit(address)
        if (
            p.scheme != "https" and not (p.scheme == "http" and t.get("allow_http"))
        ) or not p.hostname:
            raise SafetyError(
                "HTTPS erforderlich; internes HTTP muss ausdrücklich aktiviert werden"
            )
        if p.username or p.password or p.query or p.fragment or p.path not in ("", "/"):
            raise SafetyError(
                "Basisadresse ohne Zugangsdaten, Pfad oder URL-Parameter erforderlich"
            )
        try:
            p.port
        except ValueError as error:
            raise SafetyError("Ungültiger Zielport") from error
    else:
        folder = Path(address)
        if not folder.is_absolute():
            raise SafetyError("Snapshot-Ziel muss ein absoluter Verzeichnispfad sein")
        validate_directory(config, folder)
        # Registering a destination does not create directories or claim a mount.
    if "key" in data and not isinstance(data["key"], str):
        raise SafetyError("Zielschlüssel muss Text sein")
    if data.get("key") == "":
        t.pop("key", None)
        if old.get("key"):
            t["key"] = old["key"]
    elif data.get("key"):
        t.pop("key_file", None)
    if "key" in t and (not isinstance(t["key"], str) or not t["key"].isascii()):
        raise SafetyError("Zielschlüssel muss ASCII-Text sein")
    key = key_for(config, t) if t.get("key") or t.get("key_file") else b""
    if not 32 <= len(key) <= 1024 or not all(33 <= c <= 126 for c in key):
        raise SafetyError(
            "Ziel benötigt einen Schlüssel mit 32–1024 druckbaren ASCII-Zeichen ohne Leerzeichen"
        )
    with control.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        # Revision prevents concurrent browser updates from silently losing changes.
        import json

        row = db.execute(
            "SELECT value FROM settings WHERE key=?", (REGISTRY,)
        ).fetchone()
        latest = json.loads(row[0]) if row else current
        existing = next((v for v in latest if v["id"] == ident), {})
        if existing.get("revision", 0) != old.get("revision", 0):
            raise SafetyError("Ziel wurde gleichzeitig geändert; Ansicht neu laden")
        latest = [v for v in latest if v["id"] != ident] + [t]
        db.execute(
            "INSERT INTO settings VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (REGISTRY, json.dumps(latest)),
        )
    control.path.chmod(0o600)
    control.sync_event(
        "config", "UPDATED", None, "Veröffentlichungsziel konfiguriert: " + ident
    )


def delete_target(config: WebConfig, control: Control, ident: str) -> None:
    if config.role != "archive":
        raise SafetyError("Nur Archive Nodes verwalten Veröffentlichungsziele")
    import json

    with control.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute(
            "SELECT value FROM settings WHERE key=?", (REGISTRY,)
        ).fetchone()
        current = json.loads(row[0]) if row else targets(config, control)
        if not any(t["id"] == ident for t in current):
            raise SafetyError("Unbekanntes Ziel")
        db.execute(
            "INSERT INTO settings VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (REGISTRY, json.dumps([t for t in current if t["id"] != ident])),
        )
    control.sync_event(
        "config", "REMOVED", None, "Veröffentlichungsziel entfernt: " + ident
    )


def validate_directory(config: WebConfig, folder: Path) -> None:
    protected = [
        config.state,
        config.catalog,
        config.staging,
        config.media_root,
        config.restore_root,
    ] + [s.path for s in config.sources]
    resolved = folder.resolve()
    if any(
        resolved.is_relative_to(p.resolve()) or p.resolve().is_relative_to(resolved)
        for p in protected
    ):
        raise SafetyError(
            "Snapshot-Ziel muss von Quellen und Node-Daten getrennt liegen"
        )


def initialize_directory(
    config: WebConfig, control: Control, ident: str, confirmation: str
) -> None:
    if config.role != "archive" or confirmation != config.node_id:
        raise SafetyError(
            "Zielinitialisierung benötigt die ausdrückliche Bestätigung der Node-ID"
        )
    target = next((t for t in targets(config, control) if t["id"] == ident), None)
    if target is None or target["kind"] != "directory":
        raise SafetyError("Kein Snapshot-Verzeichnisziel")
    folder = Path(target["address"])
    validate_directory(config, folder)
    if not folder.is_dir() or folder.is_symlink():
        raise SafetyError(
            "Vorhandenes, tatsächlich eingehängtes Verzeichnis erforderlich"
        )
    from ..common import sync_dir
    import os

    # Exclusive creation: never replace a marker, claim another node or create a mountpoint.
    with (folder / ".otam-backup-target").open("x") as stream:
        stream.write(config.node_id + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    sync_dir(folder)
    control.sync_event("config", "INITIALIZED", None, "Zielmarker angelegt: " + ident)
