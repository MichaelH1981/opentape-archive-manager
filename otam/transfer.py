"""Documented drive/media speed profiles for future host-stream throttling.

A selected value is a host transfer target, not a SCSI command that fixes tape motion.
Unknown drive/media combinations intentionally have no selectable speed.
"""

from __future__ import annotations

import time
from typing import Any


# IBM Ultrium 4 half-height, LTO-4 medium (SCSI density code 0x46).
# Source: IBM announcement 108-464, Digital speed matching, six native rates.
IBM_HH4_LTO4_MBPS = (30, 48, 66, 84, 103, 120)
PROFILE_IBM_HH4_LTO4 = "ibm-ult3580-hh4-lto4"
PROFILE_MAX_AGE_SECONDS = 120


def drive_speed_profiles(inventory: dict[str, Any] | None, *, now: float | None = None) -> list[dict[str, Any]]:
    """Return only currently observed, identified LTO-4 drive/media profiles."""
    if not isinstance(inventory, dict):
        return []
    observed = inventory.get("time")
    now = time.time() if now is None else now
    if not isinstance(observed, (int, float)) or not 0 <= now - observed <= PROFILE_MAX_AGE_SECONDS:
        return []
    result = []
    for drive in inventory.get("drives", []):
        if not isinstance(drive, dict):
            continue
        status = drive.get("status") or {}
        if (str(drive.get("vendor", "")).strip().upper() != "IBM"
                or str(drive.get("model", "")).strip().upper() != "ULT3580-HH4"
                or not drive.get("id") or not drive.get("serial")
                or status.get("density_code") != 0x46
                or not status.get("online")
                or not drive.get("medium_serial") or drive.get("busy")):
            continue
        result.append({
            "drive_id": drive["id"],
            "drive_serial": drive["serial"],
            "vendor": "IBM",
            "model": "ULT3580-HH4",
            "medium_density_code": 0x46,
            "profile_id": PROFILE_IBM_HH4_LTO4,
            "native_capacity_bytes": 800_000_000_000,
            "speed_steps_bytes_per_second": [rate * 1_000_000 for rate in IBM_HH4_LTO4_MBPS],
            "source": "https://www.ibm.com/docs/en/announcement_archive/ENUS108-464/ENUS108-464.PDF",
            "observed_at": observed,
        })
    return result


def selected_speed_profile(inventory: dict[str, Any] | None, drive_id: str,
                           *, now: float | None = None) -> dict[str, Any] | None:
    return next((profile for profile in drive_speed_profiles(inventory, now=now)
                 if profile["drive_id"] == drive_id), None)
