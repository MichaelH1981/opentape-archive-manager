#!/usr/bin/env python3
"""Explicitly destructive TEST-MEDIUM layout acceptance, separate from software tests.

Requires an idle/stopped OTAM worker, its state directory, and the same TMPDIR.
Never enables the production tape backend. No external source data is accepted.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import time
import uuid
from pathlib import Path
from typing import Any

from otam.archive import (
    create_archive,
    inventory,
    metadata_tar,
    plan_archives,
    read_metadata,
    verify_archive,
)
from otam.common import FORMAT, SafetyError, sha256, sync_dir
from otam.physical import BLOCK_SIZE, LinuxMaintenance, discover_drives, run, status
from otam.storage import io_lock, require_local


def fixtures(root: Path, payload_mib: int = 16) -> list[Path]:
    """Create only new synthetic files and locally validate all PAX archives."""
    if not 1 <= payload_mib <= 1024:
        raise SafetyError("Invalid synthetic fixture size")
    root.mkdir(mode=0o700, exist_ok=False)
    media = str(uuid.uuid4())
    header = root / "00000000.tar"
    metadata_tar(
        header,
        "media.json",
        {
            "format": FORMAT,
            "media_id": media,
            "label": "DESTRUCTIVE HARDWARE ACCEPTANCE ONLY",
            "class": "rotation",
            "capacity": 800_000_000_000,
            "created": time.time(),
            "backend": "hardware-test",
        },
        recovery=True,
    )
    archives = [header]
    previous = sha256(header)
    for index in range(2):
        source = root / f"synthetic-source-{index}"
        source.mkdir(mode=0o700)
        (source / "README.txt").write_text(
            "Synthetic OTAM hardware acceptance fixture.\n"
        )
        with (source / "payload.bin").open("xb") as stream:
            for block in range(payload_mib + index):
                stream.write(
                    hashlib.shake_256(f"otam-layout-{index}-{block}".encode()).digest(
                        1024**2
                    )
                )
            stream.flush()
            os.fsync(stream.fileno())
        manifest = plan_archives(inventory(source), media, 64 * 1024**2)[0]
        position = len(archives)
        data = root / f"{position:08d}.tar"
        create_archive(data, source, manifest)
        verify_archive(data, manifest)
        receipt = root / f"{position + 1:08d}.tar"
        metadata_tar(
            receipt,
            "receipt.json",
            {
                "format": FORMAT,
                "media_id": media,
                "archive_id": manifest["archive_id"],
                "tape_file": position,
                "bytes": data.stat().st_size,
                "sha256": sha256(data),
                "previous": previous,
                "verified_at": None,
                "test_fixture": True,
            },
        )
        previous = sha256(receipt)
        archives.extend([data, receipt])
    for path in archives:
        path.chmod(0o400)
    return archives


class Acceptance:
    def __init__(self, device: LinuxMaintenance, root: Path):
        self.device = device
        self.root = root
        self.report: dict[str, Any] = {
            "job_id": str(uuid.uuid4()),
            "state": "RUNNING",
            "started": time.time(),
            "drive": device.expected,
            "events": [],
            "scope": "small PAX/filemark/position/append test, NOT full-media qualification",
        }

    def record(self, phase: str, **values: Any) -> None:
        self.report["events"].append({"time": time.time(), "phase": phase, **values})
        tmp = self.root / "report.json.tmp"
        with tmp.open("w") as stream:
            json.dump(self.report, stream, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, self.root / "report.json")
        sync_dir(self.root)
        print(
            json.dumps({"job_id": self.report["job_id"], "phase": phase, **values}),
            flush=True,
        )

    def position(self, expected: int, *, at_start: bool = True) -> dict[str, Any]:
        value = status(self.device.device)
        self.record("POSITION", expected_file=expected, actual=value)
        if value["file_number"] != expected or (
            at_start and value["block_number"] != 0
        ):
            raise SafetyError("Unconfirmed tape position; no blind continuation")
        return value

    def move(self, operation: str, count: int | None = None) -> None:
        if operation not in ("rewind", "fsf", "eod") or (
            count is not None and not 0 <= count <= 5
        ):
            raise SafetyError("Invalid acceptance-test movement")
        args = ["mt", "-f", self.device.device, operation]
        if count is not None:
            args.append(str(count))
        self.record("MOVE_START", operation=operation, count=count)
        run(args, timeout=900)
        self.record("MOVE_COMPLETE", operation=operation, count=count)

    def seek(self, position: int) -> None:
        self.device.check()
        self.move("rewind")
        if position:
            self.move("fsf", position)
        self.position(position)

    def write(self, source: Path, position: int) -> None:
        self.device.check()
        self.position(position)
        checksum = sha256(source)
        self.record(
            "WRITE_START",
            tape_file=position,
            sha256=checksum,
            bytes=source.stat().st_size,
        )
        fd = self.device.writer()
        try:
            with source.open("rb") as stream:
                while block := stream.read(BLOCK_SIZE):
                    if self.device.write(fd, block) != len(block):
                        raise SafetyError("Short write; incomplete test medium")
        finally:
            self.device.close(fd)
        self.record("WRITE_CLOSED", tape_file=position)
        self.position(position + 1)

    def read(self, source: Path, position: int, label: str) -> Path:
        self.seek(position)
        dest = self.root / f"readback-{label}-{position}.tar"
        fd = self.device.reader()
        count = 0
        checksum = hashlib.sha256()
        try:
            with dest.open("xb") as stream:
                while block := self.device.read(fd):
                    count += len(block)
                    if count > source.stat().st_size:
                        raise SafetyError("Unexpected extra data before filemark")
                    stream.write(block)
                    checksum.update(block)
                stream.flush()
                os.fsync(stream.fileno())
        finally:
            self.device.close(fd)
        if count != source.stat().st_size or checksum.hexdigest() != sha256(source):
            raise SafetyError("Tape file readback mismatch")
        self.record(
            "READBACK_VERIFIED",
            tape_file=position,
            bytes=count,
            sha256=checksum.hexdigest(),
            after_close=status(self.device.device),
        )
        # Independent open-format reader, without extraction of untrusted metadata.
        run(["tar", "-tf", str(dest)], timeout=30)
        return dest

    def finalize_receipt(self, archives: list[Path], position: int) -> None:
        value = read_metadata(archives[position], "receipt.json")
        value.update(verified_at=time.time(), previous=sha256(archives[position - 2]))
        tmp = archives[position].with_suffix(".partial")
        metadata_tar(tmp, "receipt.json", value)
        with tmp.open("rb") as stream:
            os.fsync(stream.fileno())
        tmp.chmod(0o400)
        os.replace(tmp, archives[position])
        sync_dir(tmp.parent)
        self.record("RECEIPT_READY_AFTER_READBACK", tape_file=position)

    def execute(self, archives: list[Path]) -> None:
        self.record(
            "AUTHORIZED", confirmation="exact drive and cartridge serials matched"
        )
        try:
            self.device.mt("rewind")
            self.device.mt("setblk", "0")
            self.device.mt("compression", "0")
            self.device.check()
            self.position(0)
            for position in range(3):
                if position == 2:
                    self.finalize_receipt(archives, position)
                self.seek(position)
                self.write(archives[position], position)
                self.read(archives[position], position, "initial")
            # Re-open and reconstruct the entire existing prefix before append.
            for position in range(3):
                self.read(archives[position], position, "pre-append")
            self.device.check()
            self.move("rewind")
            self.move("eod")
            self.position(3)
            self.write(archives[3], 3)
            self.read(archives[3], 3, "new-data")
            self.finalize_receipt(archives, 4)
            self.seek(4)
            self.write(archives[4], 4)
            for position in (4, 0, 3, 1, 2):
                self.read(archives[position], position, "final")
            self.report["state"] = "LAYOUT_READBACK_VERIFIED"
            self.record("COMPLETE", ended=time.time(), tape_files=5)
        except BaseException as error:
            self.report["state"] = "FAILED_INCOMPLETE"
            self.record("FAILED", error=str(error), ended=time.time())
            raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--drive-serial", required=True)
    parser.add_argument("--medium-serial", required=True)
    parser.add_argument(
        "--confirm", required=True, help="Exact: TESTEN <drive serial> <medium serial>"
    )
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument(
        "--output", type=Path, required=True, help="New private test directory"
    )
    args = parser.parse_args()
    if args.confirm != f"TESTEN {args.drive_serial} {args.medium_serial}":
        raise SafetyError("Explicit destructive confirmation does not match")
    if (
        os.geteuid() == 0
        or not args.state.is_absolute()
        or not args.output.is_absolute()
    ):
        raise SafetyError(
            "Use the unprivileged worker user and absolute state/output paths"
        )
    # Same worker exclusivity and heavy-I/O locks; never compete with its scanner.
    storage = require_local(args.output.parent)
    if storage["free"] < 512 * 1024**2:
        raise SafetyError(
            "At least 512 MiB local space required for synthetic fixtures and readbacks"
        )
    fd = os.open(args.state / "worker.lock", os.O_RDWR | os.O_NOFOLLOW)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with io_lock():
            drives = [
                d
                for d in discover_drives()
                if d["serial"] == args.drive_serial
                and d["medium_serial"] == args.medium_serial
                and d["ready"]
            ]
            if len(drives) != 1:
                raise SafetyError(
                    "No unique writable drive/cartridge matching authorization"
                )
            device = LinuxMaintenance(drives[0], args.state / "drive-locks")
            args.output.mkdir(mode=0o700, exist_ok=False)
            with device.locked():
                acceptance = Acceptance(device, args.output)
                acceptance.record("STAGING")
                try:
                    archives = fixtures(args.output / "staged")
                except BaseException as error:
                    acceptance.report["state"] = "FAILED_BEFORE_WRITE"
                    acceptance.record("FAILED", error=str(error))
                    raise
                acceptance.execute(archives)
    finally:
        os.close(fd)


if __name__ == "__main__":
    main()
