"""Persistent owned staging artifacts; ready files survive every failed tape job."""
from __future__ import annotations

import json
import os
import stat
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from .archive import create_archive, estimate, verify_archive
from .catalog import Catalog
from .common import SafetyError, encode, sha256, sync_dir
from .storage import require_local


def fingerprint(path: Path) -> list[int]:
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise SafetyError("Staging artifact must be an unlinked regular file")
    return [info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns]


class StagingStore:
    def __init__(self, catalog: Catalog, root: Path):
        self.catalog = catalog
        self.root = root.resolve()
        ancestor = self.root
        while not ancestor.exists():
            ancestor = ancestor.parent
        require_local(ancestor)
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.storage = require_local(self.root)

    def row(self, job: str, archive: str) -> dict[str, Any]:
        row = self.catalog.db.execute("SELECT * FROM staged_archives WHERE job_id=? AND archive_id=?",
                                      (job, archive)).fetchone()
        if row is None:
            raise SafetyError("Missing persistent staging record")
        return dict(row)

    def phase(self, job: str, archive: str, phase: str, state: str = "RUNNING",
              error: str | None = None, **values: Any) -> None:
        permitted = {"path", "sha256", "bytes", "fingerprint_json", "progress_bytes", "total_bytes", "root"}
        if not values.keys() <= permitted:
            raise ValueError("Unknown staging field")
        assignments = ",".join(f"{key}=?" for key in values)
        with self.catalog.db:
            self.catalog.db.execute(f"UPDATE staged_archives SET phase=?,state=?,updated=?,error=?"
                + ("," + assignments if assignments else "") + " WHERE job_id=? AND archive_id=?",
                (phase, state, time.time(), error, *values.values(), job, archive))
        with self.catalog.db:
            self.catalog.db.execute("UPDATE jobs SET phase=?,updated=? WHERE id=?", (phase, time.time(), job))
        self.catalog.event(job, "archive_phase", archive=archive, phase=phase, state=state, error=error)

    def directory(self, job: str, archive: str) -> Path:
        uuid.UUID(job)
        uuid.UUID(archive)
        row = self.row(job, archive)
        if row["root"] is not None and row["root"] != str(self.root):
            raise SafetyError("Job is bound to a different staging root")
        directory = self.root / f"otam-{job}" / archive
        parent = directory.parent
        parent.mkdir(mode=0o700, exist_ok=True)
        if parent.is_symlink() or parent.resolve().parent != self.root:
            raise SafetyError("Unsafe staging job directory")
        owner = {"format": "otam-staging-v1", "job_id": job, "archive_id": archive}
        if not directory.exists():
            directory.mkdir(mode=0o700)
            with (directory / "owner.json").open("xb") as stream:
                stream.write(encode(owner))
                stream.flush()
                os.fsync(stream.fileno())
            sync_dir(directory)
            sync_dir(parent)
        if directory.is_symlink() or directory.resolve().parent != parent:
            raise SafetyError("Unsafe staging archive directory")
        marker = directory / "owner.json"
        if marker.is_symlink() or json.loads(marker.read_bytes()) != owner:
            raise SafetyError("Staging ownership mismatch")
        with self.catalog.db:
            self.catalog.db.execute("UPDATE staged_archives SET root=? WHERE job_id=? AND archive_id=?",
                                    (str(self.root), job, archive))
        return directory

    def track(self, job: str, archive: str, path: Path) -> None:
        info = fingerprint(path)
        with self.catalog.db:
            self.catalog.db.execute("INSERT INTO staging_artifacts VALUES(?,?,?,?,?)",
                                    (job, archive, path.name, info[0], info[1]))

    def require_space(self, required: int) -> None:
        info = require_local(self.root)
        if info["free"] < required:
            raise SafetyError(f"Insufficient local staging space: need {required}, available {info['free']}")

    def validate_ready(self, job: str, manifest: dict[str, Any]) -> Path:
        archive = manifest["archive_id"]
        directory = self.directory(job, archive)
        row = self.row(job, archive)
        path = directory / "ready.tar"
        if row["path"] != str(path) or not row["sha256"] or row["fingerprint_json"] is None:
            raise SafetyError("Archive has no completed staging validation")
        require_local(path)
        before = fingerprint(path)
        if before != json.loads(row["fingerprint_json"]) or path.stat().st_mode & 0o222:
            raise SafetyError("Prepared archive changed or is writable")
        if sha256(path) != row["sha256"]:
            raise SafetyError("Prepared TAR checksum changed")
        verify_archive(path, manifest)
        if fingerprint(path) != before:
            raise SafetyError("Prepared TAR changed during validation")
        return path

    def revalidate_ready(self, job: str, manifest: dict[str, Any]) -> None:
        """Explicitly recertify metadata-only changes; never accept changed content/identity."""
        archive = manifest["archive_id"]
        directory = self.directory(job, archive)
        row = self.row(job, archive)
        path = directory / "ready.tar"
        if row["path"] != str(path) or not row["sha256"] or not row["fingerprint_json"]:
            raise SafetyError("No previously validated READY archive to recertify")
        previous = json.loads(row["fingerprint_json"])
        before = fingerprint(path)
        if before[:4] != previous[:4] or path.stat().st_mode & 0o222:
            raise SafetyError("Recertification requires unchanged identity, size, mtime and read-only mode")
        require_local(path)
        if sha256(path) != row["sha256"]:
            raise SafetyError("Recertification refused: original TAR checksum differs")
        verify_archive(path, manifest)
        if fingerprint(path) != before:
            raise SafetyError("Archive changed during explicit recertification")
        self.phase(job, archive, "READY", "COMPLETE", fingerprint_json=encode(before).decode())
        self.catalog.event(job, "staging_explicitly_revalidated", archive=archive,
                           original_sha256=row["sha256"], previous_fingerprint=previous, fingerprint=before)

    def prepare(self, job: str, root: Path, manifest: dict[str, Any]) -> Path:
        archive = manifest["archive_id"]
        directory = self.directory(job, archive)
        row = self.row(job, archive)
        ready = directory / "ready.tar"
        if ready.exists() or ready.is_symlink():
            try:
                if row["fingerprint_json"] is None and row["sha256"] and row["path"] == str(ready):
                    owned = self.catalog.db.execute("SELECT * FROM staging_artifacts WHERE job_id=? AND archive_id=? AND name='ready.tar'",
                                                    (job, archive)).fetchone()
                    info = ready.lstat()
                    if (owned is None or not stat.S_ISREG(info.st_mode) or info.st_mode & 0o222
                            or [info.st_dev, info.st_ino] != [owned["device"], owned["inode"]]
                            or sha256(ready) != row["sha256"]):
                        raise SafetyError("Cannot recover interrupted READY publication")
                    verify_archive(ready, manifest)
                    for alias in self.catalog.db.execute("SELECT * FROM staging_artifacts WHERE job_id=? AND archive_id=? AND name!='ready.tar'",
                                                         (job, archive)).fetchall():
                        alias_path = directory / alias["name"]
                        if alias_path.exists() and not alias_path.is_symlink():
                            alias_info = alias_path.stat()
                            if (alias_info.st_dev, alias_info.st_ino) == (info.st_dev, info.st_ino):
                                alias_path.unlink()  # ready.tar retains exactly the same verified inode.
                                with self.catalog.db:
                                    self.catalog.db.execute("DELETE FROM staging_artifacts WHERE job_id=? AND archive_id=? AND name=?",
                                                            (job, archive, alias["name"]))
                    final = fingerprint(ready)
                    sync_dir(directory)
                    with self.catalog.db:
                        self.catalog.db.execute("UPDATE staged_archives SET fingerprint_json=? WHERE job_id=? AND archive_id=?",
                                                (encode(final).decode(), job, archive))
                result = self.validate_ready(job, manifest)
                self.phase(job, archive, "READY", "COMPLETE")
                return result
            except BaseException as error:
                self.phase(job, archive, "VALIDATION", "FAILED", str(error))
                raise
        with self.catalog.db:
            self.catalog.db.execute("DELETE FROM staging_artifacts WHERE job_id=? AND archive_id=? AND name='ready.tar'", (job, archive))
        self.require_space(estimate(manifest["files"]) + 10240)
        # A new attempt never overwrites or deletes a previous interrupted artifact.
        partial = directory / f"{uuid.uuid4()}.partial"
        fd = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        os.close(fd)
        self.track(job, archive, partial)
        self.phase(job, archive, "STAGING", path=str(partial), progress_bytes=0)
        last = time.monotonic()
        def progress(done: int) -> None:
            nonlocal last
            now = time.monotonic()
            if now - last >= 1 or done == row["total_bytes"]:
                with self.catalog.db:
                    self.catalog.db.execute("UPDATE staged_archives SET progress_bytes=?,updated=? WHERE job_id=? AND archive_id=?",
                                            (done, time.time(), job, archive))
                self.catalog.event(job, "staging_progress", archive=archive, bytes=done,
                                   elapsed_seconds=now - last)
                last = now
        try:
            create_archive(partial, root, manifest, progress=progress)
            self.phase(job, archive, "VALIDATION")
            checksum = sha256(partial)
            verify_archive(partial, manifest)
            before = fingerprint(partial)
            if sha256(partial) != checksum or fingerprint(partial) != before:
                raise SafetyError("Staging file changed during validation")
            with partial.open("rb") as stream:
                os.fsync(stream.fileno())
            os.chmod(partial, 0o400)
            # link publication is exclusive; never replace an existing ready archive.
            intent = partial.stat()
            with self.catalog.db:
                self.catalog.db.execute("INSERT INTO staging_artifacts VALUES(?,?,?,?,?)",
                                        (job, archive, ready.name, intent.st_dev, intent.st_ino))
                self.catalog.db.execute("UPDATE staged_archives SET path=?,sha256=?,bytes=?,fingerprint_json=NULL WHERE job_id=? AND archive_id=?",
                                        (str(ready), checksum, intent.st_size, job, archive))
            os.link(partial, ready)
            partial.unlink()
            sync_dir(directory)
            final = fingerprint(ready)
            with self.catalog.db:
                self.catalog.db.execute("DELETE FROM staging_artifacts WHERE job_id=? AND archive_id=? AND name=?",
                                        (job, archive, partial.name))
                self.catalog.db.execute("UPDATE staged_archives SET path=?,sha256=?,bytes=?,fingerprint_json=? WHERE job_id=? AND archive_id=?",
                    (str(ready), checksum, final[2], encode(final).decode(), job, archive))
            self.phase(job, archive, "READY", "COMPLETE", progress_bytes=final[2], total_bytes=final[2])
            return ready
        except BaseException as error:
            self.phase(job, archive, "STAGING" if self.row(job, archive)["phase"] == "STAGING" else "VALIDATION",
                       "INTERRUPTED" if isinstance(error, (KeyboardInterrupt, SystemExit)) else "FAILED", str(error))
            raise

    def metadata_path(self, job: str, archive: str) -> Path:
        directory = self.directory(job, archive)
        path = directory / f"receipt-{uuid.uuid4()}.tar"
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        os.close(fd)
        self.track(job, archive, path)
        return path

    def cleanup(self, job: str, archive: str) -> None:
        row = self.catalog.db.execute("SELECT state FROM archives WHERE id=? AND job_id=?", (archive, job)).fetchone()
        if row is None or row["state"] != "VERIFIED":
            raise SafetyError("Staging cleanup requires a fully read-back VERIFIED archive")
        directory = self.directory(job, archive)
        self.phase(job, archive, "STAGING_CLEANUP")
        artifacts = self.catalog.db.execute("SELECT * FROM staging_artifacts WHERE job_id=? AND archive_id=?", (job, archive)).fetchall()
        # Validate every deletion candidate before deleting any; no recursive deletion.
        for artifact in artifacts:
            name = artifact["name"]
            if Path(name).name != name or name == "owner.json":
                raise SafetyError("Invalid owned artifact name")
            path = directory / name
            if path.exists() or path.is_symlink():
                info = fingerprint(path)
                if info[:2] != [artifact["device"], artifact["inode"]]:
                    raise SafetyError("Cleanup refused: artifact identity changed")
        for artifact in artifacts:
            path = directory / artifact["name"]
            if path.exists():
                path.unlink()
        sync_dir(directory)
        with self.catalog.db:
            self.catalog.db.execute("DELETE FROM staging_artifacts WHERE job_id=? AND archive_id=?", (job, archive))
        self.phase(job, archive, "STAGING_CLEANUP", "COMPLETE")
