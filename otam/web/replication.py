"""Authenticated, versioned publication of consistent read-only catalog snapshots."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import shutil
import sqlite3
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

from ..common import SafetyError, sync_dir
from .config import WebConfig
from .control import Control

REQUIRED = {
    "media": {"id", "label", "state", "capacity"},
    "archives": {"id", "media_id", "state", "sha256"},
    "files": {"archive_id", "path", "size", "sha256"},
    "jobs": {"id", "kind", "state", "phase"},
    "events": {"seq", "job_id", "details_json"},
    "staged_archives": {"job_id", "archive_id", "phase"},
    "verifications": {"id", "state"},
    "restores": {"id", "state"},
    "staging_artifacts": {"job_id", "archive_id"},
    "storage_benchmarks": {"id", "report_json"},
}


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as source:
        while block := source.read(1024 * 1024):
            value.update(block)
    return value.hexdigest()


def canonical(meta: dict[str, Any]) -> bytes:
    return json.dumps(
        {k: v for k, v in meta.items() if k != "signature"},
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


def sign(meta: dict[str, Any], key: bytes) -> dict[str, Any]:
    return {
        **meta,
        "signature": hmac.new(
            key, b"otam-snapshot-v1\n" + canonical(meta), hashlib.sha256
        ).hexdigest(),
    }


def metadata_header(meta: dict[str, Any]) -> str:
    return base64.urlsafe_b64encode(
        json.dumps(meta, separators=(",", ":")).encode()
    ).decode()


def decode_header(value: str, config: WebConfig) -> dict[str, Any]:
    try:
        if len(value) > 4096:
            raise ValueError()
        meta = json.loads(base64.b64decode(value, altchars=b"-_", validate=True))
        if set(meta) != {
            "format",
            "publisher",
            "sequence",
            "created",
            "bytes",
            "sha256",
            "signature",
        }:
            raise ValueError()
        expected = sign(meta, config.peer_key())["signature"]
        if not hmac.compare_digest(meta["signature"], expected):
            raise ValueError()
        if (
            meta["format"] != "otam-catalog-snapshot-v1"
            or meta["publisher"] != config.publisher_id
        ):
            raise ValueError()
        if type(meta["sequence"]) is not int or meta["sequence"] < 1:
            raise ValueError()
        if (
            type(meta["bytes"]) is not int
            or not 1024 <= meta["bytes"] <= config.max_snapshot_bytes
        ):
            raise ValueError()
        if (
            type(meta["created"]) not in (int, float)
            or not 0 < meta["created"] <= time.time() + 300
        ):
            raise ValueError()
        if (
            not isinstance(meta["sha256"], str)
            or len(meta["sha256"]) != 64
            or any(c not in "0123456789abcdef" for c in meta["sha256"])
        ):
            raise ValueError()
        return meta
    except (ValueError, TypeError, KeyError, UnicodeError) as error:
        raise SafetyError(
            "Snapshot-Metadaten, Signatur oder Herausgeber ungültig"
        ) from error


def validate_snapshot(path: Path) -> None:
    with path.open("rb") as source:
        if source.read(16) != b"SQLite format 3\x00":
            raise SafetyError("Snapshot ist keine SQLite-Datenbank")
    db = sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True)
    try:
        db.execute("PRAGMA query_only=ON")
        db.execute("PRAGMA trusted_schema=OFF")
        if db.execute("PRAGMA user_version").fetchone()[0] != 2:
            raise SafetyError("Nicht unterstützte Katalogversion")
        if db.execute(
            "SELECT count(*) FROM sqlite_master WHERE type IN ('trigger','view')"
        ).fetchone()[0]:
            raise SafetyError("Snapshot enthält unerwartete Views/Trigger")
        tables = {
            r[0]
            for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        if tables != set(REQUIRED):
            raise SafetyError("Snapshot besitzt unerwartete oder fehlende Tabellen")
        for table, columns in REQUIRED.items():
            if not columns <= {
                r[1] for r in db.execute(f'PRAGMA table_info("{table}")')
            }:
                raise SafetyError("Unvollständiges Katalogschema")
        if db.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise SafetyError("Katalog-Integritätsprüfung fehlgeschlagen")
        if db.execute("PRAGMA foreign_key_check").fetchone():
            raise SafetyError("Katalog besitzt ungültige Verweise")
    except sqlite3.Error as error:
        raise SafetyError("Katalog-Snapshot ist nicht lesbar") from error
    finally:
        db.close()


def make_snapshot(
    config: WebConfig, control: Control, key: bytes | None = None
) -> tuple[Path, dict[str, Any]]:
    if config.role != "archive" or not config.catalog.is_file():
        raise SafetyError("Nur der Archive Node veröffentlicht seinen Primärkatalog")
    folder = config.state / "outgoing"
    folder.mkdir(exist_ok=True, mode=0o700)
    sequence = control.next_sequence()
    fd, filename = tempfile.mkstemp(
        prefix=f"snapshot-{sequence}-", suffix=".sqlite", dir=folder
    )
    os.close(fd)
    path = Path(filename)
    try:
        source = sqlite3.connect(config.catalog.as_uri() + "?mode=ro", uri=True)
        target = sqlite3.connect(path)
        try:
            source.backup(target, pages=256, sleep=0.02)
            target.execute("PRAGMA journal_mode=DELETE")
        finally:
            target.close()
            source.close()
        if path.stat().st_size > config.max_snapshot_bytes:
            raise SafetyError("Katalog überschreitet das konfigurierte Snapshot-Limit")
        validate_snapshot(path)
        with path.open("rb") as stream:
            os.fsync(stream.fileno())
        meta = {
            "format": "otam-catalog-snapshot-v1",
            "publisher": config.node_id,
            "sequence": sequence,
            "created": time.time(),
            "bytes": path.stat().st_size,
            "sha256": digest(path),
        }
        meta = sign(meta, key if key is not None else config.peer_key())
        path.chmod(0o400)
        return path, meta
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def export_nas(config: WebConfig, path: Path, meta: dict[str, Any]) -> None:
    if config.nas_backup is None:
        return
    folder = config.nas_backup
    from .targets import validate_directory

    validate_directory(config, folder)
    if not folder.is_dir():
        raise SafetyError(
            "Snapshot-Verzeichnisziel ist nicht erreichbar; kein Verzeichnis automatisch angelegt"
        )
    marker = folder / ".otam-backup-target"
    if (
        not marker.is_file()
        or marker.is_symlink()
        or marker.read_text().strip() != config.node_id
    ):
        raise SafetyError(
            "Snapshot-Zielmarker fehlt oder gehört zu einem anderen Node; Mount prüfen"
        )
    name = f"otam-catalog-{meta['publisher']}-{meta['sequence']:012d}"
    # Never replace existing NAS data. Partial files are not advertised as valid snapshots.
    temporary = folder / (name + "." + uuid.uuid4().hex + ".partial")
    try:
        with temporary.open("xb") as target, path.open("rb") as source:
            shutil.copyfileobj(source, target, 1024 * 1024)
            target.flush()
            os.fsync(target.fileno())
        if digest(temporary) != meta["sha256"]:
            raise SafetyError("Snapshot-Prüfsumme stimmt nicht überein")
        os.link(temporary, folder / (name + ".sqlite"))
        with (folder / (name + ".json")).open("x") as stream:
            json.dump(meta, stream, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        sync_dir(folder)
    finally:
        temporary.unlink(missing_ok=True)


def publish(
    config: WebConfig, control: Control, temporary: Path, meta: dict[str, Any]
) -> dict[str, Any]:
    if temporary.stat().st_size != meta["bytes"] or digest(temporary) != meta["sha256"]:
        raise SafetyError("Snapshot ist unvollständig oder verändert")
    validate_snapshot(temporary)
    folder = config.state / "snapshots"
    name = f"{meta['sequence']:012d}-{meta['sha256']}.sqlite"
    published = {**meta, "file": name, "received": time.time()}
    with control.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute(
            "SELECT value FROM settings WHERE key='active_snapshot'"
        ).fetchone()
        active = json.loads(row[0]) if row else None
        if active:
            if meta["publisher"] != active["publisher"]:
                raise SafetyError("Herausgeberwechsel benötigt manuelle Freigabe")
            if meta["sequence"] < active["sequence"]:
                raise SafetyError("Veralteter Snapshot: Zurückrollen verweigert")
            if meta["sequence"] == active["sequence"]:
                if meta["sha256"] != active["sha256"]:
                    raise SafetyError("Snapshot-Sequenz mit abweichendem Inhalt")
                return {"state": "UNCHANGED", "sequence": active["sequence"]}
        with temporary.open("rb") as stream:
            os.fsync(stream.fileno())
        temporary.chmod(0o400)
        try:
            os.link(temporary, folder / name)
        except FileExistsError:
            # A crash after durable file publication but before pointer commit can leave an orphan.
            existing = folder / name
            if (
                existing.is_symlink()
                or existing.stat().st_size != meta["bytes"]
                or digest(existing) != meta["sha256"]
            ):
                raise SafetyError("Vorhandenes Snapshot-Artefakt stimmt nicht überein")
        sync_dir(folder)
        db.execute(
            "INSERT INTO settings VALUES('active_snapshot',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (json.dumps(published),),
        )
        db.execute(
            "INSERT INTO sync_log(time,direction,state,sequence,details) VALUES(?, 'receive','SUCCEEDED',?,?)",
            (time.time(), meta["sequence"], "Katalog atomar veröffentlicht"),
        )
    return {
        "state": "PUBLISHED",
        "sequence": meta["sequence"],
        "sha256": meta["sha256"],
    }


def _push_one(
    config: WebConfig,
    control: Control,
    status_key: str = "last_push",
    key: bytes | None = None,
) -> dict[str, Any]:
    import httpx

    if not config.peer_url and config.nas_backup is None:
        raise SafetyError(
            "Kein Katalog-Peer oder Snapshot-Verzeichnisziel konfiguriert"
        )
    key = key if key is not None else config.peer_key()
    path, meta = make_snapshot(config, control, key)
    try:
        targets = hashlib.sha256(
            (config.peer_url + "|" + str(config.nas_backup)).encode() + key
        ).hexdigest()
        previous = control.get(status_key)
        if (
            previous
            and previous.get("sha256") == meta["sha256"]
            and previous.get("targets") == targets
        ):
            control.set(
                "last_sync_check",
                {
                    "time": time.time(),
                    "state": "UNCHANGED",
                    "sequence": previous["sequence"],
                },
            )
            return {"state": "UNCHANGED", "sequence": previous["sequence"], "bytes": 0}
        export_nas(config, path, meta)
        if config.peer_url:
            with (
                path.open("rb") as stream,
                httpx.Client(
                    timeout=httpx.Timeout(120, connect=10),
                    follow_redirects=False,
                    trust_env=False,
                ) as client,
            ):
                response = client.put(
                    config.peer_url.rstrip("/") + "/api/v1/replication/snapshot",
                    headers={
                        "Authorization": "Bearer " + key.decode("ascii"),
                        "Content-Type": "application/octet-stream",
                        "Content-Length": str(meta["bytes"]),
                        "X-OTAM-Manifest": metadata_header(meta),
                    },
                    content=stream,
                )
            if response.status_code != 200:
                raise SafetyError(
                    f"Katalog-Peer verweigert Veröffentlichung (HTTP {response.status_code})"
                )
            receipt = response.json()
            if receipt.get("sequence") != meta["sequence"] or receipt.get(
                "state"
            ) not in ("PUBLISHED", "UNCHANGED"):
                raise SafetyError("Ungültige Bestätigung des Katalog-Peers")
        result = {
            "state": "SUCCEEDED",
            "sequence": meta["sequence"],
            "created": meta["created"],
            "bytes": meta["bytes"],
            "sha256": meta["sha256"],
            "nas_exported": config.nas_backup is not None,
            "peer_updated": bool(config.peer_url),
        }
        control.set(status_key, result | {"time": time.time(), "targets": targets})
        control.sync_event(
            "send", "SUCCEEDED", meta["sequence"], "Snapshot übertragen und bestätigt"
        )
        return result
    except Exception:
        control.sync_event(
            "send",
            "FAILED",
            meta["sequence"],
            "Synchronisation fehlgeschlagen; letzten gültigen Peer-Stand erhalten",
        )
        raise
    finally:
        # Only this invocation's own managed, fully exported source snapshot.
        path.unlink(missing_ok=True)


def push(
    config: WebConfig, control: Control, *, due_only: bool = False
) -> dict[str, Any]:
    """Fan out independently; a failed optional destination cannot stop another."""
    from dataclasses import replace
    from .targets import enabled_targets, key_for

    destinations = enabled_targets(config, control)
    if not destinations:
        return {"state": "DISABLED", "targets": []}
    results = []
    for target in destinations:
        ident = target["id"]
        previous = control.get("target_status:" + ident, {})
        if (
            due_only
            and previous.get("revision") == target["revision"]
            and time.time() - previous.get("time", 0) < target["interval"]
        ):
            continue
        status_key = "target_receipt:" + ident + ":" + str(target["revision"])
        try:
            outgoing = replace(
                config,
                peer_url=target["address"] if target["kind"] == "catalog" else "",
                nas_backup=(
                    Path(target["address"]) if target["kind"] == "directory" else None
                ),
            )
            result = _push_one(outgoing, control, status_key, key_for(config, target))
            status = {**result, "time": time.time(), "revision": target["revision"]}
        except Exception:
            status = {
                "state": "FAILED",
                "time": time.time(),
                "revision": target["revision"],
                "error": "Übertragung fehlgeschlagen; Erreichbarkeit, Zielmarker und Schlüssel prüfen",
            }
            control.sync_event("send", "FAILED", None, "Ziel fehlgeschlagen: " + ident)
        control.sync_event(
            "send", status["state"], status.get("sequence"), "Ziel: " + ident
        )
        control.set("target_status:" + ident, status)
        results.append({"id": ident, **status})
    result = {
        "state": (
            "PARTIAL" if any(r["state"] == "FAILED" for r in results) else "SUCCEEDED"
        ),
        "targets": results,
    }
    control.set("last_fanout", {**result, "time": time.time()})
    return result
