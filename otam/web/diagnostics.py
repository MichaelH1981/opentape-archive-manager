"""Worker-owned diagnostics persistence and read-only dashboard status views."""

from __future__ import annotations
import json
import time
from typing import Any
from ..diagnostics import collect
from ..physical import discover_drives
from .control import Control


def save_sample(control: Control, observation: dict[str, Any]) -> None:
    ident = observation["drive_id"]
    sample = observation["page_sample"]
    with control.connect() as db:
        db.execute("BEGIN IMMEDIATE")

        def read(key, default):
            row = db.execute(
                "SELECT value FROM settings WHERE key=?", (key,)
            ).fetchone()
            return json.loads(row[0]) if row else default

        def write(key, value):
            db.execute(
                "INSERT INTO settings VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, json.dumps(value)),
            )

        latest = read("drive_diagnostics:" + ident, {})
        if latest.get("started") != observation["started"]:
            latest = {
                k: v
                for k, v in observation.items()
                if k not in ("page_sample", "pages")
            }
            latest["pages"] = {}
        latest["pages"][f"{sample['page']:02x}"] = sample
        latest["time"] = sample["time"]
        write("drive_diagnostics:" + ident, latest)
        # Parse raw TapeAlert records in the same transaction as raw persistence.
        # This also preserves flags if the process dies before the second sink call.
        if sample["page"] == 0x2E and sample.get("raw_hex"):
            from ..diagnostics import decode
            from ..common import SafetyError

            try:
                active = decode(bytes.fromhex(sample["raw_hex"]), 0x2E)["active_flags"]
            except (SafetyError, ValueError):
                active = []
            latch = read("drive_alerts:" + ident, {})
            for code in active:
                previous = latch.get(str(code), {})
                latch[str(code)] = {
                    "code": code,
                    "first_seen": previous.get("first_seen", sample["time"]),
                    "last_seen": sample["time"],
                    "medium_serial": observation.get("medium_serial"),
                }
            write("drive_alerts:" + ident, latch)


def scan(control: Control, *, force: bool = False) -> dict[str, Any]:
    # Called only by the single worker between jobs, not from HTTP requests.
    drives = discover_drives()
    now = time.time()
    inventory = {"time": now, "drives": drives}
    control.set("hardware_inventory", inventory)
    known = control.get("hardware_last_seen", {})
    for drive in drives:
        known[drive["id"]] = {**drive, "last_seen": now}
        if drive.get("busy"):
            continue
        previous = control.get("drive_diagnostics:" + drive["id"], {})
        if (
            force
            or not previous
            or now - previous.get("started", 0) >= 60
            or previous.get("medium_serial") != drive.get("medium_serial")
        ):
            try:
                collect(drive, lambda value: save_sample(control, value))
            except Exception as error:
                # Raw samples already captured remain intact; never report a clean read.
                control.set(
                    "diagnostics_error:" + drive["id"],
                    {"time": time.time(), "error": str(error)},
                )
            else:
                control.set("diagnostics_error:" + drive["id"], None)
    control.set("hardware_last_seen", known)
    return inventory


def detail(control: Control, ident: str) -> dict[str, Any]:
    return {
        "sample": control.get("drive_diagnostics:" + ident),
        "warning_history": sorted(
            control.get("drive_alerts:" + ident, {}).values(),
            key=lambda value: value["last_seen"],
            reverse=True,
        ),
        "error": control.get("diagnostics_error:" + ident),
    }


def overview(control: Control) -> dict[str, Any]:
    now = time.time()
    inventory = control.get("hardware_inventory", {"time": 0, "drives": []})
    heartbeat = control.get("worker_heartbeat", 0)
    fresh = 0 <= now - inventory.get("time", 0) <= 30 and 0 <= now - heartbeat <= 20
    with control.connect() as db:
        active = db.execute(
            "SELECT id,kind,payload FROM commands WHERE state='RUNNING' ORDER BY created LIMIT 1"
        ).fetchone()
    present = {d["id"]: d for d in inventory["drives"]}
    known = control.get("hardware_last_seen", {})
    active_maintenance = None
    if active and active["kind"] in ("tape-maintenance", "initialize-physical", "reset-physical", "reinitialize-physical"):
        payload = json.loads(active["payload"])
        progress = control.get(
            "maintenance_progress:" + payload.get("approval_id", ""), {}
        )
        if progress.get("state") == "RUNNING":
            active_maintenance = {
                key: progress.get(key)
                for key in (
                    "phase",
                    "time",
                    "bytes",
                    "bytes_per_second",
                    "total_bytes",
                    "written_bytes",
                    "operation",
                )
            }
            active_maintenance.update(
                fresh=0 <= now - heartbeat <= 20
                and 0 <= now - progress.get("time", 0) <= 15,
                command_id=active["id"],
                drive_id=progress.get("drive", {}).get("id"),
            )
    all_known = {**known, **present}
    drives = []
    for ident in sorted(set(present) | set(known)):
        drive = dict(present.get(ident) or known[ident])
        # Resolve earlier anonymous observations without fabricating a second drive.
        # Raw diagnostics and warning history remain stored under the original ID.
        if (
            not drive.get("serial")
            and drive.get("sysfs")
            and not control.get("drive_alerts:" + ident, {})
            and any(
                value.get("serial")
                and value.get("sysfs") == drive["sysfs"]
                and known.get(other, {}).get("last_seen", inventory.get("time", 0))
                >= known.get(ident, {}).get("last_seen", 0)
                for other, value in all_known.items()
                if other != ident
            )
        ):
            continue
        drive["active_maintenance"] = (
            active_maintenance
            if active_maintenance and active_maintenance["drive_id"] == ident
            else None
        )
        drive["observed_present"] = ident in present
        drive["contact_state"] = (
            "CURRENT"
            if ident in present and fresh
            else "STALE" if ident in present else "OFFLINE"
        )
        drive["last_seen"] = known.get(ident, {}).get(
            "last_seen", inventory.get("time")
        )
        drive["diagnostics"] = detail(control, ident)
        sample = drive["diagnostics"]["sample"]
        drive["diagnostics"]["stale"] = (
            not sample
            or not fresh
            or drive["contact_state"] != "CURRENT"
            or now - sample.get("started", 0) > 120
            or sample.get("medium_serial") != drive.get("medium_serial")
        )
        alert = sample.get("pages", {}).get("2e", {}) if sample else {}
        drive["diagnostics"]["current_alerts"] = (
            alert.get("decoded", {}).get("active_flags")
            if not drive["diagnostics"]["stale"] and alert.get("state") == "AVAILABLE" else None)
        drives.append(drive)
    return {
        "time": now,
        "last_scan": inventory["time"],
        "worker_online": 0 <= now - heartbeat <= 20,
        "fresh": fresh,
        "busy": active["kind"] if active else None,
        "active_maintenance": active_maintenance,
        "drives": drives,
    }
