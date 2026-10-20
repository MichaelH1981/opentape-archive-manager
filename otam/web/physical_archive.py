"""Shared fail-closed physical media bindings and per-job transfer selection.

Registration reads an existing OTAM header only. This module never initializes
media; UUID, MAM identity and drive serial persist independently of /dev names.
"""
from __future__ import annotations

import time
import uuid
from typing import Any

from ..catalog import Catalog
from ..common import SafetyError
from ..physical import discover_drives
from ..service import ArchiveService
from ..storage import require_local
from ..tape import LinuxTape
from ..transfer import selected_speed_profile
from . import maintenance, resources
from .config import WebConfig
from .control import Control


def bindings(control: Control) -> dict[str, dict[str, Any]]:
    return control.get("physical_media_bindings", {})


def require_mode(config: WebConfig, control: Control, *, archive: bool = True) -> None:
    if (config.role != "archive" or not config.physical_maintenance
            or maintenance.mode(config, control) != "physical"
            or (archive and not config.physical_archiving)):
        raise SafetyError("Physische Archivierung benötigt die separate administrative Bandformat-Abnahme")


def validate_registration(config: WebConfig, control: Control, payload: dict[str, Any]) -> dict[str, Any]:
    require_mode(config, control, archive=False)
    if (set(payload) != {"drive_id", "drive_serial", "medium_serial"}
            or any(not isinstance(v, str) or not 1 <= len(v) <= 128 for v in payload.values())):
        raise SafetyError("Eindeutige Laufwerks- und MAM-Identität erforderlich")
    inventory = control.get("hardware_inventory", {})
    if not 0 <= time.time() - inventory.get("time", 0) <= 120:
        raise SafetyError("Laufwerkserkennung ist veraltet")
    matches = [d for d in inventory.get("drives", []) if d.get("id") == payload["drive_id"]
               and d.get("serial") == payload["drive_serial"]
               and d.get("medium_serial") == payload["medium_serial"]
               and d.get("status", {}).get("online") and not d.get("busy")]
    if len(matches) != 1:
        raise SafetyError("Laufwerk und eingelegtes Medium stimmen nicht überein")
    return matches[0]


def register_existing(config: WebConfig, control: Control, payload: dict[str, Any]) -> dict[str, Any]:
    validate_registration(config, control, payload)
    matches = [d for d in discover_drives() if d.get("id") == payload["drive_id"]
               and d.get("serial") == payload["drive_serial"]
               and d.get("medium_serial") == payload["medium_serial"]]
    if len(matches) != 1:
        raise SafetyError("Physische Identität hat sich seit der Auswahl geändert")
    tape = LinuxTape(matches[0], config.state)
    catalog = Catalog(config.catalog)
    try:
        # register() checks the physical header/receipt accounting, not all data.
        header = ArchiveService(catalog, tape).register()
        uuid.UUID(header["media_id"])
        if header.get("medium_serial") != payload["medium_serial"] or header.get("backend") != "physical":
            raise SafetyError("Kein passendes selbstbeschreibendes OTAM-Medium")
        with control.connect() as db:
            if db.execute("SELECT 1 FROM resources WHERE id=?", (header["media_id"],)).fetchone():
                raise SafetyError("Medien-ID ist bereits als Simulator registriert")
        saved = bindings(control)
        binding = {"media_id": header["media_id"], "drive_serial": payload["drive_serial"],
                   "medium_serial": payload["medium_serial"]}
        if header["media_id"] in saved and any(saved[header["media_id"]].get(k) != v for k, v in binding.items()):
            raise SafetyError("Bestehende physische Medienbindung darf nicht ersetzt werden")
        saved[header["media_id"]] = {**binding, "registered": time.time()}
        control.set("physical_media_bindings", saved)
        control.sync_event("config", "UPDATED", None, "Physisches OTAM-Medium registriert: " + header["media_id"])
        return {**header, "binding": saved[header["media_id"]]}
    finally:
        catalog.close()


def transfer_settings(config: WebConfig, control: Control, staging_id: str,
                      drive: dict[str, Any]) -> dict[str, Any]:
    value = control.get("transfer_settings:" + staging_id)
    profile = selected_speed_profile({"time": time.time(), "drives": [drive]}, drive["id"])
    if not isinstance(value, dict) or profile is None:
        raise SafetyError("Geprüfte Transferwerte für dieses Laufwerk und Staging speichern")
    for key in ("drive_id", "drive_serial", "profile_id", "medium_density_code"):
        if value.get(key) != profile[key]:
            raise SafetyError("Transferwerte passen nicht zum aktuellen Laufwerks-/Medienprofil")
    rate, buffer = value.get("write_rate_bytes_per_second"), value.get("buffer_bytes")
    if (type(rate) is not int or rate not in profile["speed_steps_bytes_per_second"]
            or type(buffer) is not int or not 256 * 1024**2 <= buffer <= 4 * 1024**3
            or buffer % (64 * 1024**2)):
        raise SafetyError("Ungültige gespeicherte Transferrate oder Puffergröße")
    storage = require_local(resources.staging_for(config, control, staging_id))
    if value.get("storage") != {key: storage[key] for key in ("mount", "source", "device", "type")}:
        raise SafetyError("Staging-Dateisystem hat sich seit der Transferauswahl geändert")
    return value


def mounted(config: WebConfig, control: Control, media: str, *, staging_id: str | None = None) -> LinuxTape:
    require_mode(config, control)
    binding = bindings(control).get(media)
    if not binding or binding.get("media_id") != media:
        raise SafetyError("Physisches Medium ist nicht ausdrücklich registriert")
    inventory = control.get("hardware_inventory", {})
    if not 0 <= time.time() - inventory.get("time", 0) <= 120:
        raise SafetyError("Laufwerkserkennung ist veraltet")
    matches = [d for d in inventory.get("drives", [])
               if d.get("serial") == binding["drive_serial"]
               and d.get("medium_serial") == binding["medium_serial"]
               and d.get("status", {}).get("online") and not d.get("busy")]
    if len(matches) != 1:
        raise SafetyError("Benötigtes Band/Laufwerk ist nicht eindeutig eingelegt")
    drive = matches[0]
    options = {}
    if staging_id is not None:
        if not drive.get("ready") or drive.get("status", {}).get("write_protected"):
            raise SafetyError("Das eingelegte Medium ist nicht schreibbereit")
        value = transfer_settings(config, control, staging_id, drive)
        options = {"buffer_mib": value["buffer_bytes"] // 1024**2,
                   "write_rate": value["write_rate_bytes_per_second"]}
    # No device is opened here. LinuxTape.locked()/writer() re-detect and verify
    # the real identity immediately before device operations in the worker.
    return LinuxTape(drive, config.state, **options)
