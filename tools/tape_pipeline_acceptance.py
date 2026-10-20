#!/usr/bin/env python3
"""Explicit test-cartridge acceptance of the regular ArchiveService/LinuxTape.

Run as the OTAM service account, with its TMPDIR, after stopping the idle worker.
Only generated fixtures are accepted. No production sources or erase commands.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

from otam.benchmark import require_qualification
from otam.catalog import Catalog
from otam.common import SafetyError, sha256, sync_dir
from otam.physical import discover_drives
from otam.service import ArchiveService
from otam.storage import io_lock, require_local
from otam.tape import LinuxTape
from otam.web.config import WebConfig
from otam.web.control import Control
from otam.web.worker import worker_lock


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--drive-serial", required=True)
    parser.add_argument("--medium-serial", required=True)
    parser.add_argument("--confirm", required=True,
                        help="TEST <drive-serial> <medium-serial>; includes BOT overwrite")
    parser.add_argument("--payload-mib", type=int, default=32)
    parser.add_argument("--verify-mode", choices=("archive", "media"), default="archive")
    parser.add_argument("--existing-media-id", help="Append to this existing OTAM test medium instead of initializing")
    parser.add_argument("--recover-report", type=Path,
                        help="Read-only recovery of fixtures from a previous acceptance report; never initializes or appends")
    parser.add_argument("--report-root", required=True, type=Path)
    args = parser.parse_args()
    if args.confirm != f"TEST {args.drive_serial} {args.medium_serial}":
        raise SafetyError("Exact drive and cartridge confirmation required")
    if not 1 <= args.payload_mib <= 71680:
        raise SafetyError("Synthetic file size must be 1 MiB to 70 GiB")
    config = WebConfig.load(args.config)
    if config.role != "archive" or not config.physical_maintenance:
        raise SafetyError("Physical access is not configured on this archive node")
    control = Control(config.state)
    if control.shutdown_pending():
        raise SafetyError("Shutdown is pending")
    with worker_lock(config):
        with control.connect() as db:
            if db.execute("SELECT 1 FROM commands WHERE state='RUNNING'").fetchone():
                raise SafetyError("A queued worker operation is still running")
        return execute(config, args)


def execute(config: WebConfig, args: argparse.Namespace) -> int:
    drives = [drive for drive in discover_drives()
              if drive.get("serial") == args.drive_serial
              and drive.get("medium_serial") == args.medium_serial
              and (drive.get("ready") or (args.recover_report and drive.get("status", {}).get("online")))]
    if len(drives) != 1:
        raise SafetyError("The explicitly authorized drive/cartridge pair is not uniquely present")
    drive = drives[0]
    if (drive.get("vendor") != "IBM" or drive.get("model") != "ULT3580-HH4"
            or drive.get("status", {}).get("density_code") != 0x46):
        raise SafetyError("This hardware acceptance covers IBM HH4 with LTO-4 only")
    if args.recover_report:
        return recover_only(config, args, drive)
    catalog = Catalog(config.catalog)
    try:
        require_qualification(catalog, config.staging)
        root = args.report_root.resolve()
        if (root.is_relative_to(config.staging.resolve())
                or config.staging.resolve().is_relative_to(root)
                or config.catalog.resolve().is_relative_to(root)):
            raise SafetyError("Fixture/report root must be separate from staging and catalog")
        root.mkdir(mode=0o700, parents=True, exist_ok=False)
        report = {"id": str(uuid.uuid4()), "state": "RUNNING", "started": time.time(),
                  "drive": drive, "events": [], "verification": args.verify_mode,
                  "scope": "regular OTAM physical archive/readback/restore; synthetic data only"}

        def record(phase: str, **values) -> None:
            report["events"].append({"time": time.time(), "phase": phase, **values})
            temporary = root / "report.json.tmp"
            with temporary.open("w") as stream:
                json.dump(report, stream, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, root / "report.json")
            sync_dir(root)
            print(json.dumps({"phase": phase, **values}), flush=True)

        tape = LinuxTape(drive, config.state, buffer_mib=2368)
        service = ArchiveService(catalog, tape)
        try:
            source = root / "synthetic-source"
            source.mkdir(mode=0o700)
            with io_lock():
                storage = require_local(source)
                if storage["free"] < 2 * args.payload_mib * 1024**2 + 1024**3:
                    raise SafetyError("Insufficient local fixture space")
                record("FIXTURES_START", payload_mib_per_file=args.payload_mib)
                for number in (1, 2):
                    block = hashlib.shake_256(f"otam-physical-{number}".encode()).digest(1024**2)
                    with (source / f"{report['id']}-payload-{number}.bin").open("xb") as stream:
                        for _ in range(args.payload_mib):
                            stream.write(block)
                        stream.flush()
                        os.fsync(stream.fileno())
                (source / (report["id"] + "-README.txt")).write_text("OTAM synthetic physical pipeline acceptance.\n")
                checksums = {path.name: sha256(path) for path in source.iterdir()}
                record("FIXTURES_READY", checksums=checksums)
            if args.existing_media_id:
                with io_lock(), tape.locked():
                    header = tape.header()
                    if header["media_id"] != args.existing_media_id or header["class"] != "rotation":
                        raise SafetyError("Existing test medium identity/class mismatch")
            else:
                with io_lock(), tape.locked():
                    record("INITIALIZE_START")
                    header = tape.initialize("OTAM SYNTHETIC ACCEPTANCE", 800_000_000_000,
                                             "rotation", f"INITIALIZE {args.medium_serial}")
            record("HEADER_VERIFIED", media_id=header["media_id"])
            service.register()
            plan = service.plan(source, header["media_id"],
                                max(150_000, args.payload_mib * 1024**2 + 100000),
                                verify_mode=args.verify_mode)
            record("PLAN_READY", job_id=plan["job_id"], archives=len(plan["archives"]),
                   payload_bytes=plan["payload_bytes"], sha256=plan["sha256"])
            staged = service.stage(plan["job_id"], config.staging)
            record("STAGED", result=staged)
            result = service.backup(plan["job_id"], plan["job_id"], config.staging)
            record("ARCHIVE_VERIFIED", result=result)
            # Fresh object and empty DB: no original catalog is used for recovery.
            recovery = Catalog(root / "reconstructed.sqlite")
            try:
                fresh = ArchiveService(recovery, LinuxTape(drive, config.state, buffer_mib=2368))
                record("REBUILD_START")
                rebuilt = fresh.rebuild(header["media_id"])
                record("REBUILT", result=rebuilt)
                target = config.staging / ("acceptance-restore-" + report["id"])
                restored = fresh.restore(header["media_id"], target,
                                         archive_id=None, paths=list(checksums))
                for name, checksum in checksums.items():
                    if sha256(target / name) != checksum:
                        raise SafetyError("Restored fixture checksum mismatch")
                record("RESTORE_VERIFIED", result=restored, checksums=checksums)
            finally:
                recovery.close()
            report.update(state="VERIFIED", finished=time.time(), media_id=header["media_id"])
            record("COMPLETE")
            return 0
        except BaseException as error:
            report.update(state="FAILED", error=str(error), finished=time.time())
            record("FAILED", error=str(error))
            raise
    finally:
        catalog.close()


def recover_only(config: WebConfig, args: argparse.Namespace, drive: dict) -> int:
    """Keep the failed historical report intact and recover its existing medium."""
    previous = json.loads(args.recover_report.read_text())
    if any(previous["drive"][key] != drive[key] for key in ("serial", "medium_serial")):
        raise SafetyError("Recovery report belongs to a different drive/cartridge")
    media = next(event["media_id"] for event in previous["events"] if event["phase"] == "HEADER_VERIFIED")
    checksums = next(event["checksums"] for event in previous["events"] if event["phase"] == "FIXTURES_READY")
    root = args.report_root.resolve()
    if (root.is_relative_to(config.staging.resolve())
            or config.staging.resolve().is_relative_to(root)
            or config.catalog.resolve().is_relative_to(root)):
        raise SafetyError("Recovery report root must be separate from staging and catalog")
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    report = {"state": "RUNNING", "started": time.time(), "drive": drive,
              "media_id": media, "previous_report": str(args.recover_report), "events": [],
              "scope": "READ ONLY tape access: catalog reconstruction, restore and independent recovery"}

    def record(phase: str, **values):
        report["events"].append({"time": time.time(), "phase": phase, **values})
        temporary = root / "report.json.tmp"
        with temporary.open("w") as stream:
            json.dump(report, stream, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, root / "report.json")
        sync_dir(root)
        print(json.dumps({"phase": phase, **values}), flush=True)

    catalog = Catalog(root / "reconstructed.sqlite")
    try:
        tape = LinuxTape(drive, config.state)
        service = ArchiveService(catalog, tape)
        record("REBUILD_START")
        record("REBUILT", result=service.rebuild(media))
        target = config.staging / ("acceptance-recovery-" + str(uuid.uuid4()))
        restored = service.restore(media, target, paths=list(checksums))
        for name, checksum in checksums.items():
            if sha256(target / name) != checksum:
                raise SafetyError("Recovery destination checksum mismatch")
        record("RESTORE_VERIFIED", result=restored, checksums=checksums)
        # Isolated Python invocation: the recovery utility imports no OTAM code
        # and receives only standard TAR files physically read from this medium.
        for archive in catalog.db.execute("SELECT * FROM archives WHERE media_id=?", (media,)).fetchall():
            if archive["bytes"] > 256 * 1024**2:
                record("INDEPENDENT_EXPORT_SKIPPED", archive_id=archive["id"], reason="small-test limit")
                continue
            data = root / (archive["id"] + ".tar")
            receipt = root / (archive["id"] + "-receipt.tar")
            with io_lock(), tape.locked():
                with tape.open_read(archive["tape_file"]) as incoming, data.open("xb") as output:
                    count = 0
                    while chunk := incoming.read(1024**2):
                        count += len(chunk)
                        if count > archive["bytes"]:
                            raise SafetyError("Independent export exceeds verified archive size")
                        output.write(chunk)
                    output.flush()
                    os.fsync(output.fileno())
                if count != archive["bytes"] or sha256(data) != archive["sha256"]:
                    raise SafetyError("Independent export archive checksum mismatch")
                shutil.copyfile(tape.read(archive["tape_file"] + 1), receipt)
            result = subprocess.run([sys.executable, "-I", str(Path(__file__).with_name("recover_tar.py")),
                                     str(data), str(receipt), str(root / ("independent-" + archive["id"]))],
                                    capture_output=True, text=True, check=True)
            record("INDEPENDENT_RECOVERY_VERIFIED", archive_id=archive["id"],
                   sha256=archive["sha256"], result=json.loads(result.stdout))
        report.update(state="VERIFIED", finished=time.time())
        record("COMPLETE")
        return 0
    except BaseException as error:
        report.update(state="FAILED", error=str(error), finished=time.time())
        record("FAILED", error=str(error))
        raise
    finally:
        catalog.close()


if __name__ == "__main__":
    raise SystemExit(main())
