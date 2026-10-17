#!/usr/bin/env python3
"""Standalone offline recovery: Python standard library only, no OTAM imports.

Usage: python3 recover_tar.py DATA.tar RECEIPT.tar NEW_TARGET
Only use local copies of tape files. A new target directory is required.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import tarfile
from pathlib import Path


def checksum(stream):
    result = hashlib.sha256()
    while chunk := stream.read(1024 * 1024):
        result.update(chunk)
    return result.hexdigest()


def metadata(tar, member):
    if member is None or not member.isfile() or member.size > 32 * 1024 * 1024:
        raise ValueError("Invalid metadata")
    return json.load(tar.extractfile(member))


def validate(name):
    if (not name or name.startswith("/") or "\\" in name or "\x00" in name
            or any(p in ("", ".", "..") for p in name.split("/")) or ":" in name.split("/")[0]):
        raise ValueError("Unsafe payload path")
    return name


def recover(data, receipt, target):
    with tarfile.open(receipt, "r|") as tar:
        member = tar.next()
        if member is None or member.name != "receipt.json":
            raise ValueError("Invalid receipt TAR")
        record = metadata(tar, member)
        if tar.next() is not None:
            raise ValueError("Extra receipt members")
    with data.open("rb") as stream:
        if record["sha256"] != checksum(stream) or record["bytes"] != data.stat().st_size:
            raise ValueError("Whole archive checksum/size mismatch")
    if record["format"] != "otam-pax-v1":
        raise ValueError("Unsupported format")
    with tarfile.open(data, "r|") as tar:
        first = tar.next()
        if first is None or first.name != "OTAM/manifest.json":
            raise ValueError("Missing manifest")
        manifest = metadata(tar, first)
        if (manifest["archive_id"] != record["archive_id"] or manifest["media_id"] != record["media_id"]
                or manifest["format"] != record["format"]):
            raise ValueError("Identity mismatch")
        expected = {validate(e["path"]): e for e in manifest["files"]}
        if not expected or len(expected) != len(manifest["files"]):
            raise ValueError("Empty or duplicate manifest")
        seen = set()
        while (member := tar.next()) is not None:
            if not member.isfile() or not member.name.startswith("data/"):
                raise ValueError("Unsupported payload member")
            name = validate(member.name[5:])
            if name not in expected or name in seen or member.size != expected[name]["size"]:
                raise ValueError("Unknown/duplicate payload or size mismatch")
            if checksum(tar.extractfile(member)) != expected[name]["sha256"]:
                raise ValueError("Payload checksum mismatch")
            seen.add(name)
        if seen != set(expected):
            raise ValueError("Missing payload files")
    # New private directory inside an existing trusted directory. Do not run as root.
    target = target.parent.resolve(strict=True) / target.name
    target.mkdir(mode=0o700, exist_ok=False)
    root_fd = os.open(target, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        recovered = set()
        with tarfile.open(data, "r|") as tar:
            for member in tar:
                if member.name == "OTAM/manifest.json":
                    continue
                if not member.isfile() or not member.name.startswith("data/"):
                    raise ValueError("Unsafe payload on second read")
                name = validate(member.name[5:])
                if name not in expected or member.size != expected[name]["size"]:
                    raise ValueError("Payload changed between reads")
                parts = name.split("/")
                parent_fd = os.dup(root_fd)
                try:
                    for part in parts[:-1]:
                        try:
                            os.mkdir(part, 0o700, dir_fd=parent_fd)
                        except FileExistsError:
                            pass
                        next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent_fd)
                        os.close(parent_fd)
                        parent_fd = next_fd
                    fd = os.open(parts[-1], os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent_fd)
                    result = hashlib.sha256()
                    with os.fdopen(fd, "wb") as output:
                        incoming = tar.extractfile(member)
                        while chunk := incoming.read(1024 * 1024):
                            result.update(chunk)
                            output.write(chunk)
                        output.flush()
                        os.fsync(output.fileno())
                    if result.hexdigest() != expected[name]["sha256"]:
                        raise ValueError("Restored checksum mismatch; target is incomplete")
                    fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent_fd)
                    with os.fdopen(fd, "rb") as output:
                        if checksum(output) != expected[name]["sha256"]:
                            raise ValueError("Destination readback mismatch")
                    os.fsync(parent_fd)
                    recovered.add(name)
                finally:
                    os.close(parent_fd)
        if recovered != set(expected):
            raise ValueError("Missing payload on second read")
        os.fsync(root_fd)
    finally:
        os.close(root_fd)
    return len(expected)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data", type=Path)
    parser.add_argument("receipt", type=Path)
    parser.add_argument("target", type=Path)
    args = parser.parse_args()
    print(json.dumps({"restored_verified_files": recover(args.data, args.receipt, args.target)}))
