"""Restore only regular payload files, with descriptor-relative exclusive creation."""
from __future__ import annotations

import hashlib
import os
import tarfile
import uuid
from pathlib import Path
from typing import Any, BinaryIO

from .common import BLOCK, SafetyError, digest, safe_path


class PendingRestore:
    """Keep selected files private until the complete physical scan succeeds.

    The temporary directory is created relative to a symlink-safe target fd.
    No unverified file is published under a requested destination name.
    A crash can leave this private directory for explicit recovery/inspection.
    """

    def __init__(self, target: Path, selected: list[dict[str, Any]]):
        self.selected = {(row["archive_id"], row["path"]): row for row in selected}
        self.root_fd = open_directory(target)
        self.name = ".otam-restore-" + str(uuid.uuid4())
        self.pending: list[tuple[str, str]] = []
        self.seen: set[tuple[str, str]] = set()
        try:
            os.mkdir(self.name, 0o700, dir_fd=self.root_fd)
            self.fd = os.open(self.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                              dir_fd=self.root_fd)
        except BaseException:
            os.close(self.root_fd)
            raise

    def consume(self, manifest: dict[str, Any], name: str, payload: BinaryIO,
                entry: dict[str, Any]) -> str:
        key = (manifest["archive_id"], name)
        row = self.selected.get(key)
        if row is None:
            return digest(payload)
        if key in self.seen or any(row[field] != entry[field] for field in ("size", "sha256")):
            raise SafetyError("Restore manifest differs from catalog selection")
        safe_path(name)
        temporary = str(len(self.pending))
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o600, dir_fd=self.fd)
        self.pending.append((temporary, name))
        checksum, written = hashlib.sha256(), 0
        with os.fdopen(fd, "wb") as output:
            while chunk := payload.read(BLOCK):
                checksum.update(chunk)
                written += len(chunk)
                output.write(chunk)
            output.flush()
            os.fsync(output.fileno())
        if written != entry["size"] or checksum.hexdigest() != entry["sha256"]:
            raise SafetyError(f"Restore SHA-256/size mismatch: {name}")
        read_fd = os.open(temporary, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=self.fd)
        with os.fdopen(read_fd, "rb") as output:
            if digest(output) != entry["sha256"]:
                raise SafetyError(f"Destination readback mismatch: {name}")
        self.seen.add(key)
        return checksum.hexdigest()

    def publish(self) -> int:
        if self.seen != set(self.selected):
            raise SafetyError("Catalog selection not found on medium")
        for temporary, name in self.pending:
            parent_fd = os.dup(self.root_fd)
            try:
                parts = safe_path(name).split("/")
                for part in parts[:-1]:
                    try:
                        os.mkdir(part, mode=0o700, dir_fd=parent_fd)
                    except FileExistsError:
                        pass
                    next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                      dir_fd=parent_fd)
                    os.close(parent_fd)
                    parent_fd = next_fd
                # link() is atomic and fails if any destination already exists.
                # The source and target are deliberately on the same filesystem.
                os.link(temporary, parts[-1], src_dir_fd=self.fd, dst_dir_fd=parent_fd,
                        follow_symlinks=False)
                os.fsync(parent_fd)
            finally:
                os.close(parent_fd)
        return len(self.seen)

    def close(self) -> None:
        try:
            for temporary, _ in self.pending:
                os.unlink(temporary, dir_fd=self.fd)
            os.fsync(self.fd)
        finally:
            os.close(self.fd)
            try:
                os.rmdir(self.name, dir_fd=self.root_fd)
                os.fsync(self.root_fd)
            finally:
                os.close(self.root_fd)


def open_directory(root: Path) -> int:
    # Do not resolve(): that would silently follow a pre-existing symlink.
    absolute = Path(os.path.abspath(root))
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in absolute.parts[1:]:
            try:
                os.mkdir(part, mode=0o700, dir_fd=fd)
            except FileExistsError:
                pass
            next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        return fd
    except BaseException:
        os.close(fd)
        raise


def restore_files(incoming: BinaryIO, target: Path, expected: dict[str, Any], names: set[str]) -> int:
    """Extract from a sequential stream already checked by the media scan.

    Every restored payload and destination is independently SHA-256 checked.
    The caller must first verify the complete archive and receipt chain.
    """
    entries = {e["path"]: e for e in expected["files"]}
    if not names <= entries.keys():
        raise SafetyError("Restore selection contains unknown files")
    root_fd = open_directory(target)
    count = 0
    try:
        with tarfile.open(fileobj=incoming, mode="r|") as tar:
            for member in tar:
                if not member.name.startswith("data/"):
                    continue
                name = safe_path(member.name[5:])
                if name not in names:
                    continue
                if not member.isfile():
                    raise SafetyError("Unsafe restore member")
                parts = name.split("/")
                parent_fd = os.dup(root_fd)
                try:
                    for part in parts[:-1]:
                        try:
                            os.mkdir(part, mode=0o700, dir_fd=parent_fd)
                        except FileExistsError:
                            pass
                        next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                          dir_fd=parent_fd)
                        os.close(parent_fd)
                        parent_fd = next_fd
                    fd = os.open(parts[-1], os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                                 0o600, dir_fd=parent_fd)
                    try:
                        checksum = hashlib.sha256()
                        written = 0
                        payload = tar.extractfile(member)
                        assert payload is not None
                        with os.fdopen(fd, "wb") as output:
                            while chunk := payload.read(BLOCK):
                                checksum.update(chunk)
                                written += len(chunk)
                                output.write(chunk)
                            output.flush()
                            os.fsync(output.fileno())
                        if checksum.hexdigest() != entries[name]["sha256"] or written != entries[name]["size"]:
                            raise SafetyError(f"Restore SHA-256/size mismatch: {name}")
                        # Reopen via the same dirfd and actually read back destination bytes.
                        read_fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent_fd)
                        from .common import digest
                        with os.fdopen(read_fd, "rb") as result:
                            if digest(result) != entries[name]["sha256"]:
                                raise SafetyError(f"Destination readback mismatch: {name}")
                        os.fsync(parent_fd)
                    except BaseException:
                        os.unlink(parts[-1], dir_fd=parent_fd)
                        raise
                    count += 1
                finally:
                    os.close(parent_fd)
        if count != len(names):
            raise SafetyError("Restore did not produce every requested file")
        return count
    finally:
        os.close(root_fd)
