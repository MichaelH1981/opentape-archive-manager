"""One-use, expiring approvals bound to physical drive and MAM cartridge serial."""

from __future__ import annotations
import json
import secrets
import time
import uuid
from typing import Any
from ..common import SafetyError
from ..physical import LinuxMaintenance, qualify, erase
from ..storage import io_lock
from .config import WebConfig
from .control import Control


def mode(config: WebConfig, control: Control) -> str:
    return control.get("operation_mode", "simulator")


def set_mode(config: WebConfig, control: Control, value: str) -> None:
    if config.role != "archive" or value not in ("simulator", "physical"):
        raise SafetyError("Ungültige Betriebsart")
    if value == "physical" and not config.physical_maintenance:
        raise SafetyError(
            "Physischer Zugriff muss administrativ für den Worker eingerichtet sein"
        )
    with control.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        if db.execute(
            "SELECT 1 FROM commands WHERE state IN ('QUEUED','RUNNING')"
        ).fetchone():
            raise SafetyError("Betriebsart erst nach Abschluss aller Aufträge wechseln")
        db.execute(
            "INSERT INTO settings VALUES('operation_mode',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (json.dumps(value),),
        )
    control.sync_event("config", "UPDATED", None, "Betriebsart: " + value)


def prepare(
    config: WebConfig, control: Control, drive_id: str, operation: str
) -> dict[str, Any]:
    if not config.physical_maintenance or mode(config, control) != "physical":
        raise SafetyError(
            "Zuerst ausdrücklich den physischen Wartungsbetrieb aktivieren"
        )
    if operation not in ("qualify", "erase-short", "erase-long"):
        raise SafetyError("Ungültige Wartungsaktion")
    inventory = control.get("hardware_inventory", {})
    if time.time() - inventory.get("time", 0) > 30:
        raise SafetyError(
            "Laufwerkserkennung ist veraltet; Worker oder Verbindung prüfen"
        )
    drive = next((d for d in inventory.get("drives", []) if d["id"] == drive_id), None)
    if (
        not drive
        or not drive["ready"]
        or not drive.get("medium_serial")
        or not drive.get("serial")
    ):
        raise SafetyError(
            "Laufwerk und Medium müssen eindeutig erkannt und schreibbar sein"
        )
    ident = str(uuid.uuid4())
    phrase = f"{'TESTEN' if operation=='qualify' else 'LÖSCHEN'} {drive['serial']} {drive['medium_serial']}"
    grant = {
        "id": ident,
        "operation": operation,
        "drive": drive,
        "created": time.time(),
        "expires": time.time() + 300,
        "confirmation": phrase,
        "state": "PREPARED",
        "seed": secrets.token_hex(32),
    }
    control.set("maintenance_approval:" + ident, grant)
    return {k: v for k, v in grant.items() if k != "seed"}


def approval(
    config: WebConfig,
    control: Control,
    payload: dict[str, Any],
    *,
    consume: bool = False,
) -> dict[str, Any]:
    if not config.physical_maintenance or mode(config, control) != "physical":
        raise SafetyError("Physischer Wartungsbetrieb ist nicht aktiviert")
    if (
        set(payload) != {"approval_id", "confirmation", "destructive_confirmed"}
        or payload["destructive_confirmed"] is not True
    ):
        raise SafetyError(
            "Ausdrückliche Freigabe des destruktiven Vorgangs erforderlich"
        )
    if not isinstance(payload["approval_id"], str):
        raise SafetyError("Ungültige Freigabe")
    uuid.UUID(payload["approval_id"])
    with control.connect() as db:
        if consume:
            db.execute("BEGIN IMMEDIATE")
        row = db.execute(
            "SELECT value FROM settings WHERE key=?",
            ("maintenance_approval:" + payload["approval_id"],),
        ).fetchone()
        grant = json.loads(row[0]) if row else None
        if (
            not grant
            or grant["state"] != "PREPARED"
            or grant["expires"] < time.time()
            or payload["confirmation"] != grant["confirmation"]
        ):
            raise SafetyError(
                "Freigabe fehlt, ist abgelaufen/verbraucht oder Bestätigung stimmt nicht überein"
            )
        if consume:
            grant["state"] = "CONSUMED"
            grant["consumed"] = time.time()
            db.execute(
                "UPDATE settings SET value=? WHERE key=?",
                (json.dumps(grant), "maintenance_approval:" + grant["id"]),
            )
        return grant


def execute(
    config: WebConfig, control: Control, payload: dict[str, Any]
) -> dict[str, Any]:
    # Consume BEFORE touching the device. Restart/retry must require a new review.
    grant = approval(config, control, payload, consume=True)
    key = "maintenance_progress:" + grant["id"]

    def progress(**values):
        old = control.get(key, {})
        control.set(
            key,
            {
                **old,
                **values,
                "time": time.time(),
                "drive": grant["drive"],
                "operation": grant["operation"],
                "approval_id": grant["id"],
            },
        )

    try:
        device = LinuxMaintenance(grant["drive"], config.state / "drive-locks")
        with io_lock(), device.locked():
            progress(phase="STARTING", state="RUNNING", seed=grant["seed"])
            result = (
                qualify(device, grant["seed"], progress)
                if grant["operation"] == "qualify"
                else erase(device, grant["operation"] == "erase-long", progress)
            )
            progress(
                phase=result["state"],
                state="SUCCEEDED",
                result=result,
                bytes=result.get("bytes", 0),
            )
            return result
    except BaseException as error:
        progress(phase="INCOMPLETE", state="FAILED", error=str(error))
        raise
