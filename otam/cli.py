"""CLI adapter; physical commands use the separately gated durable worker."""
from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import tarfile
import sys
import uuid
from pathlib import Path
from typing import Any

from .catalog import Catalog
from .common import SafetyError
from .hardware import discover
from .service import ArchiveService
from .tape import SimulatedTape
from .storage import require_local
from .benchmark import run_benchmark


def parser() -> argparse.ArgumentParser:
    cli = argparse.ArgumentParser(description="OTAM catalog, simulator and explicitly enabled physical archive worker")
    cli.add_argument("--db", type=Path, default=Path(".otam/catalog.sqlite"))
    sub = cli.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor", help="Read-only environment inventory; does not open tape devices")
    physical = sub.add_parser("physical-command", help="Queue a reviewed physical-node command through the durable worker")
    physical.add_argument("--config", required=True, type=Path)
    physical.add_argument("--kind", required=True, choices=("register-physical", "initialize-physical", "reset-physical", "reinitialize-physical", "plan-source", "bind-plan", "plan", "stage", "backup", "backup-set", "verify", "restore", "recover", "rebuild"))
    physical.add_argument("--payload-file", required=True, type=Path)
    physical.add_argument("--idempotency-key", default=None)
    physical_status = sub.add_parser("physical-command-status", help="Inspect a queued physical command without device access")
    physical_status.add_argument("--config", required=True, type=Path)
    physical_status.add_argument("--command-id", required=True)
    web_init = sub.add_parser("web-init", help="Create a private node configuration; no tape operations")
    web_init.add_argument("--config", required=True, type=Path)
    web_init.add_argument("--root", required=True, type=Path)
    web_init.add_argument("--role", choices=("archive", "catalog"), default="archive")
    web_init.add_argument("--source", type=Path, action="append", default=[])
    web_init.add_argument("--password-file", type=Path, help="Mode 0600 file; otherwise prompt securely")
    for name in ("serve", "worker"):
        web_command = sub.add_parser(name, help="Run the optional web server or separate durable worker")
        web_command.add_argument("--config", required=True, type=Path)
        if name == "worker":
            web_command.add_argument("--once", action="store_true")

    create = sub.add_parser("init-sim", help="Create a NEW simulator directory, never a physical tape")
    create.add_argument("medium", type=Path)
    create.add_argument("--label", default="Test medium")
    create.add_argument("--capacity", type=int, default=800_000_000_000, help="Native bytes")
    create.add_argument("--class", dest="media_class", choices=("permanent", "rotation"), default="permanent")
    register = sub.add_parser("register-sim", help="Read and register an existing simulator header")
    register.add_argument("medium", type=Path)
    plan = sub.add_parser("plan")
    plan.add_argument("medium", type=Path)
    plan.add_argument("source", type=Path)
    plan.add_argument("--media-id", required=True)
    plan.add_argument("--target", type=int, default=75_000_000_000, help="Target archive size in bytes")
    backup = sub.add_parser("backup")
    backup.add_argument("medium", type=Path)
    backup.add_argument("job_id")
    backup.add_argument("--confirm", required=True, help="Reviewed job ID; simulator only")
    backup.add_argument("--staging", "--spool", dest="spool", type=Path, default=Path(".otam/staging"))
    backup.add_argument("--resume", action="store_true", help="Explicit recovery after full media/position recheck")
    backup.add_argument("--prepare-all", action="store_true", help="Prepare all archives before the first write")
    stage = sub.add_parser("stage", help="Prepare all TARs locally without accessing the tape")
    stage.add_argument("job_id")
    stage.add_argument("--staging", "--spool", dest="spool", type=Path, default=Path(".otam/staging"))
    stage.add_argument("--revalidate-ready", action="store_true", help="Explicit full recertification of metadata-only READY changes before any tape attempt")
    status = sub.add_parser("staging-status")
    status.add_argument("--staging", required=True, type=Path)
    status.add_argument("--job-id")
    bench = sub.add_parser("staging-benchmark", help="Read-only long Linux direct-I/O test of an existing staging file")
    bench.add_argument("--staging", required=True, type=Path)
    bench.add_argument("--file", required=True, type=Path)
    bench.add_argument("--seconds", type=float, default=1800)
    bench.add_argument("--min-rate", type=int, default=120_000_000)
    for name in ("verify", "rebuild", "recover-jobs", "restore-plan", "restore"):
        command = sub.add_parser(name)
        command.add_argument("medium", type=Path)
        command.add_argument("--media-id", required=True)
        if name.startswith("restore"):
            command.add_argument("--path", action="append", dest="paths")
            command.add_argument("--archive-id")
        if name in ("restore", "restore-plan"):
            command.add_argument("--target", required=True, type=Path)
    search = sub.add_parser("search")
    search.add_argument("query", nargs="?", default="")
    search.add_argument("--sha256")
    export = sub.add_parser("export")
    export.add_argument("--format", choices=("json", "csv"), default="json")
    export.add_argument("--table", choices=("files", "media", "archives"), default="files")
    sub.add_parser("jobs")
    return cli


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    catalog = None
    try:
        result: Any
        if args.command in ("physical-command", "physical-command-status"):
            from .web.config import WebConfig
            from .web.control import Control
            from .web import physical_archive
            from .web.worker import validate_command
            config = WebConfig.load(args.config)
            control = Control(config.state)
            if args.command == "physical-command":
                physical_archive.require_mode(config, control, archive=args.kind != "register-physical")
                if args.payload_file.stat().st_size > 1024**2:
                    raise SafetyError("Command payload exceeds 1 MiB")
                payload = json.loads(args.payload_file.read_text())
                if not isinstance(payload, dict):
                    raise SafetyError("Command payload must be a JSON object")
                validate_command(config, control, args.kind, payload)
                row = control.enqueue(args.kind, payload, args.idempotency_key or str(uuid.uuid4()))
                result = {key: row[key] for key in ("id", "kind", "state", "idempotency")}
            else:
                uuid.UUID(args.command_id)
                with control.connect() as db:
                    row = db.execute("SELECT * FROM commands WHERE id=?", (args.command_id,)).fetchone()
                if row is None:
                    raise SafetyError("Command not found")
                result = dict(row)
                for key in ("payload", "result"):
                    if result[key] is not None:
                        result[key] = json.loads(result[key])
        elif args.command == "web-init":
            import getpass
            from .web.config import initialize
            if args.password_file:
                if args.password_file.is_symlink() or args.password_file.stat().st_mode & 0o077:
                    raise SafetyError("Password file requires mode 0600 and must not be a symlink")
                password = args.password_file.read_text().rstrip("\r\n")
            else:
                password = getpass.getpass("Neues OTAM-Passwort (mindestens 12 Zeichen): ")
                if password != getpass.getpass("Passwort wiederholen: "):
                    raise SafetyError("Passwörter stimmen nicht überein")
            initialize(args.config, args.root, args.role, password, args.source)
            result = {"config": str(args.config.resolve()), "role": args.role, "state": "CONFIGURED"}
        elif args.command in ("serve", "worker"):
            from .web.config import WebConfig
            config = WebConfig.load(args.config)
            if args.command == "worker":
                from .web.worker import run_worker
                run_worker(config, once=args.once)
            else:
                try:
                    import uvicorn
                    from .web.app import create_app
                except ImportError as error:
                    raise SafetyError("Web dependencies missing; install OTAM with the [web] extra") from error
                uvicorn.run(create_app(config), host=config.host, port=config.port,
                            proxy_headers=bool(config.trusted_proxy_ips),
                            forwarded_allow_ips=",".join(config.trusted_proxy_ips),
                            server_header=False, workers=1,
                            timeout_keep_alive=5, limit_concurrency=100)
            return 0
        elif args.command == "doctor":
            result = discover()
        else:
            catalog = Catalog(args.db)
            if args.command == "staging-benchmark":
                result = run_benchmark(catalog, args.staging, args.file, seconds=args.seconds, min_rate=args.min_rate)
                print(json.dumps(result, indent=2))
                return 0 if result["qualified"] else 1
            elif args.command == "staging-status":
                storage = require_local(args.staging)
                sql = "SELECT * FROM staged_archives WHERE root=?"
                params: list[Any] = [str(args.staging.resolve())]
                if args.job_id:
                    sql += " AND job_id=?"
                    params.append(args.job_id)
                result = {"storage": storage, "archives": [dict(r) for r in catalog.db.execute(sql, params)],
                          "latest_metrics": [dict(r) for r in catalog.db.execute(
                              "SELECT * FROM events WHERE event IN ('io_progress','staging_progress','staging_read_sample') ORDER BY seq DESC LIMIT 20")]}
            elif args.command == "stage":
                # Staging is deliberately independent of a currently attached drive/medium.
                class NoTape:
                    pass
                result = ArchiveService(catalog, NoTape()).stage(args.job_id, args.spool, revalidate_ready=args.revalidate_ready)
            elif args.command == "search":
                result = catalog.search(args.query, args.sha256)
            elif args.command == "jobs":
                result = [dict(row) for row in catalog.db.execute("SELECT * FROM jobs ORDER BY created DESC")]
            elif args.command == "export":
                result = catalog.export()
                if args.format == "csv":
                    rows = result[args.table]
                    if rows:
                        writer = csv.DictWriter(sys.stdout, fieldnames=list(rows[0]))
                        writer.writeheader()
                        writer.writerows(rows)
                    return 0
            else:
                tape = (SimulatedTape.create(args.medium, args.label, args.capacity, args.media_class)
                        if args.command == "init-sim" else SimulatedTape(args.medium))
                service = ArchiveService(catalog, tape)
                if args.command in ("init-sim", "register-sim"):
                    result = service.register()
                elif args.command == "plan":
                    result = service.plan(args.source, args.media_id, args.target)
                elif args.command == "backup":
                    result = service.backup(args.job_id, args.confirm, args.spool, resume=args.resume, prepare_all=args.prepare_all)
                elif args.command == "verify":
                    result = service.verify(args.media_id)
                elif args.command == "rebuild":
                    result = service.rebuild(args.media_id)
                elif args.command == "recover-jobs":
                    result = {"interrupted_jobs": service.recover_jobs(args.media_id)}
                elif args.command == "restore-plan":
                    result = {**service.restore_plan(args.media_id, args.paths, args.archive_id), "target": str(args.target.absolute())}
                else:
                    result = service.restore(args.media_id, args.target, args.paths, args.archive_id)
        print(json.dumps(result, ensure_ascii=True, indent=2))
        return 0
    except KeyboardInterrupt:
        print(json.dumps({"error": "Interrupted; inspect job log and medium before further actions"}), file=sys.stderr)
        return 130
    except (SafetyError, OSError, ValueError, KeyError, TypeError, tarfile.TarError,
            sqlite3.Error) as error:
        print(json.dumps({"error": str(error), "type": type(error).__name__}), file=sys.stderr)
        return 1
    finally:
        if catalog is not None:
            catalog.close()
