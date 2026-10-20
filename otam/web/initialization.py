"""Explicit initialization of locally unregistered cartridges, never recycling.

The short-lived grant seals drive/MAM, native profile and media metadata. Only
the worker opens a device. Known catalog identities and unresolved intents are
protected; catalog loss requires read-only registration/recovery, not formatting.
"""
from __future__ import annotations

import hashlib
import json
import time
import uuid
from typing import Any

from ..catalog import Catalog
from ..common import FORMAT, SafetyError, encode
from ..physical import discover_drives
from ..storage import io_lock
from ..tape import LinuxTape
from ..transfer import selected_speed_profile
from .config import WebConfig
from .control import Control
from . import maintenance, physical_archive

PREFIX = "initialization_approval:"
REVIEW_FIELDS = ("id", "node_id", "drive", "profile_id", "capacity", "label", "media_class", "created", "expires", "confirmation")


def availability(config: WebConfig, control: Control, drive: dict) -> dict:
    """Explain the same cached, read-only gates used by the admin review."""
    try:
        require_enabled(config, control)
        validate = {"drive_id":drive.get("id"), "drive_serial":drive.get("serial"), "medium_serial":drive.get("medium_serial")}
        physical_archive.validate_registration(config,control,validate)
        _profile(control.get("hardware_inventory"),drive)
        with control.connect() as db:
            _unused(config,control,drive["medium_serial"],db)
        return {"enabled":True,"reason":""}
    except (SafetyError, ValueError, KeyError) as error:
        return {"enabled":False,"reason":str(error)}


def require_enabled(config: WebConfig, control: Control) -> None:
    physical_archive.require_mode(config, control)
    if not config.physical_initialization:
        raise SafetyError("Physische Initialisierung benötigt eine separate administrative Freigabe")


def _digest(grant: dict[str, Any]) -> str:
    fields = (*REVIEW_FIELDS, 'previous_initializations') if 'previous_initializations' in grant else REVIEW_FIELDS
    return hashlib.sha256(encode({key: grant[key] for key in fields})).hexdigest()


def _workflow(config, control, reinitialize):
    require_enabled(config, control)
    if reinitialize and not config.physical_reinitialization:
        raise SafetyError('Explizite Neuinitialisierung ist administrativ nicht freigegeben')
    return 'reinitialization_approval:' if reinitialize else PREFIX



def _profile(inventory: dict[str, Any], drive: dict[str, Any]) -> dict[str, Any]:
    profile = selected_speed_profile(inventory, drive["id"])
    if (profile is None or type(profile.get("native_capacity_bytes")) is not int
            or not drive.get("ready") or drive.get("status", {}).get("write_protected")):
        raise SafetyError("Kein bestätigtes schreibbereites Profil mit nativer Medienkapazität")
    return profile


def _unused(config: WebConfig, control: Control, serial: str, db, *, own: str = "") -> None:
    if any(b.get("medium_serial") == serial for b in physical_archive.bindings(control).values()):
        raise SafetyError("Bereits bekannte Kassette: nur lesend registrieren, nicht initialisieren")
    catalog = Catalog(config.catalog)
    try:
        for row in catalog.db.execute("SELECT serial,header_json FROM media"):
            header = json.loads(row["header_json"])
            if header.get("backend") == "simulator":
                continue
            if row["serial"] == serial or header.get("medium_serial") == serial:
                raise SafetyError("Bereits bekannte Kassette: nur lesend registrieren, nicht initialisieren")
    finally:
        catalog.close()
    pending = config.state / "physical-pending" / (hashlib.sha256(serial.encode()).hexdigest() + ".json")
    if pending.exists() or pending.is_symlink():
        raise SafetyError("Ungeklärter Schreibvorgang: Initialisierung gesperrt")
    reset = config.state / "physical-reset" / pending.name
    if reset.exists() or reset.is_symlink():
        raise SafetyError("Ungeklärtes Zurücksetzen: Initialisierung gesperrt")
    for row in db.execute("SELECT value FROM settings WHERE key LIKE 'reinitialization_approval:%'"):
        value = json.loads(row[0])
        if (value.get('id') != own and value.get('drive',{}).get('medium_serial') == serial
                and (value.get('state') in ('CONSUMED','SUCCEEDED','INTERRUPTED') or value.get('write_attempted'))):
            raise SafetyError('Frühere Neuinitialisierung gespeichert; getrennten Review verwenden')
    for row in db.execute("SELECT value FROM settings WHERE key LIKE ?", (PREFIX + "%",)):
        other = json.loads(row[0])
        if (other.get("id") != own and other.get("drive", {}).get("medium_serial") == serial
                and (other.get("state") in ("CONSUMED", "SUCCEEDED", "INTERRUPTED")
                     or other.get("write_attempted"))):
            if other.get('state') == 'SUCCEEDED':
                raise SafetyError('Initialisierung bereits abgeschlossen (Medien-ID '+str(other.get('media_id','unbekannt'))+'). Medium fehlt im aktuellen Katalog: lesend registrieren oder ausdrücklich neu initialisieren.')
            raise SafetyError('Frühere Initialisierung ungeklärt; lesende Prüfung erforderlich, kein Erzwingen erlaubt')


def prepare(config: WebConfig, control: Control, data: dict[str, Any], *, reinitialize: bool = False) -> dict[str, Any]:
    prefix = _workflow(config, control, reinitialize)
    if (set(data) != {"drive_id", "drive_serial", "medium_serial", "label", "media_class"}
            or not isinstance(data.get("label"), str) or not 1 <= len(data["label"].strip()) <= 100
            or any(ord(c) < 32 for c in data["label"])
            or data.get("media_class") not in ("permanent", "rotation")):
        raise SafetyError("Geprüfte Medienbezeichnung und Medienklasse erforderlich")
    identity = {key: data[key] for key in ("drive_id", "drive_serial", "medium_serial")}
    drive = physical_archive.validate_registration(config, control, identity)
    inventory = control.get("hardware_inventory")
    profile = _profile(inventory, drive)
    now = time.time()
    grant = {"id": str(uuid.uuid4()), "node_id": config.node_id, "drive": drive,
             "profile_id": profile["profile_id"], "capacity": profile["native_capacity_bytes"],
             "label": data["label"].strip(), "media_class": data["media_class"],
             "created": now, "expires": now + 300,
             "confirmation": f"INITIALIZE {drive['serial']} {drive['medium_serial']}",
             "state": "PREPARED", "write_attempted": False}
    grant["review_hash"] = _digest(grant)
    with control.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        if reinitialize:
            from .reinitialization import eligible
            grant['previous_initializations'] = eligible(config, control, drive['medium_serial'], db)
            grant['confirmation'] = f"REINITIALIZE {drive['serial']} {drive['medium_serial']}"
            grant['review_hash'] = _digest(grant)
        else:
            _unused(config, control, drive['medium_serial'], db)
        db.execute("INSERT INTO settings VALUES(?,?)", (prefix + grant["id"], json.dumps(grant)))
    return grant


def approval(config: WebConfig, control: Control, payload: dict[str, Any], *, consume: bool = False, reinitialize: bool = False) -> dict[str, Any]:
    prefix = _workflow(config, control, reinitialize)
    if (set(payload) != {"approval_id", "confirmation", "destructive_confirmed"}
            or payload["destructive_confirmed"] is not True or not isinstance(payload["approval_id"], str)):
        raise SafetyError("Ausdrückliche Freigabe des destruktiven Vorgangs erforderlich")
    uuid.UUID(payload["approval_id"])
    with control.connect() as db:
        if consume:
            db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT value FROM settings WHERE key=?", (prefix + payload["approval_id"],)).fetchone()
        grant = json.loads(row[0]) if row else None
        now = time.time()
        if (not grant or not set(REVIEW_FIELDS) <= grant.keys()
                or grant.get("state") != "PREPARED" or grant.get("node_id") != config.node_id
                or type(grant.get("created")) not in (int, float) or not 0 <= now - grant["created"] <= 300
                or grant.get("expires") != grant["created"] + 300
                or grant["expires"] < now or payload["confirmation"] != grant.get("confirmation")
                or grant.get("review_hash") != _digest(grant)):
            raise SafetyError("Initialisierungsfreigabe fehlt, ist verändert, abgelaufen oder verbraucht")
        if reinitialize:
            from .reinitialization import eligible
            if grant.get('previous_initializations') != eligible(config,control,grant['drive']['medium_serial'],db,own=grant['id']):
                raise SafetyError('Initialisierungshistorie hat sich seit dem Review geändert')
        elif 'previous_initializations' in grant:
            raise SafetyError('Falscher Initialisierungsworkflow')
        if consume:
            if not reinitialize:
                _unused(config, control, grant["drive"]["medium_serial"], db, own=grant["id"])
            grant.update(state="CONSUMED", consumed=now)
            db.execute("UPDATE settings SET value=? WHERE key=?", (json.dumps(grant), prefix + grant["id"]))
    return grant


def execute(config: WebConfig, control: Control, payload: dict[str, Any], *, reinitialize: bool = False) -> dict[str, Any]:
    prefix = _workflow(config,control,reinitialize)
    grant = approval(config, control, payload, consume=True, reinitialize=reinitialize)
    key = "maintenance_progress:" + grant["id"]
    catalog = Catalog(config.catalog)
    job = None

    def progress(state: str, phase: str, **values: Any) -> None:
        control.set(key, {"state": state, "phase": phase, "time": time.time(), "operation": "reinitialize" if reinitialize else "initialize",
                          "approval_id": grant["id"], "drive": grant["drive"], **values})

    try:
        progress("RUNNING", "PRECHECK")
        with io_lock():
            matches = [d for d in discover_drives() if all(d.get(key) == grant["drive"][key]
                       for key in ("id", "serial", "medium_serial"))]
            if len(matches) != 1:
                raise SafetyError("Physische Identität hat sich seit der Auswahl geändert")
            drive = matches[0]
            profile = _profile({"time": time.time(), "drives": [drive]}, drive)
            if profile["profile_id"] != grant["profile_id"] or profile["native_capacity_bytes"] != grant["capacity"]:
                raise SafetyError("Native Medienkapazität oder Laufwerksprofil hat sich geändert")
            tape = LinuxTape(drive, config.state)
            with tape.locked():
                with control.connect() as db:
                    if reinitialize:
                        from .reinitialization import eligible
                        if eligible(config,control,drive['medium_serial'],db,own=grant['id']) != grant['previous_initializations']:
                            raise SafetyError('Initialisierungshistorie hat sich geändert')
                    else:
                        _unused(config, control, drive["medium_serial"], db, own=grant["id"])
                if reinitialize:
                    old = tape.header()
                    if (old.get('media_id') != grant['previous_initializations'][-1]['media_id']
                            or old.get('medium_serial') != drive['medium_serial'] or old.get('backend') != 'physical'):
                        raise SafetyError('Vorhandener Header stimmt nicht mit der geprüften Initialisierung überein')
                job = catalog.job("reinitialize" if reinitialize else "initialize", None)
                catalog.event(job, "initialization_confirmed", previous_initializations=grant.get("previous_initializations"), approval_id=grant["id"],
                              review_hash=grant["review_hash"], drive_serial=drive["serial"],
                              medium_serial=drive["medium_serial"], label=grant["label"],
                              native_capacity=grant["capacity"], media_class=grant["media_class"])
                grant["write_attempted"] = True
                control.set(prefix + grant["id"], grant)
                progress("RUNNING", "HEADER_WRITE")
                header = tape.initialize(grant["label"], grant["capacity"], grant["media_class"],
                                         "INITIALIZE " + drive["medium_serial"])
                if (header != tape.header() or len(tape.positions()) != 1
                        or header["medium_serial"] != drive["medium_serial"]
                        or header.get("label") != grant["label"] or header.get("class") != grant["media_class"]
                        or header.get("capacity") != grant["capacity"] or header.get("backend") != "physical"
                        or header.get("format") != FORMAT):
                    raise SafetyError("Initialisierter Header konnte nicht bestätigt werden")
                uuid.UUID(header["media_id"])
                if reinitialize and header['media_id'] == grant['previous_initializations'][-1]['media_id']:
                    raise SafetyError('Neuinitialisierung hat keine neue Medien-ID erzeugt')
                catalog.register(header, tape.used())
                with catalog.db:
                    catalog.db.execute("UPDATE media SET serial=? WHERE id=?", (drive["medium_serial"], header["media_id"]))
                    catalog.db.execute("UPDATE jobs SET media_id=? WHERE id=?", (header["media_id"], job))
                saved = physical_archive.bindings(control)
                saved[header["media_id"]] = {"media_id": header["media_id"], "drive_serial": drive["serial"],
                                            "medium_serial": drive["medium_serial"], "registered": time.time()}
                control.set("physical_media_bindings", saved)
                result = {"state": "INITIALIZED", "job_id": job, "media_id": header["media_id"],
                          "header": header, "scope": "header readback only; no data archive or full qualification"}
                catalog.finish(job, "SUCCEEDED", report=result)
                grant.update(state="SUCCEEDED", finished=time.time(), media_id=header["media_id"])
                control.set(prefix + grant["id"], grant)
                progress("SUCCEEDED", "INITIALIZED", result=result)
                control.sync_event("config", "UPDATED", None, "Physisches OTAM-Medium initialisiert: " + header["media_id"])
                return result
    except BaseException as error:
        # A consumed uncertain intent is never silently cleared, even when the
        # header write succeeded but catalog/binding publication failed.
        grant.update(state="FAILED", finished=time.time(), error=str(error))
        control.set(prefix + grant["id"], grant)
        progress("FAILED", "INCOMPLETE" if grant["write_attempted"] else "NOT_STARTED", error=str(error))
        if job is not None:
            catalog.finish(job, "FAILED", str(error))
        raise
    finally:
        catalog.close()
