"""Bounded read-only SCSI LOG SENSE sampling, explicit units and unknown values."""

from __future__ import annotations

import time
import re
import subprocess
from pathlib import Path
from typing import Any, Callable

from .common import SafetyError
from .physical import run

PAGES = {
    0x2E: "TapeAlert",
    0x02: "Schreibfehlerzähler",
    0x03: "Lesefehlerzähler",
    0x0D: "Temperatur",
}
ERROR_COUNTERS = {
    0: ("corrected_without_delay", "Ohne Verzögerung korrigiert", "count"),
    1: ("corrected_with_delay", "Mit Verzögerung korrigiert", "count"),
    2: ("retries", "Wiederholungen", "count"),
    3: ("corrected_total", "Korrigierte Fehler gesamt", "count"),
    4: ("correction_invocations", "Fehlerkorrektur-Aufrufe", "count"),
    5: ("bytes_processed", "Verarbeitete Bytes", "bytes"),
    6: ("uncorrected_total", "Nicht korrigierte Fehler", "count"),
}
STATS = (
    "read_byte_cnt",
    "write_byte_cnt",
    "read_cnt",
    "write_cnt",
    "read_ns",
    "write_ns",
    "io_ns",
    "in_flight",
    "resid_cnt",
    "other_cnt",
)


def parameters(data: bytes, page: int) -> dict[int, bytes]:
    if len(data) < 4 or data[0] & 0x40 or data[0] & 0x3F != page or data[1] != 0:
        raise SafetyError("Falsche oder unvollständige SCSI-Logseite")
    length = int.from_bytes(data[2:4], "big")
    if len(data) != length + 4 or len(data) > 4096:
        raise SafetyError("Abgeschnittene oder übergroße SCSI-Logseite")
    offset = 4
    result = {}
    while offset < len(data):
        if offset + 4 > len(data):
            raise SafetyError("Abgeschnittener Logparameter")
        ident = int.from_bytes(data[offset : offset + 2], "big")
        size = data[offset + 3]
        offset += 4
        if offset + size > len(data) or ident in result:
            raise SafetyError("Ungültiger oder doppelter Logparameter")
        result[ident] = data[offset : offset + size]
        offset += size
    return result


def decode(data: bytes, page: int) -> dict[str, Any]:
    values = parameters(data, page)
    if page == 0x2E:
        if not values:
            raise SafetyError(
                "TapeAlert-Seite enthält keine Parameter; Status unbekannt"
            )
        if any(
            not 1 <= code <= 64 or len(value) != 1 or value[0] not in (0, 1)
            for code, value in values.items()
        ):
            raise SafetyError("Unbekanntes TapeAlert-Parameterformat")
        return {
            "active_flags": [code for code, value in values.items() if value[0]],
            "reported_flags": len(values),
        }
    if page in (2, 3):
        counters = []
        for code, value in values.items():
            if code in ERROR_COUNTERS:
                if not 1 <= len(value) <= 8:
                    raise SafetyError("Ungültige Fehlerzählerbreite")
                name, label, unit = ERROR_COUNTERS[code]
                # Decimal strings retain all 64 bits when consumed by JavaScript.
                counters.append(
                    {
                        "code": code,
                        "name": name,
                        "label": label,
                        "unit": unit,
                        "value": str(int.from_bytes(value, "big")),
                    }
                )
        if not counters:
            raise SafetyError("Keine unterstützten Fehlerzähler verfügbar")
        return {
            "counters": counters,
            "scope": "drive_reported; may reset on power cycle; not a per-medium lifetime estimate",
        }
    if page == 0x0D:
        result = {}
        for code, key in ((0, "current_celsius"), (1, "reference_celsius")):
            value = values.get(code)
            if value is None:
                result[key] = None
            elif len(value) != 2:
                raise SafetyError("Ungültiger Temperaturparameter")
            else:
                result[key] = None if value[1] == 255 else value[1]
        return result
    raise SafetyError("Nicht erlaubte Diagnose-Logseite")


def kernel_stats(drive: dict[str, Any]) -> dict[str, str]:
    # Paths come from discovery, not browser-supplied values.
    name = Path(drive["device"]).name
    if not re.fullmatch(r"nst[0-9]+", name):
        raise SafetyError("Ungültiger Laufwerkspfad")
    root = Path("/sys/class/scsi_tape") / name / "stats"
    result = {}
    for field in STATS:
        try:
            value = (root / field).read_text().strip()
            if value.isascii() and value.isdigit() and len(value) <= 24:
                result[field] = value
        except OSError:
            pass
    return result


def collect(
    drive: dict[str, Any], sink: Callable[[dict[str, Any]], None]
) -> dict[str, Any]:
    """Read only these four pages; NEVER log-select, reset, position or open tape data.

    TapeAlert can acknowledge flags at the device. Persist each raw response before
    issuing another command, then persist its decoded result (or parse failure).
    A sink/storage failure aborts sampling rather than silently losing warnings.
    """
    result = {
        "drive_id": drive["id"],
        "drive_serial": drive.get("serial"),
        "medium_serial": drive.get("medium_serial"),
        "medium_context": "last_identity_observation",
        "started": time.time(),
        "pages": {},
        "kernel_stats": kernel_stats(drive),
    }
    for page, label in PAGES.items():
        sample = {
            "page": page,
            "label": label,
            "time": time.time(),
            "state": "UNAVAILABLE",
        }
        try:
            sg = drive.get("sg")
            if not sg:
                raise SafetyError("SCSI-Generic-Gerät nicht zugänglich")
            raw = run(
                [
                    "sg_logs",
                    "--readonly",
                    "--raw",
                    "--raw",  # sg_logs -rr includes the log-page header.
                    "--maxlen=4096",
                    f"--page=0x{page:02x}",
                    sg,
                ],
                timeout=5,
            )
        except (OSError, SafetyError, subprocess.TimeoutExpired) as error:
            sample["error"] = str(error)
        else:
            sample.update(raw_hex=raw.hex(), state="CAPTURED")
            sink({**result, "page_sample": dict(sample)})
            try:
                sample.update(decoded=decode(raw, page), state="AVAILABLE")
            except SafetyError as error:
                sample.update(error=str(error), state="INVALID")
        result["pages"][f"{page:02x}"] = sample
        sink({**result, "page_sample": dict(sample)})
    result["time"] = time.time()
    return result
