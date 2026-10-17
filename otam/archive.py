"""Open PAX archives, strict manifests and safe source inventory."""
from __future__ import annotations

import io
import json
import os
import stat
import tarfile
import time
import uuid
from pathlib import Path
from typing import Any, BinaryIO, Callable

from .common import FORMAT, SafetyError, digest, encode, safe_path, sha256

MANIFEST = "OTAM/manifest.json"
MAX_META = 32 * 1024 * 1024
RECOVERY = b"""OTAM PAX v1. Keep this medium write protected during recovery.
Each tape file is an independent uncompressed POSIX PAX TAR.
File 0: media.json and RECOVERY.txt. Then alternating data TAR and receipt TAR.
Data TAR starts with OTAM/manifest.json; payload members are under data/.
Receipt contains data TAR SHA-256, archive ID, tape file number, previous receipt hash.
Read each tape file to a fresh local file using Linux st/mt-st, verified block settings,
and mbuffer/dd. Do not use erase, eod followed by writing, or relabel.
List with GNU tar -tf local.tar; extract only regular data/ members into an empty
isolated directory; reject absolute paths, dot-dot, links, devices and duplicates.
Verify payload SHA-256 and sizes against manifest, and the complete data TAR
against receipt. Scan all readable pairs to rebuild a catalog; absence of receipt
means incomplete/uncommitted, not success. No central database is needed.
Physical filemark/close behavior requires hardware validation before first use.
"""


def add_bytes(tar: tarfile.TarFile, name: str, content: bytes) -> None:
    info = tarfile.TarInfo(name)
    info.size = len(content)
    info.mode = 0o600
    tar.addfile(info, io.BytesIO(content))


def metadata_tar(path: Path, name: str, value: dict[str, Any], recovery: bool = False) -> None:
    with tarfile.open(path, "w", format=tarfile.PAX_FORMAT, copybufsize=1024 * 1024) as tar:
        add_bytes(tar, name, encode(value))
        if recovery:
            add_bytes(tar, "RECOVERY.txt", RECOVERY)


def read_metadata(path: Path, name: str, recovery: bool = False) -> dict[str, Any]:
    with tarfile.open(path, "r|") as tar:
        expected = [name, "RECOVERY.txt"] if recovery else [name]
        result = None
        for index, expected_name in enumerate(expected):
            member = tar.next()
            if member is None or member.name != expected_name or not member.isfile() or member.size > MAX_META:
                raise SafetyError("Unexpected or invalid metadata TAR member")
            stream = tar.extractfile(member)
            assert stream is not None
            if index == 0:
                result = json.load(stream)
            else:
                stream.read()
        if tar.next() is not None or not isinstance(result, dict):
            raise SafetyError("Invalid metadata JSON or extra TAR members")
        return result



def source_fd(root: Path, name: str) -> int:
    """Open through directory descriptors, rejecting symlinks at every level."""
    parts = safe_path(name).split("/")
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in parts[:-1]:
            next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        result = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        if not stat.S_ISREG(os.fstat(result).st_mode):
            os.close(result)
            raise SafetyError("Only regular source files are supported")
        return result
    finally:
        os.close(fd)


def inventory(root: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    if not root.is_dir():
        raise SafetyError("Source must be a directory")
    def walk_error(error: OSError) -> None:
        raise error
    for base, dirs, files in os.walk(root, followlinks=False, onerror=walk_error):
        dirs.sort()
        for directory in dirs:
            if (Path(base) / directory).is_symlink():
                raise SafetyError("Source directory symlinks are unsupported")
        for filename in sorted(files):
            name = (Path(base) / filename).relative_to(root).as_posix()
            fd = source_fd(root, name)
            with os.fdopen(fd, "rb") as stream:
                before = os.fstat(stream.fileno())
                checksum = digest(stream)
                after = os.fstat(stream.fileno())
            if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
                    after.st_size, after.st_mtime_ns, after.st_ctime_ns):
                raise SafetyError(f"Source changed while hashing: {name}")
            entries.append({"path": safe_path(name), "size": before.st_size,
                            "mtime_ns": before.st_mtime_ns, "sha256": checksum,
                            "type": Path(name).suffix.lower() or "(none)"})
    if not entries:
        raise SafetyError("Source contains no regular files")
    return entries


def estimate(entries: list[dict[str, Any]]) -> int:
    # Deliberately conservative, including JSON escape expansion and PAX headers.
    return 20480 + len(encode(entries)) * 2 + sum(
        ((e["size"] + 511) // 512) * 512 + 4096 + len(e["path"].encode()) * 8 for e in entries)


def plan_archives(entries: list[dict[str, Any]], media: str, target: int) -> list[dict[str, Any]]:
    if target <= 0:
        raise SafetyError("Target size must be positive")
    groups: list[list[dict[str, Any]]] = []
    batch: list[dict[str, Any]] = []
    for entry in entries:
        if batch and estimate(batch + [entry]) > target:
            groups.append(batch)
            batch = []
        batch.append(entry)
    if batch:
        groups.append(batch)
    return [{"format": FORMAT, "media_id": media, "archive_id": str(uuid.uuid4()),
             "created": time.time(), "files": group} for group in groups]


def create_archive(path: Path, root: Path, manifest: dict[str, Any],
                   progress: Callable[[int], None] | None = None) -> None:
    with tarfile.open(path, "w", format=tarfile.PAX_FORMAT, copybufsize=1024 * 1024) as tar:
        manifest_bytes = encode(manifest)
        if len(manifest_bytes) > MAX_META:
            raise SafetyError("Manifest exceeds metadata limit; reduce target archive size")
        add_bytes(tar, MANIFEST, manifest_bytes)
        done = 0
        class ProgressReader:
            def __init__(self, stream: BinaryIO):
                self.stream = stream
            def read(self, size: int = -1) -> bytes:
                nonlocal done
                data = self.stream.read(size)
                done += len(data)
                if progress:
                    progress(done)
                return data
        for entry in manifest["files"]:
            with os.fdopen(source_fd(root, entry["path"]), "rb") as stream:
                info_stat = os.fstat(stream.fileno())
                if (info_stat.st_size, info_stat.st_mtime_ns) != (entry["size"], entry["mtime_ns"]):
                    raise SafetyError(f"Source changed since planning: {entry['path']}")
                info = tarfile.TarInfo("data/" + entry["path"])
                info.size = entry["size"]
                info.mtime = entry["mtime_ns"] / 1_000_000_000
                info.mode = 0o600
                tar.addfile(info, ProgressReader(stream))
    verify_archive(path, manifest)


def verify_archive(path: Path | BinaryIO, expected: dict[str, Any] | None = None) -> dict[str, Any]:
    arguments = {"name": str(path)} if isinstance(path, Path) else {"fileobj": path}
    with tarfile.open(mode="r|", bufsize=1024 * 1024, **arguments) as tar:
        first = tar.next()
        if first is None or first.name != MANIFEST or not first.isfile() or first.size > MAX_META:
            raise SafetyError("Missing or invalid manifest")
        stream = tar.extractfile(first)
        assert stream is not None
        manifest = json.load(stream)
        if manifest["format"] != FORMAT or (expected is not None and manifest != expected):
            raise SafetyError("Manifest differs from plan or format is unsupported")
        uuid.UUID(manifest["archive_id"])
        uuid.UUID(manifest["media_id"])
        entries = {safe_path(e["path"]): e for e in manifest["files"]}
        if not entries or len(entries) != len(manifest["files"]):
            raise SafetyError("Empty or duplicate manifest paths")
        seen: set[str] = set()
        while (member := tar.next()) is not None:
            if not member.isfile() or not member.name.startswith("data/"):
                raise SafetyError(f"Unsafe or unexpected TAR member: {member.name}")
            name = safe_path(member.name[5:])
            if name not in entries or name in seen:
                raise SafetyError(f"Unexpected or duplicate file: {name}")
            entry = entries[name]
            if member.size != entry["size"]:
                raise SafetyError(f"Size mismatch: {name}")
            payload = tar.extractfile(member)
            assert payload is not None
            if digest(payload) != entry["sha256"]:
                raise SafetyError(f"SHA-256 mismatch: {name}")
            seen.add(name)
        if seen != set(entries):
            raise SafetyError("Missing files in TAR")
        return manifest


def verify_stream(stream: BinaryIO, expected_hash: str, expected_bytes: int,
                  manifest: dict[str, Any] | None = None,
                  progress: Callable[[int], None] | None = None) -> dict[str, Any]:
    """Hash the entire tape file and inspect TAR in one bounded-memory pass."""
    import hashlib
    result = hashlib.sha256()
    done = 0
    class HashReader:
        def read(self, size: int = -1) -> bytes:
            nonlocal done
            data = stream.read(size)
            result.update(data)
            done += len(data)
            if progress:
                progress(done)
            return data
    incoming = HashReader()
    found = verify_archive(incoming, manifest)
    while incoming.read(1024 * 1024):
        pass  # Include all TAR end blocks/padding through the actual filemark/EOF.
    if done != expected_bytes or result.hexdigest() != expected_hash:
        raise SafetyError("Full tape readback SHA-256/byte count mismatch")
    return found
