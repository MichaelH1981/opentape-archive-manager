"""Small, bounded I/O and path validation primitives."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO

BLOCK = 1024 * 1024
FORMAT = "otam-pax-v1"


class SafetyError(Exception):
    """Operation cannot meet the safety contract."""


def encode(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()


def digest(stream: BinaryIO) -> str:
    result = hashlib.sha256()
    while chunk := stream.read(BLOCK):
        result.update(chunk)
    return result.hexdigest()


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return digest(stream)


def safe_path(name: str) -> str:
    parts = PurePosixPath(name).parts
    if (not name or name.startswith("/") or "\\" in name or "\x00" in name
            or any(p in ("", ".", "..") for p in name.split("/"))
            or not parts or ":" in parts[0]):
        raise SafetyError(f"Unsafe archive path: {name!r}")
    return name


def sync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
