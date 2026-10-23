#!/usr/bin/env python3
"""Read-only recheck of a completed qualification job; no tape writes.

Runs separately with the OTAM worker paused, its user, state and TMPDIR.
A verified prefix is not a full archive/media verification or capacity test.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import resource
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from otam.common import SafetyError, sync_dir
from otam.diagnostics import kernel_stats
from otam.physical import (
    BLOCK_SIZE,
    LinuxMaintenance,
    pattern,
    prefetched_records,
    status,
    test_block,
)
from otam.storage import io_lock, require_local

MAX_BYTES = 32 * 1024**3
MAX_CHECK_BYTES = 20_000_000_000_000


def verify_prefix(
    device: Any,
    fd: int,
    seed: str,
    max_bytes: int,
    progress: Callable[..., None],
    *,
    read_seconds_limit: float | None = None,
) -> dict[str, Any]:
    if (
        not re.fullmatch("[0-9a-f]{64}", seed)
        or not 0 < max_bytes <= MAX_CHECK_BYTES
        or max_bytes % BLOCK_SIZE
        or (read_seconds_limit is not None and not 0 < read_seconds_limit <= 7200)
    ):
        raise SafetyError("Invalid qualification prefix")
    data = pattern(seed)
    count = 0
    checksum = hashlib.sha256()
    before = resource.getrusage(resource.RUSAGE_SELF)
    started = last = time.monotonic()
    with prefetched_records(device, fd, max_records=max_bytes // BLOCK_SIZE) as records:
        for block in records:
            if block != test_block(count, seed, data):
                raise SafetyError(
                    "Qualification prefix differs from the original reconstructible records"
                )
            checksum.update(block)
            count += 1
            now = time.monotonic()
            if read_seconds_limit is not None and now - started >= read_seconds_limit:
                progress(
                    phase="TIME_LIMIT", bytes=count * BLOCK_SIZE, total_bytes=max_bytes
                )
                raise SafetyError(
                    "Read-only comparison reached its time budget; no complete verification"
                )
            if now - last >= 2:
                progress(
                    phase="TAPE_READBACK",
                    bytes=count * BLOCK_SIZE,
                    total_bytes=max_bytes,
                    bytes_per_second=count * BLOCK_SIZE / (now - started),
                )
                last = now
    elapsed = time.monotonic() - started
    if count * BLOCK_SIZE != max_bytes:
        raise SafetyError("Unexpected filemark before requested prefix end")
    after = resource.getrusage(resource.RUSAGE_SELF)
    return {
        "state": "PREFIX_VERIFIED",
        "scope": "prefix_only_not_full_medium",
        "bytes": max_bytes,
        "sha256": checksum.hexdigest(),
        "read_seconds": elapsed,
        "bytes_per_second": max_bytes / max(elapsed, 0.001),
        "worker_cpu_one_core_percent": 100
        * ((after.ru_utime + after.ru_stime) - (before.ru_utime + before.ru_stime))
        / max(elapsed, 0.001),
        "max_records_in_memory": 2,
    }


def confirm_complete_stream(
    device: Any, fd: int, checked: dict[str, Any], source: dict[str, Any]
) -> dict[str, Any]:
    if checked["bytes"] != source["bytes"] or checked["sha256"] != source["sha256"]:
        raise SafetyError("Complete original stream checksum or size mismatch")
    started = time.monotonic()
    if device.read(fd):
        raise SafetyError("Unexpected extra record instead of the original filemark")
    elapsed = checked["read_seconds"] + time.monotonic() - started
    return {
        **checked,
        "state": "READBACK_VERIFIED",
        "scope": "complete_original_test_stream_not_full_medium_qualification",
        "read_seconds": elapsed,
        "bytes_per_second": checked["bytes"] / max(elapsed, 0.001),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-job", required=True)
    parser.add_argument("--drive-serial", required=True)
    parser.add_argument("--medium-serial", required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--full-stream",
        action="store_true",
        help="Read and hash the complete original qualification stream, including its filemark",
    )
    parser.add_argument(
        "--read-seconds-limit",
        type=int,
        default=2700,
        help="Stop at a record boundary after this read-time budget (default 45 minutes)",
    )
    args = parser.parse_args()
    uuid.UUID(args.source_job)
    if (
        os.geteuid() == 0
        or not args.state.is_absolute()
        or not args.output.is_absolute()
    ):
        raise SafetyError("Use the unprivileged worker user and absolute paths")
    require_local(args.output.parent)
    lock = os.open(args.state / "worker.lock", os.O_RDWR | os.O_NOFOLLOW)
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with (
            io_lock(),
            sqlite3.connect(
                (args.state / "control.sqlite").as_uri() + "?mode=ro", uri=True
            ) as db,
        ):
            row = db.execute(
                "SELECT kind,state,payload,result FROM commands WHERE id=?",
                (args.source_job,),
            ).fetchone()
            if not row or row[0] != "tape-maintenance" or row[1] != "SUCCEEDED":
                raise SafetyError("A completed successful qualification is required")
            payload, result = json.loads(row[2]), json.loads(row[3])
            if (
                result.get("state") not in ("SAMPLE_VERIFIED", "VERIFIED")
                or type(result.get("bytes")) is not int
                or not 0 < result["bytes"] <= MAX_CHECK_BYTES
                or result["bytes"] % BLOCK_SIZE
                or (not args.full_stream and result["bytes"] < MAX_BYTES)
            ):
                raise SafetyError("Qualification does not cover the requested prefix")
            limit = result["bytes"] if args.full_stream else MAX_BYTES
            row = db.execute(
                "SELECT value FROM settings WHERE key=?",
                ("maintenance_approval:" + payload["approval_id"],),
            ).fetchone()
            grant = json.loads(row[0]) if row else {}
            expected = grant.get("drive", {})
            if (
                expected.get("serial") != args.drive_serial
                or expected.get("medium_serial") != args.medium_serial
                or grant.get("seed") != result.get("seed")
            ):
                raise SafetyError(
                    "Source job and requested drive/cartridge identity differ"
                )
            device = LinuxMaintenance(expected, args.state / "drive-locks")
            args.output.mkdir(mode=0o700, exist_ok=False)
            report = {
                "job_id": str(uuid.uuid4()),
                "source_job": args.source_job,
                "state": "RUNNING",
                "started": time.time(),
                "drive": expected,
                "source_sha256": result["sha256"],
                "events": [],
            }

            def progress(**values):
                report["events"].append({"time": time.time(), **values})
                tmp = args.output / "report.json.tmp"
                with tmp.open("w") as out:
                    json.dump(report, out, indent=2)
                    out.flush()
                    os.fsync(out.fileno())
                os.replace(tmp, args.output / "report.json")
                sync_dir(args.output)
                print(json.dumps(values), flush=True)

            try:
                with device.locked():
                    progress(phase="READBACK_POSITIONING", bytes=0)
                    device.mt("rewind")
                    device.check()
                    if status(device.device)["block_size"] != 0:
                        raise SafetyError(
                            "Variable block mode is required; no automatic settings change"
                        )
                    report["kernel_before"] = kernel_stats(expected)
                    cpu_before = list(
                        map(
                            int,
                            Path("/proc/stat").read_text().splitlines()[0].split()[1:9],
                        )
                    )
                    fd = device.reader()
                    try:
                        checked = verify_prefix(
                            device,
                            fd,
                            result["seed"],
                            limit,
                            progress,
                            read_seconds_limit=args.read_seconds_limit,
                        )
                        if args.full_stream:
                            checked = confirm_complete_stream(
                                device, fd, checked, result
                            )
                    finally:
                        device.close(fd)
                    device.check()
                    cpu_after = list(
                        map(
                            int,
                            Path("/proc/stat").read_text().splitlines()[0].split()[1:9],
                        )
                    )
                    total = sum(cpu_after) - sum(cpu_before)
                    idle = cpu_after[3] + cpu_after[4] - cpu_before[3] - cpu_before[4]
                    checked["system_cpu_busy_percent"] = (
                        100 * (total - idle) / max(total, 1)
                    )
                    report["kernel_after"] = kernel_stats(expected)
                    report.update(
                        state=checked["state"], result=checked, ended=time.time()
                    )
                    progress(
                        phase=checked["state"],
                        **{k: v for k, v in checked.items() if k != "state"},
                    )
            except BaseException as error:
                report.update(
                    state="FAILED_INCOMPLETE", error=str(error), ended=time.time()
                )
                progress(phase="FAILED_INCOMPLETE", error=str(error))
                raise
    finally:
        os.close(lock)


if __name__ == "__main__":
    main()
