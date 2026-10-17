"""Restore only regular payload files, with descriptor-relative exclusive creation."""
from __future__ import annotations

import hashlib
import os
import tarfile
from pathlib import Path
from typing import Any

from .archive import verify_archive
from .common import BLOCK, SafetyError, safe_path


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


def restore_files(path: Path, target: Path, expected: dict[str, Any], names: set[str]) -> int:
    verify_archive(path, expected)
    entries = {e["path"]: e for e in expected["files"]}
    if not names <= entries.keys():
        raise SafetyError("Restore selection contains unknown files")
    root_fd = open_directory(target)
    count = 0
    try:
        with tarfile.open(path, "r|") as tar:
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
