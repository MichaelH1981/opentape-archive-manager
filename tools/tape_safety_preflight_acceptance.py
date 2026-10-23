#!/usr/bin/env python3
"""Non-writing identity, exclusion and durable pending-marker acceptance.

This deliberately does NOT claim a physical interrupted-write test. It performs
no tape data reads, no movements and no writes, apart from setting block mode.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from otam.common import SafetyError, sync_dir
from otam.physical import LinuxMaintenance, discover_drives, verify_identity
from otam.storage import io_lock
from otam.tape import LinuxTape
from otam.web.config import WebConfig
from otam.web.control import Control
from otam.web.worker import worker_lock


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--drive-serial", required=True)
    parser.add_argument("--medium-serial", required=True)
    parser.add_argument("--report-root", required=True, type=Path)
    args = parser.parse_args()
    config = WebConfig.load(args.config)
    if config.role != "archive" or not config.physical_maintenance:
        raise SafetyError("Physical maintenance is not configured")
    root = args.report_root.absolute()
    if (root.is_relative_to(config.state) or config.state.is_relative_to(root)
            or root.is_relative_to(config.staging) or config.catalog.is_relative_to(root)):
        raise SafetyError("Acceptance state must be isolated from production state/staging")
    report = {"state": "RUNNING", "started": time.time(), "checks": [],
              "scope": "no data IO or tape motion; injected marker, not interrupted physical write"}

    def save() -> None:
        with (root / "report.json.tmp").open("w") as stream:
            json.dump(report, stream, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(root / "report.json.tmp", root / "report.json")
        sync_dir(root)

    def refused(name, action, message):
        try:
            action()
        except SafetyError as error:
            if message not in str(error):
                raise
            report["checks"].append({"check": name, "state": "REFUSED", "reason": str(error)})
            save()
        else:
            raise SafetyError("A required safety gate did not refuse: " + name)

    with worker_lock(config), io_lock():
        control = Control(config.state)
        if control.shutdown_pending():
            raise SafetyError("Shutdown is pending")
        with control.connect() as db:
            if db.execute("SELECT 1 FROM commands WHERE state='RUNNING'").fetchone():
                raise SafetyError("Another command is still running")
        drives = [d for d in discover_drives() if d.get("serial") == args.drive_serial
                  and d.get("medium_serial") == args.medium_serial]
        if len(drives) != 1:
            raise SafetyError("Exact drive/MAM pair is not present")
        drive = drives[0]
        root.mkdir(parents=True, mode=0o700, exist_ok=False)
        report["drive"] = drive
        save()
        try:
            for key in ("serial", "medium_serial", "device"):
                refused("mismatched_" + key,
                        lambda key=key: verify_identity({**drive, key: "OTAM-INTENTIONALLY-WRONG"}, writable=False),
                        "Freigabe")
            locks = config.state / "drive-locks"
            one, two = LinuxMaintenance(drive, locks, writable=False), LinuxMaintenance(drive, locks, writable=False)
            with one.locked():
                def parallel():
                    with two.locked():
                        pass
                refused("exclusive_drive_lock", parallel, "bereits")
            isolated = root / "isolated-state"
            isolated.mkdir(mode=0o700)
            tape = LinuxTape(drive, isolated)
            # A separate process fsyncs its own marker and exits without cleanup.
            seed = ('import os,sys; from pathlib import Path; '
                    'p=Path(sys.argv[1]); p.parent.mkdir(); '
                    'f=p.open("x"); f.write("injected acceptance marker"); f.flush(); '
                    'os.fsync(f.fileno()); f.close(); '
                    'd=os.open(p.parent,os.O_RDONLY|os.O_DIRECTORY); os.fsync(d); os.close(d); os._exit(79)')
            ended = subprocess.run([sys.executable, "-I", "-c", seed, str(tape._pending)], check=False)
            if ended.returncode != 79 or not tape._pending.is_file():
                raise SafetyError("Durable injected marker was not preserved")
            # New adapter instance represents a fresh process/backend state.
            restarted = LinuxTape(drive, isolated)
            restarted.device.lock_root = locks
            def forbidden(*args, **kwargs):
                raise AssertionError("Pending refusal must not read, move or open a writer")
            restarted._move = forbidden
            restarted.header = forbidden
            restarted.device.writer = forbidden
            with restarted.locked():
                refused("durable_pending_refuses_before_motion",
                        lambda: restarted.append(root / "absent.tar", "not-used"), "uncertain")
            report.update(state="VERIFIED", finished=time.time(),
                          limitation="Injected pending-marker test only; physical write interruption remains untested")
            save()
        except BaseException as error:
            report.update(state="FAILED", finished=time.time(), error=str(error))
            save()
            raise


if __name__ == "__main__":
    main()
