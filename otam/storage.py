"""Conservative local-filesystem detection and per-user I/O scheduling."""
from __future__ import annotations

import fcntl
import os
import platform
import re
import shutil
import stat
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .common import SafetyError

LOCAL_LINUX = {"ext2", "ext3", "ext4", "xfs", "btrfs", "zfs", "f2fs", "jfs", "reiserfs", "bcachefs"}


def unescape_mount(value: str) -> str:
    return re.sub(r"\\([0-7]{3})", lambda m: chr(int(m[1], 8)), value)


def local_block_device(major_minor: str, sysfs: Path = Path("/sys/dev/block")) -> bool:
    """Require a visible local block dependency chain, including dm/md slaves."""
    entry = sysfs / major_minor
    if not entry.exists():
        return False
    visited: set[Path] = set()
    def inspect(node: Path) -> bool:
        node = node.resolve()
        if node in visited:
            return False
        visited.add(node)
        text = str(node)
        if re.search(r"/(session[0-9]+|rport-[^/]+|nbd[0-9]+|rbd[^/]*|drbd[0-9]+)(/|$)", text) or "/aoe/" in text:
            return False
        # NVMe transport is exposed at controller level; TCP/RDMA/FC are remote.
        for ancestor in (node, *node.parents):
            transport = ancestor / "transport"
            if transport.exists():
                try:
                    if transport.read_text().strip() not in {"pcie", "pci", "sas", "sata", "usb"}:
                        return False
                except OSError:
                    return False
            slaves = ancestor / "slaves"
            if slaves.is_dir():
                children = list(slaves.iterdir())
                if children:
                    # A dependency graph may share leaves; each branch is independently checked.
                    result = all(inspect(child) for child in children)
                    visited.remove(node)
                    return result
            if ancestor.name == "devices":
                break
        if "/virtual/block/" in text:
            return False  # loop, NBD and opaque virtual devices need a separate validated policy.
        result = "/devices/" in text and any(p.startswith(("pci", "platform", "usb")) for p in node.parts)
        visited.remove(node)
        return result
    try:
        return inspect(entry)
    except OSError:
        return False


def filesystem(path: Path) -> dict[str, Any]:
    path = path.resolve(strict=True)
    candidates = []
    if platform.system() == "Linux":
        for line in Path("/proc/self/mountinfo").read_text().splitlines():
            left, right = line.split(" - ", 1)
            fields, fs = left.split(), right.split()
            mount = Path(unescape_mount(fields[4]))
            if path.is_relative_to(mount):
                candidates.append((len(mount.parts), {"mount": str(mount), "type": fs[0],
                    "source": unescape_mount(fs[1]), "local": fs[0] in LOCAL_LINUX,
                    "read_only": "ro" in fields[5].split(","), "device": os.stat(path).st_dev, "block_device": fields[2]}))
    elif platform.system() == "Darwin":
        df = subprocess.run(["/bin/df", "-P", str(path)], capture_output=True, text=True, check=True, timeout=5).stdout
        device_source = df.splitlines()[-1].split()[0]
        output = subprocess.run(["/sbin/mount"], capture_output=True, text=True, check=True, timeout=5).stdout
        for line in output.splitlines():
            match = re.match(r"^(.+) on (.+) \(([^)]+)\)$", line)
            if match:
                mount = Path(match[2])
                options = match[3].split(", ")
                same_device = match[1] == device_source
                # APFS firmlinks (e.g. /Users) belong to Data even without a lexical prefix.
                if same_device:
                    weight = len(mount.parts) + (1000 if path.is_relative_to(mount) else 0)
                    candidates.append((weight, {"mount": str(mount), "type": options[0],
                        "source": match[1], "local": "local" in options and options[0] in {"apfs", "hfs"},
                        "read_only": "read-only" in options, "device": os.stat(path).st_dev}))
    if not candidates:
        raise SafetyError("Cannot establish staging filesystem locality; refusing staging")
    info = max(candidates, key=lambda entry: entry[0])[1]
    if platform.system() == "Linux" and info["local"]:
        info["local_block_verified"] = local_block_device(info["block_device"])
        info["local"] = info["local"] and info["local_block_verified"]
    info.update({"path": str(path), **dict(zip(("total", "used", "free"), shutil.disk_usage(path)))})
    return info


def require_local(path: Path) -> dict[str, Any]:
    info = filesystem(path)
    if not info["local"] or info["read_only"]:
        raise SafetyError(f"Staging requires a confirmed local writable filesystem, got {info['type']}")
    return info


@contextmanager
def io_lock() -> Iterator[None]:
    """Serialize OTAM heavy I/O across catalogs and staging roots of this user."""
    path = Path(tempfile.gettempdir()) / f"otam-io-{os.getuid()}.lock"
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
            raise SafetyError("Unsafe OTAM I/O lock")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise SafetyError("Another OTAM staging, benchmark or tape operation is active") from error
        yield
    finally:
        os.close(fd)
