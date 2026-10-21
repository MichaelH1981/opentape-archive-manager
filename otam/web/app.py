"""FastAPI composition root: shared catalog UI and separately gated archive module."""

from __future__ import annotations

import csv
import hashlib
import hmac
import io
import json
import logging
import os
import shutil
import sqlite3
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any

from fastapi import (
    APIRouter,
    Body,
    Depends,
    FastAPI,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
)
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.concurrency import run_in_threadpool

from ..catalog import Catalog
from .. import __version__
from ..common import SafetyError
from ..hardware import discover
from ..transfer import drive_speed_profiles, selected_speed_profile
from .config import WebConfig
from .control import Control
from .query import CatalogView
from .replication import decode_header, publish
from .targets import (
    enabled_targets,
    public_targets,
    save_target,
    delete_target,
    initialize_directory,
)
from .security import cookie_name, SecurityMiddleware, login, session, require_admin
from .worker import mounted, validate_command
from . import initialization, reset, reinitialization
from . import resources, maintenance, physical_archive
from . import diagnostics
from . import accounts, power

STATIC = Path(__file__).parent / "static"


@dataclass(frozen=True)
class Module:
    id: str
    label: str
    writable: bool


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=1024)


class NewUserRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=12, max_length=1024)
    role: str


class EditUserRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: str | None = None
    enabled: bool | None = None
    password: str | None = Field(default=None, min_length=12, max_length=1024)


class LocaleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    locale: str


class PasswordRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    current_password: str = Field(min_length=1, max_length=1024)
    new_password: str = Field(min_length=12, max_length=1024)


class PoweroffRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirmation: str = Field(min_length=1, max_length=200)


class CommandRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: str = Field(min_length=1, max_length=40)
    payload: dict[str, Any] = Field(default_factory=dict)


class RestoreRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    media_id: str
    paths: list[str] = Field(default_factory=list, max_length=1000)
    archive_id: str | None = None
    target_name: str = "restore"


def create_app(config: WebConfig) -> FastAPI:
    config.validate()
    # SQLite needs reliable local filesystem locking; virtual local volumes are
    # allowed for catalogs, unlike the stricter physical staging qualification.
    from ..storage import filesystem, LOCAL_LINUX
    import platform

    for database_path in (
        (config.state / "control.sqlite", config.catalog)
        if config.role == "archive"
        else (config.state / "control.sqlite",)
    ):
        ancestor = database_path.parent
        while not ancestor.exists():
            ancestor = ancestor.parent
        info = filesystem(ancestor)
        supported = (
            info["type"] in LOCAL_LINUX
            if platform.system() == "Linux"
            else info["local"]
        )
        if not supported or info["read_only"]:
            raise SafetyError(
                "SQLite-Node-Daten benötigen ein lokales persistentes Dateisystem, keine Netzwerkfreigabe"
            )
    control = Control(config.state)
    accounts.bootstrap(control, config.username, config.password)
    if config.role == "archive":
        catalog = Catalog(config.catalog)
        catalog.close()
    view = CatalogView(config, control)
    modules = [
        Module("catalog", "Dateikatalog", False),
        Module("replication", "Katalog-Synchronisation", config.role == "archive"),
    ]
    if config.role == "archive":
        modules.append(Module("archive", "Archivierung und Staging", True))
    app = FastAPI(
        title="OpenTape Archive Manager",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.config = config
    app.state.control = control
    app.state.view = view
    app.add_middleware(SecurityMiddleware)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(config.allowed_hosts))

    @app.exception_handler(SafetyError)
    async def safety_error(request: Request, error: SafetyError):
        return JSONResponse({"error": str(error)}, status_code=409)

    @app.exception_handler(ValueError)
    async def invalid_error(request: Request, error: ValueError):
        return JSONResponse({"error": "Ungültige Eingabe"}, status_code=400)

    @app.exception_handler(OSError)
    async def io_error(request: Request, error: OSError):
        logging.getLogger("otam.web").error(
            "I/O-Fehler bei %s: %s", request.url.path, type(error).__name__
        )
        return JSONResponse(
            {
                "error": "Dateisystem oder Ressource nicht erreichbar; Serverprotokoll prüfen"
            },
            status_code=503,
        )

    @app.exception_handler(sqlite3.Error)
    async def database_error(request: Request, error: sqlite3.Error):
        logging.getLogger("otam.web").error(
            "Katalogfehler bei %s: %s", request.url.path, type(error).__name__
        )
        return JSONResponse(
            {
                "error": "Katalog konnte nicht sicher gelesen werden; Integrität und Speicher prüfen"
            },
            status_code=503,
        )

    @app.get("/healthz")
    def health():
        return {"status": "ok", "role": config.role}

    @app.post("/api/v1/login")
    def sign_in(data: LoginRequest, request: Request, response: Response):
        ip = request.client.host if request.client else "local"
        token, csrf, user = login(config, control, data.username, data.password, ip)
        response.set_cookie(
            cookie_name(config),
            token,
            max_age=config.session_seconds,
            httponly=True,
            secure=config.secure_cookie,
            samesite="strict",
            path="/",
        )
        return {"csrf": csrf, **user}

    api = APIRouter(prefix="/api/v1", dependencies=[Depends(session)])

    @api.get("/session")
    def current(request: Request):
        user = session(request)
        return {key: user[key] for key in ("csrf", "user_id", "username", "role", "locale", "mfa_state")}

    @api.get("/account")
    def account(request: Request):
        user = session(request)
        return {key: user[key] for key in ("user_id", "username", "role", "locale", "mfa_state")}

    @api.put("/account/locale")
    def account_locale(data: LocaleRequest, request: Request):
        return accounts.set_locale(control, session(request)["user_id"], data.locale)

    @api.post("/account/password")
    def account_password(data: PasswordRequest, request: Request):
        user = session(request)
        accounts.change_own_password(control, user["user_id"], data.current_password,
                                     data.new_password, user["hash"])
        return {"state": "UPDATED"}

    @api.get("/users", dependencies=[Depends(require_admin)])
    def users():
        return {"items": accounts.list_users(control)}

    @api.post("/system/poweroff", dependencies=[Depends(require_admin)], status_code=202)
    def poweroff(data: PoweroffRequest, request: Request):
        return power.request(config, control, session(request)["user_id"], data.confirmation)

    @api.get("/system/poweroff", dependencies=[Depends(require_admin)])
    def poweroff_status():
        enabled = config.role == "archive" and config.allow_host_shutdown
        return {"enabled": enabled, "service_active": power.unit_active() if enabled else False,
                "pending": control.shutdown_pending(), "last": control.get("shutdown_status")}

    @api.post("/users", dependencies=[Depends(require_admin)], status_code=201)
    def new_user(data: NewUserRequest):
        return accounts.create_user(control, data.username, data.password, data.role)

    @api.patch("/users/{ident}", dependencies=[Depends(require_admin)])
    def edit_user(ident: str, data: EditUserRequest):
        return accounts.update_user(control, ident, role=data.role, enabled=data.enabled,
                                    password=data.password)

    @api.post("/logout")
    def logout(request: Request, response: Response):
        with control.connect() as db:
            db.execute("DELETE FROM sessions WHERE hash=?", (session(request)["hash"],))
        response.delete_cookie(
            cookie_name(config),
            path="/",
            secure=config.secure_cookie,
            httponly=True,
            samesite="strict",
        )
        return {"state": "SIGNED_OUT"}

    @api.get("/node")
    def node():
        active = control.get("active_snapshot")
        return {
            "id": config.node_id,
            "name": config.name,
            "role": config.role,
            "version": __version__,
            "modules": [vars(m) for m in modules],
            "capabilities": {
                "catalog": True,
                "archive": config.role == "archive",
                "physical_tape": config.physical_archiving,
                "physical_multivolume": config.physical_multivolume,
                "physical_initialization": config.physical_initialization,
                "physical_reset": config.physical_reset,
                "physical_reinitialization": config.physical_reinitialization,
                "physical_maintenance": config.physical_maintenance,
            },
            "snapshot": active,
            "last_push": control.get("last_fanout", control.get("last_push")),
            "worker_heartbeat": control.get("worker_heartbeat", 0),
            "operation_mode": maintenance.mode(config, control),
            "staging_locations": (
                [
                    r
                    for r in resources.entries(config, control)
                    if r["kind"] == "staging"
                ]
                if config.role == "archive"
                else []
            ),
            "sources": (
                [
                    {"id": s.id, "label": s.label, "path": str(s.path)}
                    for s in resources.effective(config, control).sources
                ]
                if config.role == "archive"
                else []
            ),
            "sync_configured": bool(enabled_targets(config, control)),
            "sync_interval": config.sync_interval,
            "shutdown_enabled": config.role == "archive" and config.allow_host_shutdown,
            "publisher_id": config.publisher_id,
            "snapshot_age_seconds": (
                max(0, time.time() - active["created"]) if active else None
            ),
        }

    @api.get("/overview")
    def overview():
        return view.overview()

    @api.get("/media")
    def media():
        items = view.media()
        if config.role == "archive":
            with control.connect() as db:
                mounted_ids = {r[0] for r in db.execute("SELECT id FROM resources")}
            if maintenance.mode(config, control) == "physical":
                mounted_ids = set()
                for ident in physical_archive.bindings(control):
                    try:
                        mounted(config, control, ident)
                    except SafetyError:
                        continue
                    mounted_ids.add(ident)
            for item in items:
                item["mounted"] = item["id"] in mounted_ids
                item["plannable"] = item["mounted"] and item["state"] in ("READY", "IN_USE")
                item["backend"] = "simulator"
                if maintenance.mode(config, control) == "physical":
                    item["backend"] = "physical" if item["id"] in physical_archive.bindings(control) else "unregistered"
                    try:
                        physical_archive.planning_snapshot(config, control, item["id"])
                    except (SafetyError, ValueError, KeyError):
                        item["plannable"] = False
                    else:
                        item["plannable"] = True
        return {"items": items}

    @api.get("/archives")
    def archives(
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0, le=2147483647),
    ):
        return view.archives(limit, offset)

    @api.get("/files")
    def files(
        q: str = Query("", max_length=1000),
        checksum: str = Query("", max_length=64),
        file_type: str = Query("", max_length=100),
        media_id: str = "",
        archive_id: str = "",
        min_size: int | None = Query(None, ge=0, le=9223372036854775807),
        max_size: int | None = Query(None, ge=0, le=9223372036854775807),
        after: int | None = Query(None, ge=0, le=9223372036854775807),
        before: int | None = Query(None, ge=0, le=9223372036854775807),
        duplicates: bool = False,
        state: str = "",
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0, le=2147483647),
    ):
        return view.files(
            q=q,
            checksum=checksum,
            file_type=file_type,
            media_id=media_id,
            archive_id=archive_id,
            min_size=min_size,
            max_size=max_size,
            after=after,
            before=before,
            duplicates=duplicates,
            state=state,
            limit=limit,
            offset=offset,
        )

    @api.get("/jobs")
    def jobs():
        return {"items": view.jobs()}

    @api.get("/jobs/{ident}")
    def job(ident: str):
        return view.job(ident) | {
            "storage_binding": control.get("job_storage:" + ident)
        }

    @api.get("/jobs/{ident}/batch-option")
    def batch_option(ident: str):
        if config.role != 'archive':
            raise SafetyError('Nur auf dem Archive Node verfügbar')
        from . import batch
        return batch.offer(resources.effective(config, control),control,ident)

    @api.get("/staging")
    def staging():
        result: dict[str, Any] = {"items": view.staging(), "storage": None}
        if config.role == "archive":
            locations = resources.overview(config, control)
            result["locations"] = locations
            result["storage"] = resources.staging_capacity(locations)
        return result

    @api.get("/events")
    def events(
        job_id: str = "",
        before: int | None = Query(None, ge=1),
        limit: int = Query(100, ge=1, le=200),
    ):
        return {"items": view.events(job_id, limit, before)}

    @api.get("/verifications")
    def verifications():
        return {"items": view.verifications()}

    @api.get("/replication")
    def replication():
        with control.connect() as db:
            log = [
                dict(r)
                for r in db.execute("SELECT * FROM sync_log ORDER BY id DESC LIMIT 50")
            ]
        return {
            "active": control.get("active_snapshot"),
            "last_push": control.get("last_fanout", control.get("last_push")),
            "events": log,
            "peer_configured": any(
                t["kind"] == "catalog" for t in enabled_targets(config, control)
            ),
            "nas_configured": any(
                t["kind"] == "directory" for t in enabled_targets(config, control)
            ),
            "interval": config.sync_interval,
            "publisher": config.publisher_id,
            "mode": "publisher" if config.role == "archive" else "replica",
            "targets": (
                public_targets(config, control) if config.role == "archive" else []
            ),
            "local_catalog": config.role == "archive",
        }

    @api.put("/replication/targets/{ident}", dependencies=[Depends(require_admin)])
    def configure_target(ident: str, data: dict[str, Any] = Body()):
        save_target(config, control, ident, data)
        return {"items": public_targets(config, control)}

    @api.post("/replication/targets/{ident}/initialize", dependencies=[Depends(require_admin)])
    def initialize_target(ident: str, data: dict[str, Any] = Body()):
        if set(data) != {"confirmation"}:
            raise SafetyError("Node-ID-Bestätigung erforderlich")
        initialize_directory(config, control, ident, data["confirmation"])
        return {"state": "INITIALIZED"}

    @api.delete("/replication/targets/{ident}", dependencies=[Depends(require_admin)])
    def remove_target(ident: str):
        delete_target(config, control, ident)
        return {"items": public_targets(config, control)}

    @api.get("/export")
    def export(table: str = "files", format: str = "csv"):
        tables = {"media", "archives", "files", "jobs", "verifications", "restores"}
        if table not in tables or format not in {"csv", "json"}:
            raise HTTPException(400, "Ungültiges Exportformat")

        # Hold the connection/transaction for the stream, including replica swaps.
        def generate():
            with view.connect() as db:
                if db is None:
                    yield "[]" if format == "json" else ""
                    return
                cursor = db.execute(f'SELECT * FROM "{table}"')
                columns = [c[0] for c in cursor.description]
                if format == "json":
                    yield "["
                    first = True
                    for row in cursor:
                        yield ("" if first else ",") + json.dumps(
                            dict(row), ensure_ascii=True
                        )
                        first = False
                    yield "]"
                else:
                    buf = io.StringIO(newline="")
                    writer = csv.writer(buf)
                    writer.writerow(columns)
                    yield buf.getvalue()
                    for row in cursor:
                        buf.seek(0)
                        buf.truncate(0)
                        # Neutralize spreadsheet formulas in untrusted filenames/labels.
                        writer.writerow(
                            [
                                (
                                    "'" + v
                                    if isinstance(v, str) and v and v[:1] in "=+-@\t\r"
                                    else v
                                )
                                for v in row
                            ]
                        )
                        yield buf.getvalue()

        return StreamingResponse(
            generate(),
            media_type=(
                "application/json" if format == "json" else "text/csv; charset=utf-8"
            ),
            headers={
                "Content-Disposition": f'attachment; filename="otam-{table}.{format}"'
            },
        )

    app.include_router(api)
    if config.role == "archive":
        archive = APIRouter(prefix="/api/v1", dependencies=[Depends(session)])

        @archive.get("/commands")
        def commands():
            return {"items": control.commands()}

        @archive.post("/commands", status_code=202)
        def command(
            data: CommandRequest,
            idempotency_key: Annotated[str, Header(min_length=8, max_length=128)],
            request: Request,
        ):
            if data.kind in ("tape-maintenance", "staging-speedtest", "register-physical", "initialize-physical", "reset-physical", "reinitialize-physical"):
                require_admin(request)
            validate_command(config, control, data.kind, data.payload)
            result = control.enqueue(data.kind, data.payload, idempotency_key)
            return {
                "id": result["id"],
                "kind": result["kind"],
                "state": result["state"],
            }

        @archive.get("/staging/speedtests")
        def staging_speedtests():
            catalog = Catalog(config.catalog)
            try:
                reports = []
                for row in catalog.db.execute(
                    "SELECT report_json FROM storage_benchmarks ORDER BY time DESC LIMIT 20"
                ):
                    report = json.loads(row[0])
                    samples = report.pop("samples", [])
                    report["sample_count"] = len(samples)
                    report["recent_samples"] = samples[-30:]
                    reports.append(report)
            finally:
                catalog.close()
            return {
                "items": reports,
                "progress": {
                    r["id"]: control.get("speedtest_progress:" + r["id"])
                    for r in resources.entries(config, control) if r["kind"] == "staging"
                },
                "settings": {
                    r["id"]: control.get("transfer_settings:" + r["id"])
                    for r in resources.entries(config, control) if r["kind"] == "staging"
                },
                "drive_profiles": drive_speed_profiles(control.get("hardware_inventory")),
            }

        @archive.put("/staging/transfer-settings/{ident}", dependencies=[Depends(require_admin)])
        def transfer_settings(ident: str, data: dict[str, Any] = Body()):
            staging = resources.staging_for(config, control, ident)
            from ..storage import require_local
            storage = require_local(staging)
            if set(data) != {"drive_id", "write_rate_bytes_per_second", "buffer_bytes"}:
                raise SafetyError("Laufwerk, Schreibrate und Puffergröße erforderlich")
            if not isinstance(data["drive_id"], str):
                raise SafetyError("Ungültige Laufwerks-ID")
            profile = selected_speed_profile(control.get("hardware_inventory"), data["drive_id"])
            if profile is None:
                raise SafetyError("Kein aktuell erkanntes Laufwerk mit bestätigtem Geschwindigkeitsprofil")
            rate, buffer = data["write_rate_bytes_per_second"], data["buffer_bytes"]
            if (type(rate) is not int or type(buffer) is not int
                    or rate not in profile["speed_steps_bytes_per_second"]
                    or not 256 * 1024 ** 2 <= buffer <= 4 * 1024 ** 3
                    or buffer % (64 * 1024 ** 2)):
                raise SafetyError("Schreibrate wird vom erkannten Laufwerksprofil nicht unterstützt oder Puffergröße ist ungültig")
            with control.connect() as db:
                if db.execute("SELECT 1 FROM commands WHERE kind IN ('backup','backup-set') AND state='RUNNING'").fetchone():
                    raise SafetyError("Transferwerte während eines Archivjobs nicht ändern")
            value = {"write_rate_bytes_per_second": rate, "buffer_bytes": buffer,
                     "updated": time.time(), "effective": False,
                     "drive_id": profile["drive_id"], "drive_serial": profile["drive_serial"],
                     "profile_id": profile["profile_id"],
                     "medium_density_code": profile["medium_density_code"],
                     "storage": {key: storage[key] for key in ("mount", "source", "device", "type")}}
            control.set("transfer_settings:" + ident, value)
            control.sync_event("config", "UPDATED", None,
                               "Vorgemerkte Transferwerte für Staging: " + ident)
            return value

        @archive.post("/restore-plan")
        def restore_plan(data: RestoreRequest):
            payload = data.model_dump(exclude_none=True)
            validate_command(config, control, "restore", payload)
            catalog = Catalog(config.catalog)
            try:
                from ..service import ArchiveService

                result = ArchiveService(
                    catalog, mounted(config, control, data.media_id)
                ).restore_plan(data.media_id, data.paths or None, data.archive_id)
                return {**result, "target": str(config.restore_root / data.target_name)}
            finally:
                catalog.close()

        @archive.get("/directories")
        def directories(path: str = Query("", max_length=4096)):
            return resources.browse(config, control, path)

        @archive.get("/source-tree")
        def source_tree(source_id: str = Query(max_length=100),
                        path: str = Query("", max_length=4096),
                        offset: int = Query(0, ge=0, le=1_000_000)):
            return resources.source_tree(config, control, source_id, path, offset)

        @archive.get("/storage-resources")
        def storage_resources():
            return {"items": resources.overview(config, control)}

        @archive.put("/storage-resources/{ident}", dependencies=[Depends(require_admin)])
        def save_resource(ident: str, data: dict[str, Any] = Body()):
            resources.save(config, control, ident, data)
            return {"state": "REGISTERED"}

        @archive.delete("/storage-resources/{ident}", dependencies=[Depends(require_admin)])
        def remove_resource(ident: str):
            resources.remove(config, control, ident)
            return {"state": "REMOVED", "files_deleted": False}

        @archive.put("/operation-mode", dependencies=[Depends(require_admin)])
        def operation_mode(data: dict[str, Any] = Body()):
            if set(data) != {"mode"}:
                raise SafetyError("Betriebsart fehlt")
            maintenance.set_mode(config, control, data["mode"])
            return {"mode": maintenance.mode(config, control)}

        @archive.post("/initialization/prepare", dependencies=[Depends(require_admin)])
        def initialization_prepare(data: dict[str, Any] = Body()):
            return initialization.prepare(config, control, data)

        @archive.post("/reinitialization/prepare", dependencies=[Depends(require_admin)])
        def reinitialization_prepare(data: dict[str, Any] = Body()):
            return initialization.prepare(config, control, data, reinitialize=True)

        @archive.post("/reset/prepare", dependencies=[Depends(require_admin)])
        def reset_prepare(data: dict[str, Any] = Body()):
            return reset.prepare(config, control, data)

        @archive.post("/maintenance/prepare", dependencies=[Depends(require_admin)])
        def maintenance_prepare(data: dict[str, Any] = Body()):
            if set(data) != {"drive_id", "operation"} or not isinstance(
                data["drive_id"], str
            ):
                raise SafetyError("Ungültige Wartungsplanung")
            return maintenance.prepare(
                config, control, data["drive_id"], data["operation"]
            )

        @archive.get("/hardware/status")
        def hardware_status():
            return diagnostics.overview(control)

        @archive.get("/hardware/diagnostics/{ident}")
        def hardware_diagnostics(ident: str):
            import re

            if not re.fullmatch("[0-9a-f]{32}", ident):
                raise HTTPException(400, "Ungültige Laufwerks-ID")
            result = diagnostics.detail(control, ident)
            if result["sample"] is None:
                raise HTTPException(
                    404, "Noch keine Diagnosedaten dieses Laufwerks vorhanden"
                )
            return result

        @archive.get("/hardware")
        def hardware():
            with control.connect() as db:
                history = [
                    json.loads(r[0])
                    for r in db.execute(
                        "SELECT value FROM settings WHERE key LIKE 'maintenance_progress:%' ORDER BY rowid DESC LIMIT 30"
                    )
                ]
            return {
                "inventory": discover(),
                "physical_tape_enabled": config.physical_archiving,
                "physical_maintenance_enabled": config.physical_maintenance,
                "physical_initialization_enabled": config.physical_initialization,
                "physical_reset_enabled": config.physical_reset,
                "physical_reinitialization_enabled": config.physical_reinitialization,
                "media_actions": {d["id"]: {
                    "initialization": initialization.availability(config,control,d),
                    "reset": reset.availability(config,control,d),
                    "reinitialization": reinitialization.availability(config,control,d)}
                    for d in control.get("hardware_inventory", {"drives":[]}).get("drives",[])},
                "mode": maintenance.mode(config, control),
                "discovery": control.get(
                    "hardware_inventory", {"time": 0, "drives": []}
                ),
                "maintenance": history,
                "status": diagnostics.overview(control),
                "message": ("Physische Archivierung ist administrativ freigegeben. Initialisierung erfolgt niemals automatisch."
                            if config.physical_archiving else
                            "Physischer Wartungsbetrieb mit Einzelfreigaben; reguläre LTO-Archivierung wartet auf Bandformat-Abnahme"),
            }

        app.include_router(archive)
    else:
        receive_lock = threading.Lock()

        @app.put("/api/v1/replication/snapshot")
        async def receive(request: Request):
            if not config.publisher_id or config.peer_key_file is None:
                raise HTTPException(
                    503, "Herausgeber und Peer-Schlüssel zuerst konfigurieren"
                )
            if not hmac.compare_digest(
                request.headers.get("authorization", "").encode(),
                b"Bearer " + config.peer_key(),
            ):
                raise HTTPException(401, "Ungültiger Peer-Zugang")
            meta = decode_header(request.headers.get("x-otam-manifest", ""), config)
            if request.headers.get("content-length") != str(meta["bytes"]):
                raise HTTPException(
                    400, "Übertragungsgröße stimmt nicht mit Manifest überein"
                )
            if not receive_lock.acquire(blocking=False):
                raise HTTPException(409, "Eine Katalogübertragung läuft bereits")
            temporary = None
            try:
                folder = config.state / "snapshots"
                folder.mkdir(exist_ok=True, mode=0o700)
                if shutil.disk_usage(folder).free < meta["bytes"] + 16 * 1024**2:
                    raise HTTPException(507, "Nicht genügend freier Katalogspeicher")
                fd, name = tempfile.mkstemp(
                    prefix=".receiving-", suffix=".partial", dir=folder
                )
                temporary = Path(name)
                size = 0
                checksum = hashlib.sha256()
                with os.fdopen(fd, "wb") as target:
                    async for chunk in request.stream():
                        size += len(chunk)
                        if size > meta["bytes"]:
                            raise SafetyError(
                                "Snapshot überschreitet deklarierte Größe"
                            )
                        checksum.update(chunk)
                        target.write(chunk)
                    target.flush()
                    os.fsync(target.fileno())
                if size != meta["bytes"] or checksum.hexdigest() != meta["sha256"]:
                    raise SafetyError(
                        "Unvollständiger oder beschädigter Katalogtransfer"
                    )
                return await run_in_threadpool(
                    publish, config, control, temporary, meta
                )
            except Exception:
                control.sync_event(
                    "receive",
                    "FAILED",
                    meta["sequence"],
                    "Snapshot nicht veröffentlicht",
                )
                raise
            finally:
                if temporary:
                    temporary.unlink(missing_ok=True)
                receive_lock.release()

    app.mount("/assets", StaticFiles(directory=STATIC), name="assets")

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(STATIC / "index.html")

    return app
