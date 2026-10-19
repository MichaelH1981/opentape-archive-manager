"""Separate durable command executor; no tape job lives inside an HTTP request."""

from __future__ import annotations

import fcntl
import json
import os
import re
import signal
import time
import threading
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from ..catalog import Catalog
from ..common import SafetyError, safe_path
from ..service import ArchiveService
from ..sets import backup_set_step, next_child, plan_set
from ..tape import SimulatedTape
from ..storage import io_lock
from .config import WebConfig
from .control import Control
from .replication import push
from .targets import enabled_targets
from . import resources, maintenance
from . import diagnostics

COMMANDS = {
    "create-medium",
    "plan",
    "stage",
    "backup",
    "backup-set",
    "verify",
    "restore",
    "recover",
    "rebuild",
    "sync",
    "tape-maintenance",
    "hardware-scan",
}


def mounted(config: WebConfig, control: Control, media: str) -> SimulatedTape:
    path = control.resource(media)
    if path.is_symlink() or not path.resolve().is_relative_to(
        config.media_root.resolve()
    ):
        raise SafetyError("Medium liegt außerhalb des konfigurierten Simulatorbereichs")
    return SimulatedTape(path)


def require_uuid(payload: dict[str, Any], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or len(value) > 36:
        raise SafetyError(f"Ungültige Ressourcen-ID: {field}")
    try:
        uuid.UUID(value)
    except ValueError as error:
        raise SafetyError(f"Ungültige Ressourcen-ID: {field}") from error
    return value


def validate_command(
    config: WebConfig, control: Control, kind: str, payload: dict[str, Any]
) -> None:
    if config.role != "archive" or kind not in COMMANDS:
        raise SafetyError("Dieser Node erlaubt keine Archivierungsaufträge")
    config = resources.effective(config, control)
    if kind == "tape-maintenance":
        maintenance.approval(config, control, payload)
        return
    if kind == "hardware-scan":
        if payload:
            raise SafetyError("Laufwerkserkennung benötigt keine Parameter")
        return
    if kind not in ("sync",) and maintenance.mode(config, control) != "simulator":
        raise SafetyError(
            "Im physischen Wartungsbetrieb sind Simulator-Archivierungen gesperrt. Reale Archivierung benötigt die Bandformat-Abnahme."
        )
    if kind == "sync":
        if payload:
            raise SafetyError(
                "Synchronisation akzeptiert keine frei wählbaren Parameter"
            )
        if not enabled_targets(config, control):
            raise SafetyError("Kein Synchronisationsziel konfiguriert")
        return
    if kind == "create-medium":
        if set(payload) - {"label", "capacity", "media_class"}:
            raise SafetyError("Unbekannte Medienparameter")
        if (
            not isinstance(payload.get("label"), str)
            or not 1 <= len(payload["label"].strip()) <= 100
        ):
            raise SafetyError("Medienbezeichnung fehlt oder ist zu lang")
        if (
            type(payload.get("capacity", 800_000_000_000)) is not int
            or not 32768
            <= payload.get("capacity", 800_000_000_000)
            <= 100_000_000_000_000
        ):
            raise SafetyError("Ungültige native Medienkapazität")
        if payload.get("media_class", "permanent") not in ("permanent", "rotation"):
            raise SafetyError("Ungültige Medienklasse")
        return
    allowed = {
        "plan": {"media_id", "media_ids", "source_id", "target", "staging_id", "selected_paths", "verify_mode"},
        "stage": {"job_id", "revalidate_ready", "confirm"},
        "backup": {"job_id", "confirm", "plan_hash", "resume", "prepare_all"},
        "backup-set": {"job_id", "confirm", "plan_hash", "media_id", "resume"},
        "verify": {"media_id"},
        "restore": {"media_id", "paths", "archive_id", "target_name"},
        "recover": {"media_id"},
        "rebuild": {"media_id"},
    }[kind]
    if set(payload) - allowed:
        raise SafetyError("Unbekannte Auftragsparameter")
    if kind == "plan":
        if payload.get("verify_mode", "archive") not in ("archive", "media"):
            raise SafetyError("Ungültiger Verifikationsmodus")
        if "selected_paths" in payload:
            selected = payload["selected_paths"]
            if (not isinstance(selected, list) or not 1 <= len(selected) <= 10000
                    or any(not isinstance(path, str) or len(path) > 4096 for path in selected)):
                raise SafetyError("Ungültige Dateiauswahl")
            for path in selected:
                safe_path(path)
        resources.staging_for(
            config, control, payload.get("staging_id", "default-staging")
        )
        if not isinstance(payload.get("source_id"), str) or payload.get(
            "source_id"
        ) not in {s.id for s in config.sources}:
            raise SafetyError("Quelle ist nicht freigegeben")
        if "media_ids" in payload:
            ids = payload["media_ids"]
            if (not isinstance(ids, list) or not 2 <= len(ids) <= 32
                    or any(not isinstance(ident, str) for ident in ids)
                    or len(set(ids)) != len(ids)):
                raise SafetyError("Zwei bis 32 verschiedene Medien erforderlich")
            for media_id in ids:
                require_uuid({"media_id": media_id}, "media_id")
                mounted(config, control, media_id)
            if "media_id" in payload:
                raise SafetyError("Einzel- und Mehrbandziel nicht mischen")
        else:
            require_uuid(payload, "media_id")
            mounted(config, control, payload["media_id"])
        if (
            type(payload.get("target", 75_000_000_000)) is not int
            or not 10240 <= payload.get("target", 75_000_000_000) <= 10_000_000_000_000
        ):
            raise SafetyError("Ungültige TAR-Zielgröße")
    if kind == "backup-set":
        require_uuid(payload, "job_id")
        require_uuid(payload, "media_id")
        if payload.get("confirm") != payload["job_id"] or not isinstance(payload.get("plan_hash"), str):
            raise SafetyError("Geprüften Mehrbandplan ausdrücklich bestätigen")
        if type(payload.get("resume", False)) is not bool:
            raise SafetyError("Ungültige Wiederaufnahmeoption")
        catalog = Catalog(config.catalog)
        try:
            row, child = next_child(catalog, payload["job_id"])
            plan = json.loads(row["plan_json"])
            if payload["plan_hash"] != plan["sha256"] or child["media_id"] != payload["media_id"]:
                raise SafetyError("Falsches Medium oder geänderter Mehrbandplan")
            if Path(plan["source"]).resolve() not in {s.path.resolve() for s in config.sources}:
                raise SafetyError("Planquelle ist nicht mehr freigegeben")
            mounted(config, control, payload["media_id"])
        finally:
            catalog.close()
    elif kind in ("stage", "backup"):
        require_uuid(payload, "job_id")
        catalog = Catalog(config.catalog)
        try:
            row = catalog.db.execute(
                "SELECT state,plan_json FROM jobs WHERE id=? AND kind='archive'",
                (payload["job_id"],),
            ).fetchone()
            if row is None:
                raise SafetyError("Archivplan fehlt")
            plan = json.loads(row["plan_json"])
            source = Path(plan["source"]).resolve()
            if source not in {s.path.resolve() for s in config.sources}:
                raise SafetyError("Planquelle ist auf diesem Node nicht freigegeben")
            mounted(config, control, plan["media_id"])
            if (
                kind == "stage"
                and "revalidate_ready" in payload
                and type(payload["revalidate_ready"]) is not bool
            ):
                raise SafetyError("Ungültige Option für erneute Staging-Prüfung")
            if kind == "stage" and payload.get("revalidate_ready"):
                if (
                    payload.get("revalidate_ready") is not True
                    or payload.get("confirm") != payload["job_id"]
                ):
                    raise SafetyError(
                        "Erneute Staging-Prüfung benötigt die ausdrückliche Job-ID-Bestätigung"
                    )
            if kind == "backup":
                if (
                    payload.get("confirm") != payload["job_id"]
                    or payload.get("plan_hash") != plan["sha256"]
                ):
                    raise SafetyError(
                        "Geprüften Plan mit Job-ID und Plan-Hash ausdrücklich bestätigen"
                    )
                for key in ("resume", "prepare_all"):
                    if key in payload and type(payload[key]) is not bool:
                        raise SafetyError("Ungültige Archivierungsoption")
        finally:
            catalog.close()
    elif kind != "plan":
        require_uuid(payload, "media_id")
        mounted(config, control, payload["media_id"])
    if kind == "restore":
        if (
            not isinstance(payload.get("paths", []), list)
            or len(payload.get("paths", [])) > 1000
            or any(
                not isinstance(p, str) or len(p) > 4096
                for p in payload.get("paths", [])
            )
        ):
            raise SafetyError("Ungültige Dateiauswahl")
        if not isinstance(payload.get("target_name"), str) or not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", payload.get("target_name", "")
        ):
            raise SafetyError(
                "Zielname darf nur Buchstaben, Zahlen, Punkt, Bindestrich und Unterstrich enthalten"
            )
        if payload.get("archive_id"):
            require_uuid(payload, "archive_id")


def execute(
    config: WebConfig,
    control: Control,
    kind: str,
    payload: dict[str, Any],
    *,
    scheduled: bool = False,
) -> Any:
    validate_command(config, control, kind, payload)
    config = resources.effective(config, control)
    if kind == "tape-maintenance":
        return maintenance.execute(config, control, payload)
    if kind == "hardware-scan":
        return diagnostics.scan(control, force=True)
    if kind == "sync":
        with io_lock():
            return push(config, control, due_only=scheduled)
    catalog = Catalog(config.catalog)
    try:
        if kind == "create-medium":
            config.media_root.mkdir(parents=True, exist_ok=True, mode=0o700)
            tape = SimulatedTape.create(
                config.media_root / str(uuid.uuid4()),
                payload["label"].strip(),
                payload.get("capacity", 800_000_000_000),
                payload.get("media_class", "permanent"),
            )
            header = ArchiveService(catalog, tape).register()
            control.register(header["media_id"], tape.path)
            return header
        if kind in ("stage", "backup", "backup-set"):
            row = catalog.db.execute(
                "SELECT plan_json FROM jobs WHERE id=?", (payload["job_id"],)
            ).fetchone()
            media = payload["media_id"] if kind == "backup-set" else json.loads(row[0])["media_id"]
        else:
            media = payload.get("media_id") or payload.get("media_ids", [None])[0]
        service = ArchiveService(catalog, mounted(config, control, media))
        if kind == "plan":
            source = next(
                s.path for s in config.sources if s.id == payload["source_id"]
            )
            if "media_ids" in payload:
                plan = plan_set(catalog, source,
                    [(ident, mounted(config, control, ident)) for ident in payload["media_ids"]],
                    payload.get("target", 75_000_000_000), payload.get("selected_paths"),
                    payload.get("verify_mode", "archive"))
            else:
                plan = service.plan(source, media, payload.get("target", 75_000_000_000),
                                    payload.get("selected_paths"), payload.get("verify_mode", "archive"))
            control.set(
                "job_storage:" + plan["job_id"],
                {
                    "staging_id": payload.get("staging_id", "default-staging"),
                    "source_id": payload["source_id"],
                    "staging_path": str(
                        resources.staging_for(
                            config,
                            control,
                            payload.get("staging_id", "default-staging"),
                        )
                    ),
                },
            )
            for child in plan.get("children", []):
                control.set("job_storage:" + child["job_id"], control.get("job_storage:" + plan["job_id"]))
            return {k: plan[k] for k in (
                "job_id", "sha256", "file_count", "payload_bytes"
            )} | {k: plan[k] for k in ("required_estimate", "available", "media_ids") if k in plan}
        if kind in ("stage", "backup", "backup-set"):
            binding = control.get(
                "job_storage:" + payload["job_id"], {"staging_id": "default-staging"}
            )
            spool = resources.staging_for(config, control, binding["staging_id"])
        if kind == "stage":
            return service.stage(
                payload["job_id"],
                spool,
                revalidate_ready=payload.get("revalidate_ready", False),
            )
        if kind == "backup":
            return service.backup(
                payload["job_id"],
                payload["confirm"],
                spool,
                resume=payload.get("resume", False),
                prepare_all=payload.get("prepare_all", False),
            )
        if kind == "backup-set":
            return backup_set_step(catalog, payload["job_id"], payload["confirm"],
                                   payload["plan_hash"], payload["media_id"], service.tape,
                                   spool, resume=payload.get("resume", False))
        if kind == "verify":
            return service.verify(media)
        if kind == "restore":
            target = config.restore_root / payload["target_name"]
            config.restore_root.mkdir(parents=True, exist_ok=True, mode=0o700)
            if (
                not target.resolve().is_relative_to(config.restore_root.resolve())
                or target.is_symlink()
            ):
                raise SafetyError("Ungültiges Wiederherstellungsziel")
            if target.exists():
                raise SafetyError(
                    "Wiederherstellungsziel existiert bereits; einen neuen Zielnamen verwenden"
                )
            return service.restore(
                media, target, payload.get("paths") or None, payload.get("archive_id")
            )
        if kind == "recover":
            return {"interrupted_jobs": service.recover_jobs(media)}
        if kind == "rebuild":
            return service.rebuild(media)
        raise SafetyError("Unbekannter Auftrag")
    finally:
        catalog.close()


@contextmanager
def worker_lock(config: WebConfig) -> Iterator[None]:
    config.state.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(
        config.state / "worker.lock", os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600
    )
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise SafetyError("Für diesen Node läuft bereits ein Worker") from error
        yield
    finally:
        os.close(fd)


def run_once(config: WebConfig, control: Control) -> bool:
    control.set("worker_heartbeat", time.time())
    command = control.claim()
    if command is None:
        return False
    try:
        result = execute(
            config,
            control,
            command["kind"],
            command["payload"],
            scheduled=command["idempotency"].startswith("scheduled-"),
        )
        control.complete(
            command["id"],
            result,
            error=(
                "Mindestens ein optionales Ziel ist fehlgeschlagen; Einzelstatus prüfen"
                if command["kind"] == "sync" and result.get("state") == "PARTIAL"
                else None
            ),
        )
    except Exception as error:
        if command["kind"] == "tape-maintenance":
            key = "maintenance_progress:" + command["payload"].get(
                "approval_id", "invalid"
            )
            if control.get(key) is None:
                grant = control.get(
                    "maintenance_approval:" + command["payload"].get("approval_id", ""),
                    {},
                )
                control.set(
                    key,
                    {
                        "state": "FAILED",
                        "phase": "NOT_STARTED",
                        "error": str(error),
                        "time": time.time(),
                        "bytes": 0,
                        "approval_id": grant.get("id"),
                        "drive": grant.get("drive", {}),
                        "operation": grant.get("operation"),
                    },
                )
        control.complete(command["id"], error=str(error))
    return True


def run_worker(config: WebConfig, *, once: bool = False) -> None:
    if config.role != "archive":
        raise SafetyError("Ein Catalog Node benötigt keinen Archivierungsworker")
    control = Control(config.state)
    stopping = False

    def stop(signum: int, frame: Any) -> None:
        nonlocal stopping
        stopping = (
            True  # Finish the active operation; never kill a tape write from HTTP.
        )

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    with worker_lock(config):
        control.interrupt_running()
        with control.connect() as db:
            for row in db.execute(
                "SELECT key,value FROM settings WHERE key LIKE 'maintenance_progress:%'"
            ).fetchall():
                value = json.loads(row["value"])
                if value.get("state") == "RUNNING":
                    value.update(
                        state="INTERRUPTED",
                        phase="INCOMPLETE",
                        error="Worker-Neustart: Medium und Position erneut prüfen; neue Freigabe erforderlich",
                    )
                    db.execute(
                        "UPDATE settings SET value=? WHERE key=?",
                        (json.dumps(value), row["key"]),
                    )
        heartbeat_stop = threading.Event()

        def heartbeat() -> None:
            while not heartbeat_stop.wait(5):
                control.set("worker_heartbeat", time.time())

        heartbeat_thread = threading.Thread(
            target=heartbeat, name="otam-heartbeat", daemon=True
        )
        heartbeat_thread.start()
        next_scan = 0.0
        next_sync = time.monotonic() + 5
        try:
            while not stopping:
                worked = run_once(config, control)
                if once:
                    break
                if time.monotonic() >= next_scan:
                    diagnostics.scan(control)
                    next_scan = time.monotonic() + 10
                if time.monotonic() >= next_sync:
                    with control.connect() as db:
                        queued = db.execute(
                            "SELECT 1 FROM commands WHERE kind='sync' AND state IN ('QUEUED','RUNNING')"
                        ).fetchone()
                    due = False
                    for target in enabled_targets(config, control):
                        last = control.get("target_status:" + target["id"], {})
                        if (
                            last.get("revision") != target["revision"]
                            or time.time() - last.get("time", 0) >= target["interval"]
                        ):
                            due = True
                            break
                    if due and not queued:
                        control.enqueue("sync", {}, "scheduled-" + str(uuid.uuid4()))
                    next_sync = time.monotonic() + 5
                if not worked:
                    time.sleep(1)
        finally:
            heartbeat_stop.set()
            heartbeat_thread.join(timeout=6)
            control.set("worker_heartbeat", 0)
