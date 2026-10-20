"""Application workflows, independent from CLI or a future HTTP transport."""
from __future__ import annotations

import json
import hashlib
import os
import time
import uuid
from pathlib import Path
from typing import Any

from .archive import (MAX_META, create_archive, estimate, inventory, metadata_tar, plan_archives,
                      read_metadata, verify_archive, verify_stream, inspect_stream, PayloadHandler)
from .archive import estimate_entries
from .catalog import Catalog
from .common import FORMAT, SafetyError, encode, sha256
from .restore import PendingRestore
from .tape import Tape
from .staging import StagingStore
from .storage import io_lock
from .benchmark import require_qualification


def scan(tape: Tape, expected_media: str, *, allow_tail: bool = False,
         payload_handler: PayloadHandler | None = None,
         data_positions: set[int] | None = None) -> list[dict[str, Any]]:
    """Verify all pairs, or a restore selection and its preceding receipt chain.

    With data_positions, unselected payloads are NOT verified and are never
    returned. Only receipts up to the last selected archive are needed.
    """
    header = tape.header()
    if header["media_id"] != expected_media:
        raise SafetyError("Wrong medium inserted")
    positions = tape.positions()
    if data_positions is not None and (not data_positions or
            not data_positions <= set(range(1, len(positions) - 1, 2))):
        raise SafetyError("Restore archive positions are absent or incomplete")
    if not allow_tail and (tape.has_partial() or len(positions) % 2 == 0):
        raise SafetyError("Uncommitted/incomplete tape tail; append forbidden")
    previous = sha256(tape.read(0))
    found = []
    seen: set[str] = set()
    end = len(positions) - 1 if data_positions is None else max(data_positions) + 1
    for position in range(1, end, 2):
        # Read data then its receipt, in physical order. Do not seek past a
        # large data file just to obtain the expected hash before reading it.
        selected = data_positions is None or position in data_positions
        if selected:
            with tape.open_read(position) as incoming:
                manifest, checksum, size = inspect_stream(incoming, payload_handler=payload_handler)
        receipt_path = tape.read(position + 1)
        receipt = read_metadata(receipt_path, "receipt.json")
        if (receipt.get("format") != FORMAT or receipt.get("media_id") != expected_media
                or receipt.get("tape_file") != position or receipt.get("previous") != previous):
            raise SafetyError(f"Receipt mismatch at tape file {position}")
        archive_id = receipt.get("archive_id")
        if not isinstance(archive_id, str) or archive_id in seen:
            raise SafetyError("Invalid or duplicate receipt archive identity")
        uuid.UUID(archive_id)
        seen.add(archive_id)
        previous = sha256(receipt_path)
        if not selected:
            continue
        if checksum != receipt["sha256"] or size != receipt["bytes"]:
            raise SafetyError("Full tape readback SHA-256/byte count mismatch")
        if manifest["media_id"] != expected_media or manifest["archive_id"] != archive_id:
            raise SafetyError("Archive identity mismatch or duplicate")
        found.append({"manifest": manifest, "receipt": receipt, "position": position})
    return found


def inspect_catalogued_media(catalog: Catalog, tape: Tape, media: str) -> list[dict[str, Any]]:
    """Check physical append safety without re-verifying previously verified data.

    Exact header, EOD/count, pending state and every receipt must agree with
    the VERIFIED catalog. This is not an integrity scrub of old payloads.
    Unknown or unverified archives require an explicit full verification.
    """
    header = tape.header()
    known = catalog.db.execute("SELECT header_json FROM media WHERE id=?", (media,)).fetchone()
    if header["media_id"] != media or known is None or json.loads(known[0]) != header:
        raise SafetyError("Wrong medium inserted")
    positions = tape.positions()
    if tape.has_partial() or len(positions) % 2 == 0:
        raise SafetyError("Uncommitted/incomplete tape tail; append forbidden")
    rows = list(catalog.db.execute("SELECT * FROM archives WHERE media_id=? ORDER BY tape_file", (media,)))
    if [row["tape_file"] for row in rows] != list(range(1, len(positions) - 1, 2)):
        raise SafetyError("Physical sequence differs from catalog; full verification required")
    previous = sha256(tape.read(0))
    result = []
    for row in rows:
        position = row["tape_file"]
        if row["state"] != "VERIFIED":
            raise SafetyError("Unverified catalog archive; full verification required")
        path = tape.read(position + 1)
        receipt = read_metadata(path, "receipt.json")
        if (receipt.get("format") != FORMAT or receipt.get("previous") != previous
                or any(receipt.get(key) != row[key] for key in
                       ("media_id", "tape_file", "bytes", "sha256"))
                or receipt.get("archive_id") != row["id"]):
            raise SafetyError("Physical receipt differs from verified catalog")
        manifest = json.loads(row["manifest_json"])
        if manifest["media_id"] != media or manifest["archive_id"] != row["id"]:
            raise SafetyError("Invalid catalog manifest identity")
        result.append({"manifest": manifest, "receipt": receipt, "position": position})
        previous = sha256(path)
    return result


class ArchiveService:
    def __init__(self, catalog: Catalog, tape: Tape):
        self.catalog = catalog
        self.tape = tape

    def register(self) -> dict[str, Any]:
        with io_lock(), self.tape.locked():
            header = self.tape.header()
            self.catalog.register(header, self.tape.used())
            return header

    def _identity(self, expected: str) -> dict[str, Any]:
        header = self.tape.header()
        row = self.catalog.db.execute("SELECT * FROM media WHERE id=?", (expected,)).fetchone()
        if header["media_id"] != expected or row is None or json.loads(row["header_json"]) != header:
            raise SafetyError("Media identity is unknown or differs from catalog")
        return dict(row)

    def _failed_used(self, job: str, media: str) -> int:
        """A broken drive must not prevent durable recording of the original error."""
        try:
            return self.tape.used()
        except Exception as error:
            self.catalog.event(job, "capacity_unknown_after_failure", error=str(error))
            # Conservatively reserve the entire medium until independent inspection.
            return self.catalog.db.execute("SELECT capacity FROM media WHERE id=?", (media,)).fetchone()[0]

    def plan(self, source: Path, media: str, target: int = 75_000_000_000,
             selected: list[str] | None = None, verify_mode: str = "archive",
             expected: list[dict[str, Any]] | None = None,
             excluded: list[str] | None = None) -> dict[str, Any]:
        if verify_mode not in ("archive", "media"):
            raise SafetyError("Unknown verification mode")
        root = source.resolve()
        if self.catalog.path.is_relative_to(root):
            raise SafetyError("Catalog must be outside source tree")
        tape_path = getattr(self.tape, "path", None)
        if tape_path is not None and (tape_path.is_relative_to(root) or root.is_relative_to(tape_path)):
            raise SafetyError("Source and simulator medium must be separate")
        with io_lock(), self.tape.locked():
            record = self._identity(media)
            if record["state"] not in ("READY", "IN_USE"):
                raise SafetyError("Medium is not writable")
            if self.tape.header().get("backend") == "physical":
                inspect_catalogued_media(self.catalog, self.tape, media)
            else:
                scan(self.tape, media)
            return self._plan_inventory(root, media, target, selected, verify_mode,
                                        record["capacity"] * 95 // 100 - self.tape.used(),
                                        len(self.tape.positions()), expected=expected, excluded=excluded)

    def plan_catalogued(self, source: Path, media: str, target: int = 75_000_000_000,
                        selected: list[str] | None = None, verify_mode: str = "archive",
                        expected: list[dict[str, Any]] | None = None,
             excluded: list[str] | None = None) -> dict[str, Any]:
        """Advisory physical plan without opening or positioning any tape device."""
        from .planning import catalogue_snapshot
        if verify_mode not in ("archive", "media") or target <= 0:
            raise SafetyError("Unknown planning options")
        root = source.resolve()
        if self.catalog.path.is_relative_to(root):
            raise SafetyError("Catalog must be outside source tree")
        with io_lock():
            snapshot = catalogue_snapshot(self.catalog, media)
            return self._plan_inventory(root, media, target, selected, verify_mode,
                                        snapshot["record"]["capacity"] * 95 // 100 - snapshot["used"],
                                        snapshot["expected_tape_files"], catalogue_only=True, expected=expected, excluded=excluded)

    def _plan_inventory(self, root: Path, media: str, target: int, selected: list[str] | None,
                        verify_mode: str, available: int, expected_tape_files: int,
                        *, catalogue_only: bool = False, expected: list[dict[str, Any]] | None = None,
             excluded: list[str] | None = None) -> dict[str, Any]:
        job = self.catalog.job("archive", media, "PLANNING")
        with self.catalog.db:
            self.catalog.db.execute("UPDATE jobs SET phase='INVENTORY' WHERE id=?", (job,))
        self.catalog.event(job, "job_phase", phase="INVENTORY")
        try:
            expected = expected if expected is not None else inventory(root, selected, metadata_only=True, excluded=excluded)
            preflight = plan_archives(estimate_entries(expected), media, target)
            if any(len(encode(m)) > MAX_META for m in preflight):
                raise SafetyError("Manifest exceeds limit; reduce archive target size")
            if sum(estimate(m['files']) + 10240 for m in preflight) > available:
                raise SafetyError("Plan exceeds conservative capacity; select additional media before hashing")
            entries = inventory(root, selected, expected=expected, excluded=excluded)
            manifests = plan_archives(entries, media, target)
            if any(len(encode(m)) > MAX_META for m in manifests):
                raise SafetyError("Manifest exceeds limit; reduce archive target size")
            required = sum(estimate(m["files"]) + 10240 for m in manifests)
            if required > available:
                raise SafetyError("Plan exceeds conservative capacity; use another medium or smaller selection")
            plan = {"media_id": media, "source": str(root), "archives": manifests,
                    "required_estimate": required, "available": available,
                    "payload_bytes": sum(e["size"] for e in entries), "file_count": len(entries),
                    "expected_tape_files": expected_tape_files}
            if selected is not None:
                plan["selected_paths"] = sorted(set(selected))
            if excluded is not None:
                plan["excluded_paths"] = sorted(set(excluded))
            plan["verify_mode"] = verify_mode
            if catalogue_only:
                plan["planning_basis"] = "catalogue; physical preflight required before write"
            plan_hash = hashlib.sha256(encode(plan)).hexdigest()
            plan["sha256"] = plan_hash
            with self.catalog.db:
                self.catalog.db.execute("UPDATE jobs SET state='PLANNED',plan_json=?,updated=? WHERE id=?",
                                        (encode(plan).decode(), time.time(), job))
            self._load_plan(job)  # Persist INVENTORY for each planned archive, including migrated catalogs.
            self.catalog.event(job, "plan_ready", sha256=plan_hash, files=len(entries), bytes=plan["payload_bytes"])
            return {"job_id": job, **plan}
        except BaseException as error:
            self.catalog.finish(job, "FAILED", str(error))
            raise

    def _load_plan(self, job: str) -> tuple[dict[str, Any], dict[str, Any]]:
        row = self.catalog.db.execute("SELECT * FROM jobs WHERE id=? AND kind='archive'", (job,)).fetchone()
        if row is None:
            raise SafetyError("Unknown archive job")
        plan = json.loads(row["plan_json"])
        checksum = plan.pop("sha256")
        if hashlib.sha256(encode(plan)).hexdigest() != checksum:
            raise SafetyError("Stored plan has changed")
        with self.catalog.db:
            for manifest in plan["archives"]:
                self.catalog.db.execute("""INSERT OR IGNORE INTO staged_archives
                    (job_id,archive_id,phase,state,total_bytes,updated) VALUES(?,?,'INVENTORY','COMPLETE',?,?)""",
                    (job, manifest["archive_id"], sum(e["size"] for e in manifest["files"]), time.time()))
        return dict(row), plan

    def _store(self, job: str, plan: dict[str, Any], spool: Path) -> StagingStore:
        spool = spool.resolve()
        source = Path(plan["source"])
        if spool.is_relative_to(source) or source.is_relative_to(spool):
            raise SafetyError("Staging and source must be separate")
        if self.catalog.path.is_relative_to(spool):
            raise SafetyError("Staging must not contain the catalog")
        medium = getattr(self.tape, "path", None)
        if medium is not None and (spool.is_relative_to(medium) or medium.is_relative_to(spool)):
            raise SafetyError("Staging and medium must be separate")
        roots = self.catalog.db.execute("SELECT DISTINCT root FROM staged_archives WHERE job_id=? AND root IS NOT NULL", (job,)).fetchall()
        if any(row[0] != str(spool) for row in roots):
            raise SafetyError("Use the original staging root to resume this job")
        return StagingStore(self.catalog, spool)

    def stage(self, job: str, spool: Path, *, revalidate_ready: bool = False) -> dict[str, Any]:
        """Prepare the entire plan without accessing the tape or requiring source later."""
        with io_lock():
            row, plan = self._load_plan(job)
            if row["state"] not in ("PLANNED", "STAGED", "FAILED", "INTERRUPTED"):
                raise SafetyError("Job cannot enter staging in its current state")
            attempted = self.catalog.db.execute("SELECT 1 FROM staged_archives WHERE job_id=? AND phase IN ('TAPE_WRITE','TAPE_READBACK','VERIFIED','STAGING_CLEANUP')", (job,)).fetchone()
            attempted_archive = self.catalog.db.execute("SELECT 1 FROM archives WHERE job_id=?", (job,)).fetchone()
            if attempted or attempted_archive:
                raise SafetyError("Tape was already attempted; use explicit backup --resume after media inspection")
            store = self._store(job, plan, spool)
            missing = [m for m in plan["archives"] if store.row(job, m["archive_id"])["sha256"] is None]
            store.require_space(sum(estimate(m["files"]) + 10240 for m in missing))
            with self.catalog.db:
                self.catalog.db.execute("UPDATE jobs SET state='RUNNING',phase='STAGING',updated=? WHERE id=?", (time.time(), job))
            try:
                for manifest in plan["archives"]:
                    if revalidate_ready and store.row(job, manifest["archive_id"])["fingerprint_json"]:
                        store.revalidate_ready(job, manifest)
                    store.prepare(job, Path(plan["source"]), manifest)
                report = {"job_id": job, "state": "STAGED", "archives": len(plan["archives"]), "staging": str(store.root)}
                self.catalog.finish(job, "STAGED", report=report)
                return report
            except BaseException as error:
                self.catalog.finish(job, "INTERRUPTED" if isinstance(error, (KeyboardInterrupt, SystemExit)) else "FAILED", str(error))
                raise

    def _progress(self, job: str, archive: str, phase: str, total: int):
        last = time.monotonic()
        started = last
        last_done = -1
        def report(value: int | dict[str, Any]) -> None:
            nonlocal last, last_done
            data = value if isinstance(value, dict) else {"bytes": value}
            now = time.monotonic()
            done = data["bytes"]
            if (now - last < 1 and done != total) or done == last_done:
                return
            with self.catalog.db:
                self.catalog.db.execute("UPDATE staged_archives SET progress_bytes=?,total_bytes=?,updated=? WHERE job_id=? AND archive_id=?",
                                        (done, total, time.time(), job, archive))
            data = {**data, "bytes_per_second": data.get("bytes_per_second", done / max(now - started, 1e-9))}
            self.catalog.event(job, "io_progress", archive=archive, phase=phase, total_bytes=total, **data)
            last, last_done = now, done
        return report

    def backup(self, job: str, confirmation: str, spool: Path, *, resume: bool = False,
               prepare_all: bool = False) -> dict[str, Any]:
        if confirmation != job:
            raise SafetyError("Explicit confirmation must equal the reviewed job ID")
        with io_lock(), self.tape.locked():
            row, plan = self._load_plan(job)
            permitted = ("PLANNED", "STAGED", "FAILED", "INTERRUPTED") if resume else ("PLANNED", "STAGED")
            if row["state"] not in permitted:
                raise SafetyError("Job requires a reviewed unexecuted plan or explicit --resume")
            media = plan["media_id"]
            record = self._identity(media)
            if record["state"] not in (("READY", "IN_USE", "SUSPECT") if resume else ("READY", "IN_USE")):
                raise SafetyError("Medium is not writable")
            # Never resume from catalog positions. Re-read the physical sequence and all receipts.
            found = (inspect_catalogued_media(self.catalog, self.tape, media)
                     if self.tape.header().get("backend") == "physical" and not resume
                     else scan(self.tape, media))
            initial = plan["expected_tape_files"]
            committed = [item for item in found if item["position"] >= initial]
            if not resume and committed:
                raise SafetyError("Medium changed since planning; review a new plan")
            if len(self.tape.positions()) != initial + 2 * len(committed) or len(committed) > len(plan["archives"]):
                raise SafetyError("Medium changed since planning")
            for item, expected in zip(committed, plan["archives"]):
                if item["manifest"] != expected:
                    raise SafetyError("Unexpected archive on medium; resume refused")
                staged = self.catalog.db.execute("SELECT sha256 FROM staged_archives WHERE job_id=? AND archive_id=?", (job, expected["archive_id"])).fetchone()
                if staged[0] != item["receipt"]["sha256"]:
                    raise SafetyError("Read-back archive differs from original staged TAR")
            store = self._store(job, plan, spool)
            if self.tape.header().get("backend") != "simulator":
                require_qualification(self.catalog, store.root)
            todo = plan["archives"][len(committed):]
            if plan.get("verify_mode", "archive") == "media":
                return self._backup_media_batch(job, plan, store, committed, todo,
                                                media, record, initial)
            needed = [estimate(m["files"]) + 10240 for m in todo
                      if not (Path(store.row(job, m["archive_id"])["path"] or "").is_file()
                              and store.row(job, m["archive_id"])["sha256"])]
            store.require_space(sum(needed) if prepare_all else max(needed, default=10240))
            with self.catalog.db:
                self.catalog.db.execute("UPDATE jobs SET state='RUNNING',updated=? WHERE id=?", (time.time(), job))
            self.catalog.event(job, "confirmed", resume=resume, staging=str(store.root))
            completed = []
            tape_attempted = False
            current = None
            try:
                for item in committed:
                    manifest, receipt = item["manifest"], item["receipt"]
                    self.catalog.record_archive(manifest, job, item["position"], "VERIFIED", receipt["bytes"], receipt["sha256"])
                    with self.catalog.db:
                        self.catalog.db.execute("INSERT INTO verifications VALUES(?,?,?,?,?,?)",
                            (str(uuid.uuid4()), job, manifest["archive_id"], time.time(), "VERIFIED", None))
                    store.phase(job, manifest["archive_id"], "VERIFIED", "COMPLETE")
                    store.cleanup(job, manifest["archive_id"])
                    completed.append(manifest["archive_id"])
                if prepare_all:
                    for manifest in todo:
                        current = manifest["archive_id"]
                        store.prepare(job, Path(plan["source"]), manifest)
                for manifest in todo:
                    archive = manifest["archive_id"]
                    current = archive
                    data = store.prepare(job, Path(plan["source"]), manifest)
                    # Locality, identity, readonly mode, full hash and TAR consistency are rechecked immediately before write.
                    data = store.validate_ready(job, manifest)
                    ready = store.row(job, archive)
                    data_hash, size = ready["sha256"], ready["bytes"]
                    if self.tape.used() + size + 10240 > record["capacity"] * 95 // 100:
                        raise SafetyError("Insufficient remaining capacity for complete archive and receipt")
                    position = len(self.tape.positions())
                    previous = sha256(self.tape.read(position - 1))
                    self.catalog.record_archive(manifest, job, position, "WRITING", size, data_hash)
                    store.phase(job, archive, "TAPE_WRITE", progress_bytes=0, total_bytes=size)
                    with self.catalog.db:
                        self.catalog.db.execute("UPDATE media SET state='IN_USE',first_use=coalesce(first_use,?),last_use=? WHERE id=?",
                                                (time.time(), time.time(), media))
                    tape_attempted = True
                    self.tape.set_monitor(self._progress(job, archive, "TAPE_WRITE", size))
                    try:
                        if self.tape.append(data, media) != position:
                            raise SafetyError("Tape position changed unexpectedly")
                    finally:
                        self.tape.set_monitor(None)
                    # Staged TAR remains intact throughout readback; no second large local file.
                    store.phase(job, archive, "TAPE_READBACK", progress_bytes=0, total_bytes=size)
                    with self.tape.open_read(position) as incoming:
                        verify_stream(incoming, data_hash, size, manifest,
                                      self._progress(job, archive, "TAPE_READBACK", size))
                    store.validate_ready(job, manifest)
                    receipt = {"format": FORMAT, "media_id": media, "archive_id": archive,
                               "tape_file": position, "bytes": size, "sha256": data_hash,
                               "previous": previous, "verified_at": time.time()}
                    receipt_path = store.metadata_path(job, archive)
                    metadata_tar(receipt_path, "receipt.json", receipt)
                    receipt_path.chmod(0o400)
                    receipt_hash = sha256(receipt_path)
                    receipt_position = self.tape.append(receipt_path, media)
                    if (receipt_position != position + 1
                            or sha256(self.tape.read(receipt_position)) != receipt_hash
                            or read_metadata(self.tape.read(receipt_position), "receipt.json") != receipt):
                        raise SafetyError("Receipt readback mismatch")
                    self.catalog.record_archive(manifest, job, position, "VERIFIED", size, data_hash)
                    with self.catalog.db:
                        self.catalog.db.execute("INSERT INTO verifications VALUES(?,?,?,?,?,?)",
                            (str(uuid.uuid4()), job, archive, time.time(), "VERIFIED", None))
                        self.catalog.db.execute("UPDATE media SET used=?,writes=writes+1,last_verified=? WHERE id=?",
                                                (self.tape.used(), time.time(), media))
                    store.phase(job, archive, "VERIFIED", "COMPLETE")
                    completed.append(archive)
                    store.cleanup(job, archive)
                with self.catalog.db:
                    self.catalog.db.execute("""UPDATE media SET state='IN_USE',used=?,last_verified=?,
                        writes=max(writes,(SELECT count(*) FROM archives WHERE media_id=? AND state='VERIFIED')) WHERE id=?""",
                        (self.tape.used(), time.time(), media, media))
                report = {"job_id": job, "state": "VERIFIED", "archives": completed,
                          "files": plan["file_count"], "payload_bytes": plan["payload_bytes"]}
                self.catalog.finish(job, "VERIFIED", report=report)
                return report
            except BaseException as error:
                used_after_failure = self._failed_used(job, media) if tape_attempted else None
                with self.catalog.db:
                    self.catalog.db.execute("UPDATE archives SET state='INCOMPLETE' WHERE job_id=? AND state='WRITING'", (job,))
                    if tape_attempted:
                        self.catalog.db.execute("UPDATE media SET state='SUSPECT',used=? WHERE id=?", (used_after_failure, media))
                if current:
                    state = "INTERRUPTED" if isinstance(error, (KeyboardInterrupt, SystemExit)) else "FAILED"
                    store.phase(job, current, store.row(job, current)["phase"], state, str(error))
                self.catalog.finish(job, "INTERRUPTED" if isinstance(error, (KeyboardInterrupt, SystemExit)) else "FAILED",
                                    str(error), {"verified_archives": completed, "staging_retained": True})
                raise

    def _backup_media_batch(self, job: str, plan: dict[str, Any], store: StagingStore,
                            committed: list[dict[str, Any]], todo: list[dict[str, Any]],
                            media: str, record: dict[str, Any], initial: int) -> dict[str, Any]:
        """Write a complete medium segment, then read it all before any success claim.

        Receipts carry expected checksums but no verified_at until an independent
        full scan has established integrity. A crash leaves no falsely VERIFIED DB
        rows; recovery scans and hashes the physical sequence before promotion.
        """
        missing = []
        for manifest in todo:
            row = store.row(job, manifest["archive_id"])
            if not (row["sha256"] and row["fingerprint_json"]
                    and Path(row["path"] or "").is_file()):
                missing.append(estimate(manifest["files"]) + 10240)
        store.require_space(sum(missing))
        with self.catalog.db:
            self.catalog.db.execute("UPDATE jobs SET state='RUNNING',phase='STAGING',updated=? WHERE id=?",
                                    (time.time(), job))
        self.catalog.event(job, "confirmed", verification="media", staging=str(store.root))
        attempted = False
        current: str | None = None
        try:
            for manifest in todo:
                current = manifest["archive_id"]
                store.prepare(job, Path(plan["source"]), manifest)
            for manifest in todo:
                current = manifest["archive_id"]
                archive = current
                data = store.validate_ready(job, manifest)
                ready = store.row(job, archive)
                data_hash, size = ready["sha256"], ready["bytes"]
                if self.tape.used() + size + 10240 > record["capacity"] * 95 // 100:
                    raise SafetyError("Insufficient remaining capacity for complete archive and receipt")
                position = len(self.tape.positions())
                previous = sha256(self.tape.read(position - 1))
                self.catalog.record_archive(manifest, job, position, "WRITING", size, data_hash)
                store.phase(job, archive, "TAPE_WRITE", progress_bytes=0, total_bytes=size)
                with self.catalog.db:
                    self.catalog.db.execute("UPDATE media SET state='IN_USE',first_use=coalesce(first_use,?),last_use=? WHERE id=?",
                                            (time.time(), time.time(), media))
                attempted = True
                self.tape.set_monitor(self._progress(job, archive, "TAPE_WRITE", size))
                try:
                    if self.tape.append(data, media) != position:
                        raise SafetyError("Tape position changed unexpectedly")
                finally:
                    self.tape.set_monitor(None)
                receipt = {"format": FORMAT, "media_id": media, "archive_id": archive,
                           "tape_file": position, "bytes": size, "sha256": data_hash,
                           "previous": previous, "verification": "pending_readback",
                           "written_at": time.time()}
                receipt_path = store.metadata_path(job, archive)
                metadata_tar(receipt_path, "receipt.json", receipt)
                receipt_path.chmod(0o400)
                if self.tape.append(receipt_path, media) != position + 1:
                    raise SafetyError("Receipt position changed unexpectedly")
                store.phase(job, archive, "TAPE_READBACK", "PENDING", progress_bytes=0,
                            total_bytes=size)
            # This is the only point where deferred archives become eligible for
            # VERIFIED. Read every byte of this job's archives and validate the
            # receipt chain. Previously VERIFIED payloads need no repeated scrub.
            selected_positions = ({initial + 2 * index for index in range(len(plan["archives"]))}
                                  if self.tape.header().get("backend") == "physical" else None)
            found = [item for item in scan(self.tape, media, data_positions=selected_positions)
                     if item["position"] >= initial]
            if len(found) != len(plan["archives"]):
                raise SafetyError("Media batch has incomplete archive sequence")
            for item, manifest in zip(found, plan["archives"]):
                if item["manifest"] != manifest:
                    raise SafetyError("Media batch manifest mismatch")
                row = store.row(job, manifest["archive_id"])
                if item["receipt"]["sha256"] != row["sha256"]:
                    raise SafetyError("Media batch differs from staged TAR")
                archived = self.catalog.db.execute(
                    "SELECT state,sha256 FROM archives WHERE id=? AND job_id=?",
                    (manifest["archive_id"], job),
                ).fetchone()
                if Path(row["path"] or "").is_file():
                    store.validate_ready(job, manifest)
                elif (archived is None or archived["state"] != "VERIFIED"
                      or archived["sha256"] != row["sha256"]):
                    raise SafetyError("Verified staging artifact is missing")
            completed = []
            newly_verified = 0
            for item in found:
                manifest, receipt = item["manifest"], item["receipt"]
                current = manifest["archive_id"]
                prior = self.catalog.db.execute(
                    "SELECT state,sha256 FROM archives WHERE id=? AND job_id=?",
                    (current, job),
                ).fetchone()
                if prior is not None and prior["state"] == "VERIFIED":
                    if prior["sha256"] != receipt["sha256"]:
                        raise SafetyError("Previously verified archive changed")
                    stage_row = store.row(job, current)
                    if (stage_row["phase"] != "STAGING_CLEANUP"
                            or stage_row["state"] != "COMPLETE"):
                        store.cleanup(job, current)
                    completed.append(current)
                    continue
                self.catalog.record_archive(manifest, job, item["position"], "VERIFIED",
                                            receipt["bytes"], receipt["sha256"])
                with self.catalog.db:
                    self.catalog.db.execute("INSERT INTO verifications VALUES(?,?,?,?,?,?)",
                        (str(uuid.uuid4()), job, current, time.time(), "VERIFIED", None))
                store.phase(job, current, "VERIFIED", "COMPLETE")
                store.cleanup(job, current)
                completed.append(current)
                newly_verified += 1
            with self.catalog.db:
                self.catalog.db.execute("UPDATE media SET state='IN_USE',used=?,last_verified=?,writes=writes+? WHERE id=?",
                                        (self.tape.used(), time.time(), newly_verified, media))
            report = {"job_id": job, "state": "VERIFIED", "archives": completed,
                      "files": plan["file_count"], "payload_bytes": plan["payload_bytes"],
                      "verification": "media"}
            self.catalog.finish(job, "VERIFIED", report=report)
            return report
        except BaseException as error:
            used_after_failure = self._failed_used(job, media) if attempted else None
            with self.catalog.db:
                self.catalog.db.execute("UPDATE archives SET state='INCOMPLETE' WHERE job_id=? AND state='WRITING'", (job,))
                if attempted:
                    self.catalog.db.execute("UPDATE media SET state='SUSPECT',used=? WHERE id=?",
                                            (used_after_failure, media))
            if current:
                row = store.row(job, current)
                store.phase(job, current, row["phase"],
                            "INTERRUPTED" if isinstance(error, (KeyboardInterrupt, SystemExit)) else "FAILED",
                            str(error))
            self.catalog.finish(job, "INTERRUPTED" if isinstance(error, (KeyboardInterrupt, SystemExit)) else "FAILED",
                                str(error), {"staging_retained": True, "verification": "media"})
            raise

    def verify(self, media: str) -> dict[str, Any]:
        with io_lock(), self.tape.locked():
            self._identity(media)
            job = self.catalog.job("verify", media)
            try:
                found = scan(self.tape, media)
                for item in found:
                    receipt = item["receipt"]
                    self.catalog.record_archive(item["manifest"], job, item["position"], "VERIFIED",
                                                receipt["bytes"], receipt["sha256"])
                with self.catalog.db:
                    for item in found:
                        self.catalog.db.execute("INSERT INTO verifications VALUES(?,?,?,?,?,?)",
                            (str(uuid.uuid4()), job, item["manifest"]["archive_id"], time.time(), "VERIFIED", None))
                    self.catalog.db.execute("UPDATE media SET last_verified=?,used=? WHERE id=?",
                                            (time.time(), self.tape.used(), media))
                report = {"job_id": job, "state": "VERIFIED", "archives": len(found)}
                self.catalog.finish(job, "VERIFIED", report=report)
                return report
            except BaseException as error:
                with self.catalog.db:
                    self.catalog.db.execute("UPDATE archives SET state='SUSPECT' WHERE media_id=?", (media,))
                    self.catalog.db.execute("UPDATE media SET state='SUSPECT' WHERE id=?", (media,))
                    self.catalog.db.execute("INSERT INTO verifications VALUES(?,?,?,?,?,?)",
                        (str(uuid.uuid4()), job, None, time.time(), "FAILED", str(error)))
                self.catalog.finish(job, "FAILED", str(error))
                raise

    def rebuild(self, media: str) -> dict[str, Any]:
        with io_lock(), self.tape.locked():
            header = self.tape.header()
            if header["media_id"] != media:
                raise SafetyError("Wrong medium inserted")
            self.catalog.register(header, self.tape.used())
            job = self.catalog.job("rebuild", media)
            try:
                found = scan(self.tape, media, allow_tail=True)
                # Single transaction publishes the fully validated scan.
                with self.catalog.db:
                    for item in found:
                        receipt = item["receipt"]
                        self.catalog.record_archive(item["manifest"], job, item["position"], "VERIFIED",
                                                    receipt["bytes"], receipt["sha256"], transaction=False)
                    tail = self.tape.has_partial() or len(self.tape.positions()) % 2 == 0
                    self.catalog.db.execute("UPDATE media SET state=CASE WHEN ? THEN 'SUSPECT' ELSE state END,used=? WHERE id=?",
                                            (tail, self.tape.used(), media))
                report = {"job_id": job, "archives": len(found), "incomplete_tail": tail}
                self.catalog.finish(job, "VERIFIED", report=report)
                return report
            except BaseException as error:
                self.catalog.finish(job, "FAILED", str(error))
                raise

    def restore_plan(self, media: str, paths: list[str] | None = None,
                     archive_id: str | None = None) -> dict[str, Any]:
        rows = self.catalog.search()
        selected = [r for r in rows if r["media_id"] == media and r["state"] == "VERIFIED"
                    and (archive_id is None or r["archive_id"] == archive_id)
                    and (not paths or any(r["path"] == p or r["path"].startswith(p.rstrip("/") + "/") for p in paths))]
        if not selected:
            raise SafetyError("No verified files match restore selection")
        if paths and any(not any(r["path"] == p or r["path"].startswith(p.rstrip("/") + "/")
                                 for r in selected) for p in paths):
            raise SafetyError("At least one requested restore path is missing")
        names = [r["path"] for r in selected]
        if len(set(names)) != len(names):
            raise SafetyError("Multiple versions have the same path; choose one archive explicitly")
        return {"media_id": media, "media_count": 1, "tape_files": sorted({r["tape_file"] for r in selected}),
                "payload_bytes": sum(r["size"] for r in selected), "files": selected}

    def restore(self, media: str, target: Path, paths: list[str] | None = None,
                archive_id: str | None = None) -> dict[str, Any]:
        with io_lock(), self.tape.locked():
            self._identity(media)
            target_path = Path(os.path.abspath(target))
            tape_path = getattr(self.tape, "path", None)
            if tape_path is not None and (target_path.is_relative_to(tape_path)
                                          or tape_path.is_relative_to(target_path)):
                raise SafetyError("Restore target must be separate from simulator medium")
            if self.catalog.path.is_relative_to(target_path):
                raise SafetyError("Restore target must not contain the catalog")
            plan = self.restore_plan(media, paths, archive_id)
            job = self.catalog.job("restore", media)
            with self.catalog.db:
                self.catalog.db.execute("INSERT INTO restores VALUES(?,?,?,?,?)",
                                        (str(uuid.uuid4()), job, str(target.absolute()), encode(plan).decode(), "RUNNING"))
            try:
                pending = PendingRestore(target, plan["files"])
                try:
                    # Verify selected TARs and their receipt chain, extracting
                    # privately in one pass. Unselected payloads are not read.
                    scan(self.tape, media, allow_tail=True, payload_handler=pending.consume,
                         data_positions=set(plan["tape_files"]))
                    count = pending.publish()
                finally:
                    pending.close()
                with self.catalog.db:
                    self.catalog.db.execute("UPDATE restores SET state='VERIFIED' WHERE job_id=?", (job,))
                report = {"job_id": job, "state": "VERIFIED", "files": count, "target": str(target.absolute())}
                self.catalog.finish(job, "VERIFIED", report=report)
                return report
            except BaseException as error:
                with self.catalog.db:
                    self.catalog.db.execute("UPDATE restores SET state='FAILED' WHERE job_id=?", (job,))
                self.catalog.finish(job, "FAILED", str(error))
                raise

    def recover_jobs(self, media: str) -> int:
        with io_lock(), self.tape.locked():
            self._identity(media)
            return self.catalog.interrupt_unfinished(media)
