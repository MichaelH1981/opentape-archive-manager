"""Guided multi-medium archive sets using independent, self-describing media.

Physical operation has a separate default-off gate. Its plans use registered
catalog projections; every loaded medium is independently checked before write.
"""
from __future__ import annotations

import hashlib
import json
import time
import uuid
from pathlib import Path
from typing import Any

from .archive import MAX_META, estimate, inventory, plan_archives
from .catalog import Catalog
from .common import SafetyError, encode
from .service import ArchiveService, scan, inspect_catalogued_media
from .storage import io_lock
from .tape import Tape
from .planning import catalogue_snapshot


def plan_set(catalog: Catalog, source: Path, media_tapes: list[tuple[str, Tape | None]],
             target: int, selected: list[str] | None = None,
             verify_mode: str = "archive", *, catalogue_only: bool = False) -> dict[str, Any]:
    if not 2 <= len(media_tapes) <= 32 or len({m for m, _ in media_tapes}) != len(media_tapes):
        raise SafetyError("Choose two to 32 distinct media in order")
    if verify_mode not in ("archive", "media") or target <= 0:
        raise SafetyError("Invalid archive planning options")
    root = source.resolve()
    if catalog.path.is_relative_to(root):
        raise SafetyError("Catalog must be outside source tree")
    with io_lock():
        entries = inventory(root, selected)
        manifests = plan_archives(entries, media_tapes[0][0], target)
        if any(len(encode(m)) > MAX_META for m in manifests):
            raise SafetyError("Manifest exceeds limit; reduce archive target size")
        available: dict[str, int] = {}
        positions: dict[str, int] = {}
        physical_serials: set[str] = set()
        for media, tape in media_tapes:
            if catalogue_only:
                snapshot = catalogue_snapshot(catalog, media)
                serial = snapshot["header"]["medium_serial"]
                if serial in physical_serials:
                    raise SafetyError("Physical media IDs refer to the same cartridge")
                physical_serials.add(serial)
                positions[media] = snapshot["expected_tape_files"]
                available[media] = snapshot["record"]["capacity"] * 95 // 100 - snapshot["used"]
                continue
            if tape is None:
                raise SafetyError("Loaded medium required for device-based planning")
            tape_path = getattr(tape, "path", None)
            if tape_path is not None and (tape_path.is_relative_to(root) or root.is_relative_to(tape_path)):
                raise SafetyError("Source and simulator medium must be separate")
            with tape.locked():
                record = ArchiveService(catalog, tape)._identity(media)
                if record["state"] not in ("READY", "IN_USE"):
                    raise SafetyError("Medium is not writable")
                if tape.header().get("backend") == "physical":
                    inspect_catalogued_media(catalog, tape, media)
                else:
                    scan(tape, media)
                positions[media] = len(tape.positions())
                available[media] = record["capacity"] * 95 // 100 - tape.used()
        assignments: dict[str, list[dict[str, Any]]] = {media: [] for media, _ in media_tapes}
        remaining = available.copy()
        index = 0
        for manifest in manifests:
            required = estimate(manifest["files"]) + 10240
            while index < len(media_tapes) and required > remaining[media_tapes[index][0]]:
                index += 1
            if index == len(media_tapes):
                raise SafetyError("Selected media cannot hold every complete TAR; no medium was written")
            media = media_tapes[index][0]
            manifest["media_id"] = media
            assignments[media].append(manifest)
            remaining[media] -= required
        parent_id = str(uuid.uuid4())
        children = []
        child_plans = []
        for media, _ in media_tapes:
            group = assignments[media]
            if not group:
                continue
            child_id = str(uuid.uuid4())
            child = {"media_id": media, "source": str(root), "archives": group,
                     "required_estimate": available[media] - remaining[media],
                     "available": available[media],
                     "payload_bytes": sum(entry["size"] for m in group for entry in m["files"]),
                     "file_count": sum(len(m["files"]) for m in group),
                     "expected_tape_files": positions[media], "verify_mode": verify_mode,
                     "parent_job": parent_id}
            if selected is not None:
                child["selected_paths"] = sorted(set(selected))
            if catalogue_only:
                child["planning_basis"] = "catalogue; physical preflight required before write"
            child["sha256"] = hashlib.sha256(encode(child)).hexdigest()
            child_plans.append((child_id, child))
            children.append({"job_id": child_id, "media_id": media,
                             "archives": len(group), "files": child["file_count"],
                             "payload_bytes": child["payload_bytes"],
                             "required_estimate": child["required_estimate"]})
        parent = {"source": str(root), "children": children,
                  "media_ids": [child["media_id"] for child in children],
                  "verify_mode": verify_mode, "target": target,
                  "payload_bytes": sum(e["size"] for e in entries),
                  "file_count": len(entries)}
        if selected is not None:
            parent["selected_paths"] = sorted(set(selected))
        if catalogue_only:
            parent["planning_basis"] = "catalogue; physical preflight required before write"
        parent["sha256"] = hashlib.sha256(encode(parent)).hexdigest()
        now = time.time()
        with catalog.db:
            catalog.db.execute("""INSERT INTO jobs(id,kind,state,media_id,created,updated,plan_json,phase)
                VALUES(?,'archive-set','PLANNED',NULL,?,?,?,'INVENTORY')""",
                (parent_id, now, now, encode(parent).decode()))
            for child_id, child in child_plans:
                catalog.db.execute("""INSERT INTO jobs(id,kind,state,media_id,created,updated,plan_json,phase)
                    VALUES(?,'archive','PLANNED',?,?,?,?, 'INVENTORY')""",
                    (child_id, child["media_id"], now, now, encode(child).decode()))
                for manifest in child["archives"]:
                    catalog.db.execute("""INSERT INTO staged_archives
                        (job_id,archive_id,phase,state,total_bytes,updated)
                        VALUES(?,?,'INVENTORY','COMPLETE',?,?)""",
                        (child_id, manifest["archive_id"],
                         sum(e["size"] for e in manifest["files"]), now))
        catalog.event(parent_id, "plan_ready", sha256=parent["sha256"],
                      media=len(children), files=len(entries), bytes=parent["payload_bytes"])
        return {"job_id": parent_id, **parent}


def next_child(catalog: Catalog, parent_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    row = catalog.db.execute("SELECT kind,state,plan_json FROM jobs WHERE id=?", (parent_id,)).fetchone()
    if row is None or row["kind"] != "archive-set" or not row["plan_json"]:
        raise SafetyError("Unknown archive set")
    plan = json.loads(row["plan_json"])
    checksum = plan.pop("sha256")
    if hashlib.sha256(encode(plan)).hexdigest() != checksum:
        raise SafetyError("Stored archive-set plan has changed")
    plan["sha256"] = checksum
    for child in plan["children"]:
        state = catalog.db.execute("SELECT state FROM jobs WHERE id=? AND kind='archive'",
                                   (child["job_id"],)).fetchone()
        if state is None:
            raise SafetyError("Archive-set child job is missing")
        if state["state"] != "VERIFIED":
            return dict(row), child
    if row["state"] != "VERIFIED" and plan["children"]:
        # A crash can happen after the final child commits, before the parent
        # result is persisted. Return that child for a read-only final check.
        return dict(row), plan["children"][-1]
    raise SafetyError("Archive set already verified")


def backup_set_step(catalog: Catalog, parent_id: str, confirmation: str,
                    plan_hash: str, media_id: str, tape: Tape, spool: Path,
                    *, resume: bool = False) -> dict[str, Any]:
    if confirmation != parent_id:
        raise SafetyError("Confirm the reviewed archive-set job ID")
    row, child = next_child(catalog, parent_id)
    plan = json.loads(row["plan_json"])
    if plan_hash != plan["sha256"] or media_id != child["media_id"]:
        raise SafetyError("Wrong media or changed archive-set plan")
    child_state = catalog.db.execute("SELECT state FROM jobs WHERE id=?", (child["job_id"],)).fetchone()[0]
    finalizing = child_state == "VERIFIED" and all(
        catalog.db.execute("SELECT state FROM jobs WHERE id=?", (item["job_id"],)).fetchone()[0] == "VERIFIED"
        for item in plan["children"]
    )
    if row["state"] not in (("PLANNED", "WAITING_MEDIA", "FAILED", "INTERRUPTED", "RUNNING")
                            if finalizing else ("PLANNED", "WAITING_MEDIA", "FAILED", "INTERRUPTED")):
        raise SafetyError("Archive set is not ready for this medium")
    if child_state not in (("VERIFIED",) if finalizing else ("PLANNED", "STAGED", "FAILED", "INTERRUPTED")):
        raise SafetyError("Medium child job is not ready")
    if child_state in ("FAILED", "INTERRUPTED") and not resume:
        raise SafetyError("A failed medium requires explicit resume after inspection")
    with catalog.db:
        catalog.db.execute("UPDATE jobs SET state='RUNNING',phase='TAPE_WRITE',updated=? WHERE id=?",
                           (time.time(), parent_id))
    try:
        service = ArchiveService(catalog, tape)
        if finalizing:
            # Children already committed physical readback. Reconcile a lost
            # parent result against exact identity/EOD/receipts, without claiming
            # a new scrub or re-reading old physical payloads.
            with io_lock(), tape.locked():
                physical = tape.header().get("backend") == "physical"
                if physical:
                    service._identity(media_id)
                    inspect_catalogued_media(catalog, tape, media_id)
            if not physical:
                # Preserve the simulator's existing full reconciliation path.
                service.verify(media_id)
        else:
            service.backup(child["job_id"], child["job_id"], spool, resume=resume)
        remaining = [c for c in plan["children"] if catalog.db.execute(
            "SELECT state FROM jobs WHERE id=?", (c["job_id"],)).fetchone()[0] != "VERIFIED"]
        report = {"job_id": parent_id, "verified_media": len(plan["children"]) - len(remaining),
                  "total_media": len(plan["children"]), "next_media_id": remaining[0]["media_id"] if remaining else None,
                  "files": plan["file_count"], "payload_bytes": plan["payload_bytes"]}
        catalog.finish(parent_id, "WAITING_MEDIA" if remaining else "VERIFIED", report=report)
        return {"state": "WAITING_MEDIA" if remaining else "VERIFIED", **report}
    except BaseException as error:
        catalog.finish(parent_id, "INTERRUPTED" if isinstance(error, (KeyboardInterrupt, SystemExit)) else "FAILED",
                       str(error), {"failed_media": media_id, "staging_retained": True})
        raise
