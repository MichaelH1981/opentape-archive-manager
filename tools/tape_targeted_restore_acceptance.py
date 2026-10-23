#!/usr/bin/env python3
"""Read-only targeted restore acceptance; never initialize or append a tape.

Run as otam with its real TMPDIR after stopping the idle worker. The catalog
is copied, and all output is exclusive to a new report directory/restore target.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

from otam.catalog import Catalog
from otam.common import SafetyError, sha256, sync_dir
from otam.physical import discover_drives
from otam.service import ArchiveService
from otam.tape import LinuxTape
from otam.web.config import WebConfig
from otam.web.control import Control
from otam.web.worker import worker_lock


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--fixture-report", type=Path, required=True)
    parser.add_argument("--report-root", type=Path, required=True)
    parser.add_argument("--drive-serial", required=True)
    parser.add_argument("--medium-serial", required=True)
    parser.add_argument("--media-id", required=True)
    parser.add_argument("--tape-file", type=int, default=1)
    args = parser.parse_args()
    config = WebConfig.load(args.config)
    if config.role != "archive" or not config.physical_maintenance:
        raise SafetyError("Physical acceptance is not configured")
    fixture = json.loads(args.fixture_report.read_text())
    checksums = next(e["checksums"] for e in fixture["events"] if e["phase"] == "FIXTURES_READY")
    root = args.report_root.absolute()
    if (root.is_relative_to(config.staging) or config.staging.is_relative_to(root)
            or config.catalog.is_relative_to(root)):
        raise SafetyError("Report directory must be separate from staging/catalog")
    report = {"state": "RUNNING", "started": time.time(), "scope": "selected archive only; read-only tape",
              "moves": [], "data_reads": []}

    def save() -> None:
        temporary = root / "report.json.tmp"
        with temporary.open("w") as stream:
            json.dump(report, stream, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, root / "report.json")
        sync_dir(root)

    class ObservedTape(LinuxTape):
        def _move(self, operation, count=None):
            report["moves"].append({"time": time.time(), "operation": operation, "count": count})
            save()
            return super()._move(operation, count)

        @contextmanager
        def open_read(self, position):
            if position % 2:
                report["data_reads"].append(position)
                save()
            with super().open_read(position) as stream:
                yield stream

        def append(self, *unused, **kwargs):
            raise SafetyError("Acceptance forbids physical writes")

        def initialize(self, *unused, **kwargs):
            raise SafetyError("Acceptance forbids initialization")

    with worker_lock(config):
        control = Control(config.state)
        if control.shutdown_pending():
            raise SafetyError("Shutdown is pending")
        with control.connect() as db:
            if db.execute("SELECT 1 FROM commands WHERE state='RUNNING'").fetchone():
                raise SafetyError("A worker command is still running")
        drives = [d for d in discover_drives() if d.get("serial") == args.drive_serial
                  and d.get("medium_serial") == args.medium_serial and d.get("status", {}).get("online")]
        if len(drives) != 1:
            raise SafetyError("Exact drive/MAM pair is not uniquely present")
        root.mkdir(parents=True, mode=0o700, exist_ok=False)
        save()
        catalog = None
        try:
            original = sqlite3.connect(config.catalog.as_uri() + "?mode=ro", uri=True)
            copied = sqlite3.connect(root / "catalog.sqlite")
            try:
                original.backup(copied)
            finally:
                copied.close()
                original.close()
            catalog = Catalog(root / "catalog.sqlite")
            row = catalog.db.execute("SELECT * FROM archives WHERE media_id=? AND tape_file=? AND state='VERIFIED'",
                                     (args.media_id, args.tape_file)).fetchone()
            if row is None:
                raise SafetyError("Verified selected archive is missing")
            entries = json.loads(row["manifest_json"])["files"]
            if sum(e["size"] for e in entries) > 256 * 1024**2:
                raise SafetyError("This targeted acceptance is limited to 256 MiB")
            if any(checksums.get(e["path"]) != e["sha256"] for e in entries):
                raise SafetyError("Archive is not from the specified synthetic fixture report")
            target = config.staging / ("acceptance-targeted-" + root.name)
            if target.exists() or target.is_symlink():
                raise SafetyError("Restore target already exists")
            report.update(drive=drives[0], archive_id=row["id"], target=str(target))
            save()
            tape = ObservedTape(drives[0], config.state)
            result = ArchiveService(catalog, tape).restore(args.media_id, target, archive_id=row["id"])
            for entry in entries:
                if sha256(target / entry["path"]) != checksums[entry["path"]]:
                    raise SafetyError("Destination differs from original fixture SHA-256")
            if report["data_reads"] != [args.tape_file]:
                raise SafetyError("Restore read an unselected archive or repeated a data read")
            report.update(state="VERIFIED", result=result, finished=time.time())
            save()
        except BaseException as error:
            report.update(state="FAILED", error=str(error), finished=time.time())
            save()
            raise
        finally:
            if catalog is not None:
                catalog.close()


if __name__ == "__main__":
    main()
