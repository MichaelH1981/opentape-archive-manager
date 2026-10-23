#!/usr/bin/env python3
"""Explicit header-only acceptance for a separately authorized NEW test cartridge.

Uses the live catalog/control, pending journal and device locks, but does not
change the installed node configuration. Stop the idle main worker beforehand;
the supervising systemd unit must restart it after success or failure. This
never qualifies a full medium, appends payloads, recycles known media or erases.
"""
from __future__ import annotations

import argparse
import json
import os
import time
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from otam.catalog import Catalog
from otam.common import SafetyError, sha256, sync_dir
from otam.physical import discover_drives
from otam.tape import LinuxTape
from otam.web import initialization
from otam.web.config import WebConfig
from otam.web.control import Control
from otam.web.worker import execute, worker_lock


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--report-root", required=True, type=Path)
    parser.add_argument("--drive-serial", required=True)
    parser.add_argument("--medium-serial", required=True)
    parser.add_argument("--label", default="OTAM SECONDARY TEST MEDIUM")
    parser.add_argument("--confirm", required=True, help="INITIALIZE <drive-serial> <MAM-serial>; destroys existing unknown contents")
    args = parser.parse_args()
    if args.confirm != f"INITIALIZE {args.drive_serial} {args.medium_serial}":
        raise SafetyError("Exact destructive drive/MAM confirmation is required")
    os.umask(0o077)
    live = WebConfig.load(args.config)
    if live.role != "archive" or not live.physical_maintenance:
        raise SafetyError("Archive hardware access is not configured")
    root = args.report_root.resolve()
    if (root.is_relative_to(live.state) or live.state.is_relative_to(root)
            or root.is_relative_to(live.staging) or live.staging.is_relative_to(root)
            or live.catalog.is_relative_to(root)):
        raise SafetyError("Report must be separate from the live catalog/state/staging")
    report = {"state": "RUNNING", "started": time.time(), "events": [], "moves": [], "header_reads": [],
              "scope": "destructive initialization and header readback only; no payload or full tape qualification",
              "initializer_sha256": sha256(Path(initialization.__file__))}

    def save() -> None:
        with (root / "report.json.tmp").open("w") as stream:
            json.dump(report, stream, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(root / "report.json.tmp", root / "report.json")
        sync_dir(root)

    class ObservedTape(LinuxTape):
        def _move(self, operation, count=None):
            report["moves"].append({"operation": operation, "count": count})
            save()
            return super()._move(operation, count)

        def initialize(self, *values, **options):
            if (self.device.expected["serial"] != args.drive_serial
                    or self.device.expected["medium_serial"] != args.medium_serial):
                raise SafetyError("Acceptance refuses any other drive/cartridge")
            result = super().initialize(*values, **options)
            report["header_sha256"] = sha256(self.read(0))
            save()
            return result

        @contextmanager
        def open_read(self, position):
            if position != 0:
                raise SafetyError("Header acceptance forbids data/receipt reads")
            report["header_reads"].append(position)
            save()
            with super().open_read(position) as stream:
                yield stream

        def append(self, *values, **options):
            raise SafetyError("Header acceptance forbids appending archives")

    with worker_lock(live):
        control = Control(live.state)
        if control.shutdown_pending():
            raise SafetyError("Shutdown is pending")
        with control.connect() as db:
            if db.execute("SELECT 1 FROM commands WHERE state IN ('RUNNING','QUEUED')").fetchone():
                raise SafetyError("The live queue must be idle")
        root.mkdir(parents=True, mode=0o700, exist_ok=False)
        save()
        catalog = Catalog(live.catalog)
        try:
            baseline = [tuple(row) for row in catalog.db.execute(
                "SELECT id,media_id,tape_file,state,sha256 FROM archives ORDER BY id")]
            drives = [d for d in discover_drives() if d.get("serial") == args.drive_serial
                      and d.get("medium_serial") == args.medium_serial]
            if len(drives) != 1:
                raise SafetyError("Exact authorized drive/MAM pair is not uniquely present")
            drive = drives[0]
            # Acceptance flags are in-memory only. Live catalog/control/locks
            # ensure that an uncertain write remains visible after this test.
            config = replace(live, physical_archiving=True, physical_initialization=True)
            config.validate()
            control.set("hardware_inventory", {"time": time.time(), "drives": [drive]})
            grant = initialization.prepare(config, control, {
                "drive_id": drive["id"], "drive_serial": args.drive_serial, "medium_serial": args.medium_serial,
                "label": args.label, "media_class": "rotation"})
            report["approval"] = grant
            save()
            with patch("otam.web.initialization.LinuxTape", ObservedTape):
                result = execute(config, control, "initialize-physical", {
                    "approval_id": grant["id"], "confirmation": args.confirm, "destructive_confirmed": True})
            if result["state"] != "INITIALIZED" or len(report["header_reads"]) != 1:
                raise SafetyError("Header-only initialization proof is incomplete")
            if baseline != [tuple(row) for row in catalog.db.execute(
                    "SELECT id,media_id,tape_file,state,sha256 FROM archives ORDER BY id")]:
                raise SafetyError("Existing archive catalog prefix changed")
            media = result["media_id"]
            if control.get("physical_media_bindings", {}).get(media, {}).get("medium_serial") != args.medium_serial:
                raise SafetyError("New medium binding was not published")
            report.update(state="VERIFIED", finished=time.time(), result=result, archive_prefix_unchanged=True)
            save()
        except BaseException as error:
            report.update(state="FAILED", finished=time.time(), error=str(error))
            save()
            raise
        finally:
            catalog.close()


if __name__ == "__main__":
    main()
