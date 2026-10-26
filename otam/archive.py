"""Open PAX archives, strict manifests and safe source inventory."""
from __future__ import annotations

import io
import hashlib
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
PayloadHandler = Callable[[dict[str, Any], str, BinaryIO, dict[str, Any]], str]
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


def inventory(root: Path, selected: list[str] | None = None, *, metadata_only: bool = False,
              allow_empty: bool = False,
              expected: list[dict[str, Any]] | None = None,
              excluded: list[str] | None = None,
              progress: Callable[[dict[str, Any]], None] | None = None) -> list[dict[str, Any]]:
    if excluded is not None and (not isinstance(excluded,list) or len(excluded)>10000 or any(not isinstance(p,str) or len(p)>4096 for p in excluded)):
        raise SafetyError("Invalid source exclusions")
    exclusions = tuple(sorted({safe_path(p) for p in (excluded or [])}))
    def is_excluded(name):
        return any(name == prefix or name.startswith(prefix+'/') for prefix in exclusions)
    entries: list[dict[str, Any]] = []
    started = time.monotonic()
    done_bytes = 0
    expected_bytes = sum(e["size"] for e in expected) if expected is not None else None
    def notify(name, current=0, complete=False):
        if progress:
            progress({"complete":complete, "phase": "INVENTORY" if metadata_only else "HASHING", "files": len(entries),
                      "bytes": done_bytes + current, "path": name, "elapsed_seconds": time.monotonic()-started,
                      "total_bytes": expected_bytes,
                      "total_files": len(expected) if expected is not None else None})
    expected_map = {e['path']: e for e in expected} if expected is not None else None
    def fingerprint(value):
        return [value.st_dev,value.st_ino,value.st_size,value.st_mtime_ns,value.st_ctime_ns]
    if not root.is_dir():
        raise SafetyError("Source must be a directory")
    if selected is not None:
        # The request limit remains 10,000. A sealed metadata inventory may
        # expand a recursive additive selection into more explicit file paths.
        if (not selected or any(not isinstance(p, str) or len(p) > 4096 for p in selected)
                or (len(selected) > 10000 and (expected_map is None or set(selected) != set(expected_map)))):
            raise SafetyError("Invalid source selection")
        chosen = sorted({safe_path(p) for p in selected})
        # Do not resolve links: every selected path component must be a real
        # directory, and source_fd checks the final regular file with O_NOFOLLOW.
        selected_files: set[str] = set()
        selected_dirs: set[str] = set()
        for name in chosen:
            parts = name.split("/")
            current = root
            for part in parts[:-1]:
                current = current / part
                if current.is_symlink() or not current.is_dir():
                    raise SafetyError("Selected source path is not a real directory")
            path = current / parts[-1]
            if path.is_symlink():
                raise SafetyError("Selected source symlinks are unsupported")
            if path.is_dir():
                selected_dirs.add(name)
            elif path.is_file():
                selected_files.add(name)
            else:
                raise SafetyError("Selected source path is missing or unsupported")
    else:
        selected_files, selected_dirs = set(), set()
    def walk_error(error: OSError) -> None:
        raise error
    walks = [root / p for p in sorted(selected_dirs)] if selected is not None else [root]
    seen: set[str] = set()
    def add_file(name: str) -> None:
        nonlocal done_bytes
        if name in seen or is_excluded(name):
            return
        try:
            fd = source_fd(root, name)
        except OSError as error:
            import errno
            if error.errno == errno.ELOOP and metadata_only:
                raise OSError(error.errno, "Symbolische Verknüpfung nicht unterstützt; ausdrücklich ausschließen oder Auswahl ändern", name) from error
            raise
        with os.fdopen(fd, "rb") as stream:
            before = os.fstat(stream.fileno())
            if expected_map is not None and (name not in expected_map or
                    expected_map[name]['fingerprint'] != fingerprint(before)):
                raise SafetyError(f"Source changed since source plan: {name}; create a new source plan")
            if metadata_only:
                checksum = None
            elif progress:
                h = hashlib.sha256(); current = 0
                while chunk := stream.read(1024*1024):
                    h.update(chunk); current += len(chunk); notify(name, current)
                checksum = h.hexdigest()
            else:
                checksum = digest(stream)
            after = os.fstat(stream.fileno())
        if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
                after.st_size, after.st_mtime_ns, after.st_ctime_ns):
            raise SafetyError(f"Source changed while hashing: {name}")
        seen.add(name)
        entry = {"path": safe_path(name), "size": before.st_size,
                 "mtime_ns": before.st_mtime_ns, "type": Path(name).suffix.lower() or "(none)"}
        if metadata_only:
            entry['fingerprint'] = fingerprint(before)
        else:
            entry['sha256'] = checksum
        entries.append(entry)
        done_bytes += before.st_size
        notify(name)
    for name in sorted(selected_files):
        add_file(name)
    for walk_root in walks:
        if is_excluded(walk_root.relative_to(root).as_posix()):
            continue
        for base, dirs, files in os.walk(walk_root, followlinks=False, onerror=walk_error):
            dirs[:] = sorted(d for d in dirs if not is_excluded((Path(base)/d).relative_to(root).as_posix()))
            for directory in dirs:
                if (Path(base) / directory).is_symlink():
                    raise SafetyError("Source directory symlinks are unsupported")
            for filename in sorted(files):
                name = (Path(base) / filename).relative_to(root).as_posix()
                add_file(name)
    if not entries and not (allow_empty and metadata_only):
        raise SafetyError("Source contains no regular files")
    if expected_map is not None and seen != set(expected_map):
        raise SafetyError("Source selection changed since source plan; create a new source plan")
    notify(entries[-1]["path"] if entries else "", complete=True)
    return sorted(entries, key=lambda entry: entry["path"])


def estimate_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Fixed-width size projection only; never a verified manifest or persisted hash."""
    return [{k:v for k,v in e.items() if k!='fingerprint'} | {'sha256':'0'*64} for e in entries]


def estimate(entries: list[dict[str, Any]]) -> int:
    # Deliberately conservative, including JSON escape expansion and PAX headers.
    return 20480 + len(encode(entries)) * 2 + sum(
        ((e["size"] + 511) // 512) * 512 + 4096 + len(e["path"].encode()) * 8 for e in entries)


def group_entries(entries: list[dict[str, Any]], target: int) -> list[list[dict[str, Any]]]:
    if target <= 0:
        raise SafetyError("Target size must be positive")
    groups: list[list[dict[str, Any]]] = []
    batch: list[dict[str, Any]] = []
    # JSON list brackets cost four estimated bytes. Each comma adds two;
    # every entry's own JSON and padded TAR cost can be counted exactly once.
    required = 20484
    for entry in entries:
        addition = len(encode(entry)) * 2 + ((entry['size'] + 511) // 512) * 512 + 4096 + len(entry['path'].encode()) * 8
        if batch and required + addition + 2 > target:
            groups.append(batch)
            batch = []
            required = 20484
        required += addition + (2 if batch else 0)
        batch.append(entry)
    if batch:
        groups.append(batch)
    return groups


def plan_archives(entries: list[dict[str, Any]], media: str, target: int) -> list[dict[str, Any]]:
    groups = group_entries(entries, target)
    return [{"format": FORMAT, "media_id": media, "archive_id": str(uuid.uuid4()),
             "created": time.time(), "files": group} for group in groups]


def create_archive(path: Path, root: Path, manifest: dict[str, Any],
                   progress: Callable[[int], None] | None = None, *, validate: bool = True,
                   single_pass: bool = False, expected: list[dict[str, Any]] | None = None,
                   activity: Callable[[dict[str, Any]], None] | None = None) -> None:
    expected_map = {e["path"]: e for e in (expected or [])}
    with tarfile.open(path, "w", format=tarfile.PAX_FORMAT, copybufsize=1024 * 1024) as tar:
        manifest_bytes = encode(manifest)
        if len(manifest_bytes) > MAX_META:
            raise SafetyError("Manifest exceeds metadata limit; reduce target archive size")
        add_bytes(tar, MANIFEST, manifest_bytes)
        done = 0
        class ProgressReader:
            def __init__(self, stream: BinaryIO):
                self.stream = stream
                self.hasher = hashlib.sha256()
                self.count = 0
            def read(self, size: int = -1) -> bytes:
                nonlocal done
                data = self.stream.read(size)
                self.hasher.update(data)
                self.count += len(data)
                done += len(data)
                if activity:
                    activity({"path":entry["path"], "files":file_index + int(self.count == entry["size"]), "total_files":len(manifest["files"])})
                if progress:
                    progress(done)
                return data
        for file_index, entry in enumerate(manifest["files"]):
            with os.fdopen(source_fd(root, entry["path"]), "rb") as stream:
                info_stat = os.fstat(stream.fileno())
                if (info_stat.st_size, info_stat.st_mtime_ns) != (entry["size"], entry["mtime_ns"]):
                    raise SafetyError(f"Source changed since planning: {entry['path']}")
                before = [info_stat.st_dev, info_stat.st_ino, info_stat.st_size, info_stat.st_mtime_ns, info_stat.st_ctime_ns]
                if single_pass and (entry['path'] not in expected_map or before != expected_map[entry['path']]['fingerprint']):
                    raise SafetyError("Source changed since source plan: " + entry['path'])
                info = tarfile.TarInfo("data/" + entry["path"])
                info.size = entry["size"]
                info.mtime = entry["mtime_ns"] / 1_000_000_000
                info.mode = 0o600
                reader = ProgressReader(stream)
                tar.addfile(info, reader)
                after = os.fstat(stream.fileno())
                if [after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns] != before or reader.count != entry['size']:
                    raise SafetyError("Source changed during TAR creation: " + entry['path'])
                if single_pass:
                    entry['sha256'] = reader.hasher.hexdigest()
                elif reader.hasher.hexdigest() != entry['sha256']:
                    raise SafetyError("Source checksum changed during TAR creation: " + entry['path'])
    if single_pass:
        final = encode(manifest)
        if len(final) != len(manifest_bytes):
            raise SafetyError("Final manifest size changed")
        # Private, unpublished TAR only: fixed-width hashes replace placeholders.
        # The mandatory independent full inspection below certifies final bytes.
        with path.open('r+b') as stream:
            stream.seek(512)
            stream.write(final)
            stream.flush()
            os.fsync(stream.fileno())
    if validate:
        verify_archive(path, manifest)


def verify_archive(path: Path | BinaryIO, expected: dict[str, Any] | None = None,
                   payload_handler: PayloadHandler | None = None) -> dict[str, Any]:
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
            checksum = (digest(payload) if payload_handler is None else
                        payload_handler(manifest, name, payload, entry))
            if checksum != entry["sha256"]:
                raise SafetyError(f"SHA-256 mismatch: {name}")
            seen.add(name)
        if seen != set(entries):
            raise SafetyError("Missing files in TAR")
        return manifest


def inspect_stream(stream: BinaryIO, manifest: dict[str, Any] | None = None,
                   progress: Callable[[int], None] | None = None,
                   payload_handler: PayloadHandler | None = None) -> tuple[dict[str, Any], str, int]:
    """Inspect and hash through filemark before reading the following receipt."""
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
    found = verify_archive(incoming, manifest, payload_handler)
    while incoming.read(1024 * 1024):
        pass  # Include all TAR end blocks/padding through the actual filemark/EOF.
    return found, result.hexdigest(), done


def verify_stream(stream: BinaryIO, expected_hash: str, expected_bytes: int,
                  manifest: dict[str, Any] | None = None,
                  progress: Callable[[int], None] | None = None) -> dict[str, Any]:
    """Hash the entire tape file and inspect TAR in one bounded-memory pass."""
    found, checksum, done = inspect_stream(stream, manifest, progress)
    if done != expected_bytes or checksum != expected_hash:
        raise SafetyError("Full tape readback SHA-256/byte count mismatch")
    return found
