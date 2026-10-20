#!/usr/bin/env python3
"""Explicit small physical HTTP/CLI/worker acceptance on an existing test medium.

No initialization, deletion, production credentials or source changes. Uses an
isolated configuration/catalog, then imports only successfully verified new
archive metadata into the unchanged live catalog in one transaction.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import sqlite3
import subprocess
import sys
import time
import uuid
from contextlib import contextmanager
from dataclasses import asdict, replace
from pathlib import Path
from unittest.mock import patch

from otam.catalog import Catalog
from otam.common import SafetyError, encode, sha256, sync_dir
from otam.physical import discover_drives
from otam.tape import LinuxTape
from otam.web.config import Resource, WebConfig, password_hash
from otam.web.control import Control
from otam.web.worker import run_once, worker_lock
from otam.transfer import PROFILE_MAX_AGE_SECONDS


def refresh_inventory(control):
    """Match the normal worker's between-job scan without extending cache age.

    run_once deliberately does not run the worker loop's periodic diagnostics.
    Long physical positioning can outlive the profile TTL even for tiny inputs.
    Only a new real discovery may renew it, and only between completed jobs.
    """
    observed = control.get("hardware_inventory", {}).get("time", 0)
    if not 0 <= time.time() - observed <= PROFILE_MAX_AGE_SECONDS:
        from otam.web import diagnostics
        diagnostics.scan(control)


def archive_rows(db, media):
    return [dict(row) for row in db.execute(
        "SELECT id,tape_file,state,bytes,sha256 FROM archives WHERE media_id=? ORDER BY tape_file", (media,))]


def main() -> None:
    from fastapi.testclient import TestClient
    from otam.web.app import create_app
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--report-root", required=True, type=Path)
    parser.add_argument("--drive-serial", required=True)
    parser.add_argument("--medium-serial", required=True)
    parser.add_argument("--media-id", required=True)
    parser.add_argument("--confirm", required=True, help="APPEND <drive serial> <MAM serial>")
    args = parser.parse_args()
    if args.confirm != f"APPEND {args.drive_serial} {args.medium_serial}":
        raise SafetyError("Exact append authorization is required")
    live = WebConfig.load(args.config)
    if live.role != "archive" or not live.physical_maintenance:
        raise SafetyError("Physical acceptance is not configured")
    root = args.report_root.resolve()
    if (root.is_relative_to(live.staging) or live.staging.is_relative_to(root)
            or live.catalog.is_relative_to(root) or root.is_relative_to(live.state)):
        raise SafetyError("Report root must be separate from live state and staging")
    report = {"id": str(uuid.uuid4()), "state": "RUNNING", "started": time.time(),
              "events": [], "data_reads": [], "moves": [], "writes": [],
              "scope": "small synthetic HTTP/CLI/worker append and restore; no old payload scrub"}
    phase = "PREPARING"

    def record(event, **values):
        report["events"].append({"time": time.time(), "event": event, **values})
        with (root / "report.json.tmp").open("w") as stream:
            json.dump(report, stream, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(root / "report.json.tmp", root / "report.json")
        sync_dir(root)
        print(json.dumps({"event": event, **values}), flush=True)

    class ObservedTape(LinuxTape):
        def __init__(self, *values, **options):
            super().__init__(*values, **options)
            self.device.lock_root = live.state / "drive-locks"

        def _move(self, operation, count=None):
            report["moves"].append({"phase": phase, "operation": operation, "count": count})
            return super()._move(operation, count)

        @contextmanager
        def open_read(self, position):
            if position % 2:
                report["data_reads"].append({"phase": phase, "position": position})
                record("DATA_READ", phase=phase, position=position)
            with super().open_read(position) as stream:
                yield stream

        def append(self, source, expected_media):
            if (expected_media != args.media_id or self.device.expected["serial"] != args.drive_serial
                    or self.device.expected["medium_serial"] != args.medium_serial):
                raise SafetyError("Acceptance forbids another drive/cartridge")
            # The base adapter still checks fresh identity, EOD and pending state.
            position = super().append(source, expected_media)
            report["writes"].append(position)
            record("TAPE_FILE_WRITTEN", position=position)
            return position

        def initialize(self, *unused, **options):
            raise SafetyError("Acceptance forbids initialization")

    with worker_lock(live):
        control = Control(live.state)
        if control.shutdown_pending():
            raise SafetyError("Shutdown is pending")
        with control.connect() as db:
            if db.execute("SELECT 1 FROM commands WHERE state='RUNNING'").fetchone():
                raise SafetyError("The live worker was not idle")
        drives = [d for d in discover_drives() if d.get("serial") == args.drive_serial
                  and d.get("medium_serial") == args.medium_serial and d.get("ready")]
        if len(drives) != 1:
            raise SafetyError("Authorized writable drive/MAM pair is not uniquely present")
        drive = drives[0]
        if LinuxTape(drive, live.state)._pending.exists():
            raise SafetyError("An unresolved live physical write exists")
        root.mkdir(mode=0o700, parents=True, exist_ok=False)
        record("START", drive=drive)
        try:
            original = sqlite3.connect(live.catalog.as_uri() + "?mode=ro", uri=True)
            original.row_factory = sqlite3.Row
            copied = sqlite3.connect(root / "catalog.sqlite")
            try:
                baseline = archive_rows(original, args.media_id)
                if not baseline or any(row["state"] != "VERIFIED" for row in baseline):
                    raise SafetyError("Expected a fully catalogued verified test prefix")
                original.backup(copied)
            finally:
                original.close()
                copied.close()
            initial = baseline[-1]["tape_file"] + 2
            source = root / "synthetic-source"
            source.mkdir(mode=0o700)
            for number in (1, 2):
                with (source / f"{report['id']}-payload-{number}.bin").open("xb") as stream:
                    stream.write(hashlib.shake_256(f"web-cli-{number}".encode()).digest(1024**2))
                    stream.flush()
                    os.fsync(stream.fileno())
            (source / (report["id"] + "-README.txt")).write_text("OTAM synthetic web/CLI acceptance.\n")
            checksums = {path.name: sha256(path) for path in source.iterdir()}
            password = secrets.token_urlsafe(24)
            config = replace(live, state=root / "state", catalog=root / "catalog.sqlite",
                             media_root=root / "simulator", restore_root=live.staging / ("acceptance-web-cli-" + report["id"]),
                             sources=(Resource("acceptance-source", "Synthetic acceptance", source),),
                             directory_roots=(source,), password=password_hash(password),
                             physical_archiving=True, allowed_hosts=("testserver",), secure_cookie=False,
                             peer_url="", peer_key_file=None, publisher_id="", nas_backup=None,
                             allow_host_shutdown=False)
            config.validate()
            config_file = root / "node.json"
            config_file.write_text(json.dumps(asdict(config), default=str, indent=2))
            config_file.chmod(0o400)
            app = create_app(config)
            test_control = app.state.control
            test_control.set("operation_mode", "physical")
            test_control.set("hardware_inventory", {"time": time.time(), "drives": [drive]})
            record("FIXTURES_READY", checksums=checksums, initial_tape_files=initial)

            with worker_lock(config), patch("otam.web.physical_archive.LinuxTape", ObservedTape), TestClient(app) as client:
                response = client.post("/api/v1/login", json={"username": config.username, "password": password})
                if response.status_code != 200:
                    raise SafetyError("Isolated HTTP login failed")
                headers = {"X-CSRF-Token": response.json()["csrf"]}

                def finish_command(ident):
                    if not run_once(config, test_control):
                        raise SafetyError("No queued command was executed")
                    command = next(c for c in test_control.commands() if c["id"] == ident)
                    if command["state"] != "SUCCEEDED":
                        raise SafetyError("Worker command failed: " + str(command.get("error")))
                    record("COMMAND_COMPLETE", kind=command["kind"], result=command["result"])
                    refresh_inventory(test_control)
                    return command["result"]

                def enqueue(kind, payload):
                    refresh_inventory(test_control)
                    response = client.post("/api/v1/commands", json={"kind": kind, "payload": payload},
                                           headers={**headers, "Idempotency-Key": str(uuid.uuid4())})
                    if response.status_code != 202:
                        raise SafetyError(f"HTTP {kind} failed: {response.status_code} {response.text}")
                    return finish_command(response.json()["id"])

                phase = "REGISTER"
                registered = enqueue("register-physical", {"drive_id": drive["id"], "drive_serial": args.drive_serial,
                                                          "medium_serial": args.medium_serial})
                if registered["media_id"] != args.media_id:
                    raise SafetyError("Registered a different physical header")
                response = client.put("/api/v1/staging/transfer-settings/default-staging", headers=headers,
                                      json={"drive_id": drive["id"], "write_rate_bytes_per_second": 120_000_000,
                                            "buffer_bytes": 2368 * 1024**2})
                if response.status_code != 200:
                    raise SafetyError("HTTP transfer settings failed: " + response.text)
                phase = "PLAN"
                plan = enqueue("plan", {"media_id": args.media_id, "source_id": "acceptance-source",
                                        "staging_id": "default-staging", "target": 1_500_000, "verify_mode": "media"})
                phase = "STAGE"
                payload_file = root / "stage-payload.json"
                payload_file.write_text(json.dumps({"job_id": plan["job_id"]}))
                queued = subprocess.run([sys.executable, "-m", "otam", "physical-command", "--config", str(config_file),
                                         "--kind", "stage", "--payload-file", str(payload_file)],
                                        capture_output=True, text=True, check=False)
                if queued.returncode:
                    raise SafetyError("CLI staging failed: " + queued.stderr)
                finish_command(json.loads(queued.stdout)["id"])
                status = subprocess.run([sys.executable, "-m", "otam", "physical-command-status", "--config", str(config_file),
                                         "--command-id", json.loads(queued.stdout)["id"]],
                                        capture_output=True, text=True, check=False)
                if status.returncode or json.loads(status.stdout)["state"] != "SUCCEEDED":
                    raise SafetyError("CLI command status did not confirm completed staging")
                phase = "BACKUP"
                archived = enqueue("backup", {"job_id": plan["job_id"], "confirm": plan["job_id"],
                                               "plan_hash": plan["sha256"]})
                if archived["state"] != "VERIFIED" or len(archived["archives"]) != 2:
                    raise SafetyError("The small regular backup was not verified as two TARs")
                phase = "RESTORE"
                restored = enqueue("restore", {"media_id": args.media_id, "paths": list(checksums), "target_name": "verified"})
                for name, checksum in checksums.items():
                    if sha256(config.restore_root / "verified" / name) != checksum:
                        raise SafetyError("Restored fixture SHA-256 differs")
                new_positions = [initial, initial + 2]
                if report["writes"] != list(range(initial, initial + 4)):
                    raise SafetyError("Unexpected physical append positions")
                for current in ("BACKUP", "RESTORE"):
                    if [r["position"] for r in report["data_reads"] if r["phase"] == current] != new_positions:
                        raise SafetyError("Selected data read count/order differs")
                if any(r["position"] < initial for r in report["data_reads"]):
                    raise SafetyError("Acceptance unexpectedly read an old payload")
                observed = Catalog(config.catalog)
                try:
                    samples = [json.loads(r[0]) for r in observed.db.execute(
                        "SELECT details_json FROM events WHERE job_id=? AND event='io_progress'", (plan["job_id"],))]
                    samples = [s for s in samples if s.get("phase") == "TAPE_WRITE"]
                    if not samples or any(s.get("write_rate_bytes_per_second") != 120_000_000
                                          or s.get("buffer_bytes") != 2368 * 1024**2 for s in samples):
                        raise SafetyError("Actual physical transfer samples differ from saved policy")
                    report["transfer_samples"] = samples
                finally:
                    observed.close()
                record("PIPELINE_VERIFIED", archive_job=plan["job_id"], restored=restored, checksums=checksums)
            import_verified(live, config, args.media_id, baseline, plan["job_id"], root, report)
            report.update(state="VERIFIED", finished=time.time())
            record("COMPLETE")
        except BaseException as error:
            report.update(state="FAILED", finished=time.time(), error=str(error))
            record("FAILED", error=str(error))
            raise


def import_verified(live, tested, media, baseline, source_job, root, report):
    """Import only newly verified test archive records, preserving the live prefix."""
    source, destination = Catalog(tested.catalog), Catalog(live.catalog)
    try:
        if archive_rows(destination.db, media) != baseline:
            raise SafetyError("Live catalog changed during isolated acceptance; import refused")
        if archive_rows(source.db, media)[:len(baseline)] != baseline:
            raise SafetyError("Isolated catalog prefix changed")
        rows = list(source.db.execute("SELECT * FROM archives WHERE job_id=? ORDER BY tape_file", (source_job,)))
        job = source.db.execute("SELECT * FROM jobs WHERE id=?", (source_job,)).fetchone()
        if job["state"] != "VERIFIED" or len(rows) != 2 or any(row["state"] != "VERIFIED" for row in rows):
            raise SafetyError("Only a completely verified synthetic job may be imported")
        imported = str(uuid.uuid4())
        now = time.time()
        with destination.db:
            destination.db.execute("INSERT INTO jobs(id,kind,state,media_id,created,updated,report_json,phase) VALUES(?,?,?,?,?,?,?,?)",
                (imported, "acceptance-import", "VERIFIED", media, now, now,
                 encode({"source_report": str(root / "report.json"), "source_job": source_job}).decode(), "VERIFIED"))
            for row in rows:
                destination.record_archive(json.loads(row["manifest_json"]), imported, row["tape_file"],
                                           "VERIFIED", row["bytes"], row["sha256"], transaction=False)
            used = source.db.execute("SELECT used FROM media WHERE id=?", (media,)).fetchone()[0]
            destination.db.execute("UPDATE media SET used=?,writes=writes+?,last_use=? WHERE id=?", (used, len(rows), now, media))
            destination.db.execute("INSERT INTO events(job_id,time,level,event,details_json) VALUES(?,?,?,?,?)",
                                   (imported, now, "INFO", "verified_acceptance_import",
                                    encode({"source_job": source_job, "archives": [r["id"] for r in rows]}).decode()))
        report["live_catalog_import"] = {"job_id": imported, "archives": [r["id"] for r in rows]}
    finally:
        source.close()
        destination.close()


if __name__ == "__main__":
    main()
