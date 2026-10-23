"""Conservative physical media projections for planning without a loaded tape.

These are catalog estimates, never an assertion about the current device/EOD.
The write path must independently inspect the physical medium and receipt chain.
"""
from __future__ import annotations

import json
import re
import uuid
from typing import Any

from .catalog import Catalog
from .common import FORMAT, SafetyError


def catalogue_snapshot(catalog: Catalog, media: str) -> dict[str, Any]:
    row = catalog.db.execute("SELECT * FROM media WHERE id=?", (media,)).fetchone()
    if row is None or row["state"] not in ("READY", "IN_USE"):
        raise SafetyError("Catalog medium is not ready for planning")
    header = json.loads(row["header_json"])
    if (header.get("format") != FORMAT or header.get("backend") != "physical"
            or header.get("media_id") != media or not isinstance(header.get("medium_serial"), str)
            or not header["medium_serial"] or type(header.get("capacity")) is not int
            or header["capacity"] != row["capacity"] or header.get("class") != row["class"]
            or header.get("label") != row["label"]):
        raise SafetyError("Physical catalog identity is inconsistent")
    uuid.UUID(media)
    archives = list(catalog.db.execute(
        "SELECT * FROM archives WHERE media_id=? ORDER BY tape_file", (media,)))
    if (len(archives) > 2047 or [a["tape_file"] for a in archives] != list(range(1, 2 * len(archives), 2))):
        raise SafetyError("Catalog archive sequence is incomplete")
    minimum = 10240  # PAX header and each receipt occupy at least one TAR record.
    for archive in archives:
        manifest = json.loads(archive["manifest_json"])
        if (archive["state"] != "VERIFIED" or type(archive["bytes"]) is not int
                or archive["bytes"] <= 0 or archive["bytes"] % 512
                or not isinstance(archive["sha256"], str)
                or re.fullmatch("[0-9a-f]{64}", archive["sha256"]) is None
                or manifest.get("archive_id") != archive["id"]
                or manifest.get("media_id") != media):
            raise SafetyError("Only consistent VERIFIED archives may be planned around")
        uuid.UUID(archive["id"])
        minimum += archive["bytes"] + 10240
    if (type(row["used"]) is not int or not minimum <= row["used"] <= row["capacity"]
            or row["capacity"] < 32768):
        raise SafetyError("Catalog capacity is unknown or inconsistent")
    return {"record": dict(row), "header": header, "used": row["used"],
            "expected_tape_files": 2 * len(archives) + 1}
