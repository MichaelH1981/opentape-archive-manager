"""Persistent source/staging resources, bounded directory picker and job bindings."""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import replace
from contextlib import closing
import sqlite3
from pathlib import Path
from typing import Any

from ..common import SafetyError, safe_path
from ..storage import require_local, filesystem
from .config import Resource, WebConfig
from .control import Control


def entries(config: WebConfig, control: Control) -> list[dict[str, Any]]:
    saved = control.get("storage_resources")
    if saved is not None:
        return saved
    return [
        dict(id=s.id, label=s.label, path=str(s.path), kind="source")
        for s in config.sources
    ] + [
        dict(
            id="default-staging",
            label="Lokales Standard-Staging",
            path=str(config.staging),
            kind="staging",
        )
    ]


def effective(config: WebConfig, control: Control) -> WebConfig:
    return replace(
        config,
        sources=tuple(
            Resource(r["id"], r["label"], Path(r["path"]))
            for r in entries(config, control)
            if r["kind"] == "source"
        ),
    )


def roots(config: WebConfig, control: Control) -> list[Path]:
    candidates = [
        *config.directory_roots,
        *(s.path for s in config.sources),
        config.staging,
    ]
    return sorted({p.resolve() for p in candidates if p.is_dir()}, key=str)


def directory(config: WebConfig, control: Control, value: str) -> Path:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 4096
        or not Path(value).is_absolute()
    ):
        raise SafetyError("Absoluter Verzeichnispfad erforderlich")
    path = Path(value)
    if ".." in path.parts or path.is_symlink():
        raise SafetyError("Symlinks und Pfad-Traversal sind hier nicht erlaubt")
    resolved = path.resolve(strict=True)
    for private in (
        config.state,
        config.catalog,
        config.media_root,
        config.restore_root,
    ):
        if resolved.is_relative_to(private.resolve()):
            raise SafetyError(
                "Interne Node-Daten sind im Verzeichnisdialog nicht zugänglich"
            )
    if (
        not any(resolved.is_relative_to(root) for root in roots(config, control))
        or not resolved.is_dir()
    ):
        raise SafetyError(
            "Verzeichnis liegt außerhalb der administrativ freigegebenen Bereiche"
        )
    if not os.access(resolved, os.R_OK | os.X_OK):
        raise SafetyError("Dienstkonto benötigt Lese- und Verzeichnisrechte")
    return resolved


def browse(config: WebConfig, control: Control, value: str = "") -> dict[str, Any]:
    if not value:
        return {
            "path": "",
            "parent": "",
            "items": [{"name": str(p), "path": str(p)} for p in roots(config, control)],
            "truncated": False,
        }
    path = directory(config, control, value)
    items = []
    truncated = False
    with os.scandir(path) as children:
        for child in children:
            if child.is_dir(follow_symlinks=False) and not child.name.startswith("."):
                try:
                    accepted = directory(config, control, str(Path(child.path)))
                except (OSError, SafetyError):
                    continue
                items.append({"name": child.name, "path": str(accepted)})
                if len(items) >= 500:
                    truncated = True
                    break
    parent = (
        str(path.parent)
        if any(path.parent.is_relative_to(r) for r in roots(config, control))
        else ""
    )
    return {
        "path": str(path),
        "parent": parent,
        "items": sorted(items, key=lambda r: r["name"].casefold()),
        "truncated": truncated,
    }


def source_tree(config: WebConfig, control: Control, source_id: str,
                relative: str = "", offset: int = 0) -> dict[str, Any]:
    """List selectable source entries without following links or leaving the source."""
    source = next((s.path for s in effective(config, control).sources if s.id == source_id), None)
    if source is None or not source.is_dir() or offset < 0 or offset > 1_000_000:
        raise SafetyError("Ungültige Quellenauswahl")
    path = source
    if relative:
        for part in safe_path(relative).split("/"):
            path = path / part
            if path.is_symlink() or not path.is_dir():
                raise SafetyError("Quellpfad ist kein echtes Verzeichnis")
    items: list[dict[str, Any]] = []
    with os.scandir(path) as children:
        for child in children:
            if child.is_symlink():
                continue
            if child.is_dir(follow_symlinks=False):
                kind = "directory"
            elif child.is_file(follow_symlinks=False):
                kind = "file"
            else:
                continue
            name = (path / child.name).relative_to(source).as_posix()
            items.append({"name": child.name, "path": name, "kind": kind})
    items.sort(key=lambda item: (item["kind"] != "directory", item["name"].casefold()))
    return {"source_id": source_id, "path": relative, "parent": relative.rpartition("/")[0],
            "items": items[offset:offset + 200], "next_offset": offset + 200 if len(items) > offset + 200 else None}


def save(config: WebConfig, control: Control, ident: str, data: dict[str, Any]) -> None:
    if config.role != "archive":
        raise SafetyError("Nur Archive Nodes verwalten Quellen und Staging")
    uuid.UUID(ident)
    if set(data) != {"kind", "label", "path"} or data["kind"] not in (
        "source",
        "staging",
    ):
        raise SafetyError("Ungültige Verzeichnisressource")
    if not isinstance(data["label"], str) or not 1 <= len(data["label"].strip()) <= 100:
        raise SafetyError("Bezeichnung mit 1–100 Zeichen erforderlich")
    path = directory(config, control, data["path"])
    private = [config.state, config.catalog, config.media_root, config.restore_root]
    if any(
        path.is_relative_to(p.resolve()) or p.resolve().is_relative_to(path)
        for p in private
    ):
        raise SafetyError(
            "Quellen und Staging müssen von internen Node-Daten getrennt sein"
        )
    if data["kind"] == "staging":
        require_local(path)
        if not os.access(path, os.W_OK):
            raise SafetyError("Staging-Verzeichnis ist für den Dienst nicht schreibbar")
    from .targets import targets

    for target in targets(config, control):
        if target["kind"] == "directory":
            dest = Path(target["address"]).resolve()
            if path.is_relative_to(dest) or dest.is_relative_to(path):
                raise SafetyError(
                    "Verzeichnis überschneidet sich mit einem Snapshot-Ziel"
                )
    with control.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute(
            "SELECT value FROM settings WHERE key='storage_resources'"
        ).fetchone()
        current = json.loads(row[0]) if row else entries(config, control)
        old = next((r for r in current if r["id"] == ident), None)
        if old:
            raise SafetyError(
                "Ressourcen sind unveränderlich; neue Ressource anlegen und alte entfernen"
            )
        for other in current:
            other_path = Path(other["path"]).resolve()
            if path == other_path or (
                other["kind"] != data["kind"]
                and (path.is_relative_to(other_path) or other_path.is_relative_to(path))
            ):
                raise SafetyError(
                    "Quelle und Staging überschneiden sich oder der Pfad ist bereits registriert"
                )
        current.append(
            {"id": ident, **data, "path": str(path), "device": path.stat().st_dev}
        )
        db.execute(
            "INSERT INTO settings VALUES('storage_resources',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (json.dumps(current),),
        )
    control.sync_event("config", "UPDATED", None, "Verzeichnis registriert: " + ident)


def remove(config: WebConfig, control: Control, ident: str) -> None:
    if config.role != "archive":
        raise SafetyError("Nur Archive Nodes verwalten Verzeichnisse")
    with control.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute(
            "SELECT value FROM settings WHERE key='storage_resources'"
        ).fetchone()
        current = json.loads(row[0]) if row else entries(config, control)
        resource = next((r for r in current if r["id"] == ident), None)
        if resource is None:
            raise SafetyError("Unbekannte Verzeichnisressource")
        if (
            resource["kind"] == "staging"
            and sum(r["kind"] == "staging" for r in current) == 1
        ):
            raise SafetyError(
                "Mindestens ein Staging-Verzeichnis muss erhalten bleiben"
            )
        if db.execute(
            "SELECT 1 FROM commands WHERE state IN ('QUEUED','RUNNING')"
        ).fetchone():
            raise SafetyError(
                "Vor Entfernen alle wartenden und laufenden Aufträge abschließen"
            )
        with closing(sqlite3.connect(config.catalog)) as catalog:
            for plan, state in catalog.execute(
                "SELECT plan_json,state FROM jobs WHERE kind IN ('archive','source-plan')"
            ):
                if state not in ("VERIFIED", "CANCELLED", "BOUND") and plan:
                    parsed = json.loads(plan)
                    if (
                        resource["kind"] == "source"
                        and parsed["source"] == resource["path"]
                    ):
                        raise SafetyError(
                            "Quelle wird noch von einem Archivplan benötigt"
                        )
            if (
                resource["kind"] == "staging"
                and catalog.execute(
                    "SELECT 1 FROM staged_archives WHERE root=? AND phase!='STAGING_CLEANUP'",
                    (resource["path"],),
                ).fetchone()
            ):
                raise SafetyError(
                    "Nicht verifizierte Staging-Dateien benötigen dieses Verzeichnis"
                )
        # Bindings also protect plans that have not staged any bytes yet.
        with closing(sqlite3.connect(config.catalog)) as catalog:
            for binding in db.execute(
                "SELECT key,value FROM settings WHERE key LIKE 'job_storage:%'"
            ):
                if json.loads(binding["value"])["staging_id"] == ident:
                    job_id = binding["key"].split(":", 1)[1]
                    job = catalog.execute(
                        "SELECT state FROM jobs WHERE id=?", (job_id,)
                    ).fetchone()
                    if job is None or job[0] not in ("VERIFIED", "CANCELLED", "BOUND"):
                        raise SafetyError(
                            "Verzeichnis ist an einen noch nicht abgeschlossenen Job gebunden"
                        )
        db.execute(
            "INSERT INTO settings VALUES('storage_resources',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (json.dumps([r for r in current if r["id"] != ident]),),
        )
    control.sync_event(
        "config",
        "REMOVED",
        None,
        "Verzeichnis abgemeldet, Dateien bleiben erhalten: " + ident,
    )


def staging_for(
    config: WebConfig, control: Control, ident: str = "default-staging"
) -> Path:
    resource = next(
        (
            r
            for r in entries(config, control)
            if r["id"] == ident and r["kind"] == "staging"
        ),
        None,
    )
    if not resource:
        raise SafetyError("Staging-Verzeichnis ist nicht registriert")
    path = Path(resource["path"])
    if path.is_symlink() or (
        "device" in resource and path.stat().st_dev != resource["device"]
    ):
        raise SafetyError("Staging-Mount oder Verzeichnis wurde ausgetauscht")
    ancestor = path
    while not ancestor.exists():
        ancestor = ancestor.parent
    require_local(ancestor)
    return path


def overview(config: WebConfig, control: Control) -> list[dict[str, Any]]:
    result = []
    for r in entries(config, control):
        entry = dict(r)
        if r["kind"] == "source":
            # Never poll statvfs/stat on hard-mounted network sources from dashboard refreshes.
            # Actual accessibility is checked only on explicit browsing/inventory.
            entry.update(available=None, storage=None, writable=False)
            result.append(entry)
            continue
        try:
            path = Path(r["path"])
            if "device" in r and path.stat().st_dev != r["device"]:
                raise SafetyError("Staging-Mount oder Verzeichnis wurde ausgetauscht")
            entry["storage"] = filesystem(path)
            entry["available"] = path.is_dir() and os.access(path, os.R_OK | os.X_OK)
            entry["writable"] = os.access(path, os.W_OK)
        except (OSError, SafetyError):
            entry.update(available=False, storage=None, writable=False)
        result.append(entry)
    return result


def default_staging_id(config: WebConfig, control: Control) -> str:
    """Resolve the configured primary path without assuming a legacy resource ID."""
    staging = [r for r in entries(config, control) if r["kind"] == "staging"]
    primary = [r for r in staging if Path(r["path"]) == config.staging]
    if len(primary) == 1:
        return primary[0]["id"]
    if len(staging) == 1:
        return staging[0]["id"]
    raise SafetyError("Primäres Staging-Verzeichnis ist nicht eindeutig konfiguriert")


def staging_capacity(locations: list[dict[str, Any]]) -> dict[str, int]:
    """Sum each available filesystem once even when several paths refer to it."""
    summary = {"total": 0, "used": 0, "free": 0, "volumes": 0}
    seen: set[str] = set()
    for item in locations:
        storage = item.get("storage")
        if item.get("kind") != "staging" or not item.get("available") or not storage:
            continue
        key = str(storage.get("device") or
                  (storage.get("block_device"), storage.get("mount")))
        if key in seen:
            continue
        seen.add(key)
        for field in ("total", "used", "free"):
            summary[field] += int(storage[field])
        summary["volumes"] += 1
    return summary
