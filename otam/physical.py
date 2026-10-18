"""Linux tape discovery and destructive maintenance boundary; never runs at import."""

from __future__ import annotations

import errno
import fcntl
import hashlib
import json
import os
import platform
import re
import shutil
import stat
import struct
import subprocess
import time
from pathlib import Path
from typing import Any, Callable
from contextlib import contextmanager

from .common import SafetyError

BLOCK_SIZE = 512 * 1024
PATTERN_SIZE = 64 * 1024 * 1024
MAGIC = b"OTAM-QUALIFICATION-V1\n"


def mam_serial(data: bytes) -> str:
    if len(data) < 4:
        raise SafetyError("Unvollständige MAM-Antwort")
    available = int.from_bytes(data[:4], "big")
    if available > len(data) - 4:
        raise SafetyError("Abgeschnittene MAM-Antwort")
    offset = 4
    while offset + 5 <= available + 4:
        attr = int.from_bytes(data[offset : offset + 2], "big")
        length = int.from_bytes(data[offset + 3 : offset + 5], "big")
        offset += 5
        if offset + length > available + 4:
            raise SafetyError("Ungültige MAM-Attributlänge")
        value = data[offset : offset + length]
        offset += length
        if attr == 0x401:
            try:
                serial = value.decode("ascii").strip(" \0")
            except UnicodeDecodeError as error:
                raise SafetyError(
                    "MAM-Seriennummer ist kein gültiger ASCII-Text"
                ) from error
            if (
                not serial
                or len(serial) > 128
                or not all(32 <= ord(c) < 127 for c in serial)
            ):
                raise SafetyError("Keine zuverlässige Medienseriennummer")
            return serial
    raise SafetyError("MAM-Medienseriennummer fehlt; keine destruktive Aktion erlaubt")


def run(args: list[str], timeout: float = 15) -> bytes:
    result = subprocess.run(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
        env={**os.environ, "LC_ALL": "C"},
    )
    if result.returncode:
        raise SafetyError(
            f"{Path(args[0]).name}: Kommando fehlgeschlagen ({result.returncode})"
        )
    return result.stdout


def status(device: str) -> dict[str, Any]:
    # mtget: 5 native longs + 2 ints. Build the architecture-specific _IOR value.
    layout = struct.Struct("@5l2i")
    request = (2 << 30) | (layout.size << 16) | (ord("m") << 8) | 2
    fd = os.open(device, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    try:
        if (
            not stat.S_ISCHR(os.fstat(fd).st_mode)
            or os.major(os.fstat(fd).st_rdev) != 9
        ):
            raise SafetyError("Kein Linux-SCSI-Bandgerät")
        fields = layout.unpack(fcntl.ioctl(fd, request, bytes(layout.size)))
    finally:
        os.close(fd)
    flags = fields[3]
    return {
        "online": bool(flags & 0x01000000),
        "door_open": bool(flags & 0x00040000),
        "eod": bool(flags & 0x08000000),
        "block_size": fields[2] & 0xFFFFFF,
        "density_code": (fields[2] >> 24) & 0xFF,
        "write_protected": bool(flags & 0x04000000),
        "eot": bool(flags & 0x20000000),
        "bot": bool(flags & 0x40000000),
        "file_number": fields[5],
        "block_number": fields[6],
    }


def inquiry_serial(vpd: bytes) -> str:
    """Validate standard INQUIRY VPD page 0x80, from sysfs or sg_inq."""
    if len(vpd) < 4 or vpd[1] != 0x80:
        raise SafetyError("Ungültige Seriennummern-VPD-Seite")
    length = int.from_bytes(vpd[2:4], "big")
    if not 1 <= length <= 128 or length > len(vpd) - 4:
        raise SafetyError("Unvollständige Seriennummern-VPD-Seite")
    serial = vpd[4 : 4 + length].decode("ascii").strip(" \0")
    if not serial or not all(32 <= ord(c) < 127 for c in serial):
        raise SafetyError("Ungültige Laufwerksseriennummer")
    return serial


def discover_drives() -> list[dict[str, Any]]:
    if platform.system() != "Linux":
        return []
    result = []
    for entry in sorted(Path("/sys/class/scsi_tape").glob("nst*")):
        if not re.fullmatch(r"nst[0-9]+", entry.name):
            continue
        base = entry / "device"
        item: dict[str, Any] = {
            "device": "/dev/" + entry.name,
            "sysfs": str(base.resolve()),
            "serial": None,
            "medium_serial": None,
            "ready": False,
        }
        for field in ("vendor", "model", "rev"):
            try:
                item[field] = (base / field).read_text().strip()
            except OSError:
                item[field] = None
        try:
            vpd = (base / "vpd_pg80").read_bytes()
            serial = inquiry_serial(vpd)
            item["serial"] = serial
        except (OSError, ValueError, UnicodeError, SafetyError):
            pass
        item["id"] = hashlib.sha256(
            (item["sysfs"] + "|" + str(item["serial"])).encode()
        ).hexdigest()[:32]
        try:
            sg = next((base / "scsi_generic").glob("sg[0-9]*"))
            item["sg"] = "/dev/" + sg.name
            if not item["serial"]:
                item["serial"] = inquiry_serial(
                    run(["sg_inq", "--page=0x80", "--raw", item["sg"]])
                )
                item["id"] = hashlib.sha256(
                    (item["sysfs"] + "|" + item["serial"]).encode()
                ).hexdigest()[:32]
            item["status"] = status(item["device"])
            if not item["serial"]:
                raise SafetyError("Laufwerksseriennummer nicht lesbar")
            if not item["status"]["online"]:
                raise SafetyError("Kein bereites Medium eingelegt")
            item["medium_serial"] = mam_serial(
                run(["sg_read_attr", "--raw", "--first=0x401", item["sg"]])
            )
            item["ready"] = not item["status"]["write_protected"]
            item["error"] = None if item["ready"] else "Medium ist schreibgeschützt"
        except (
            OSError,
            UnicodeError,
            SafetyError,
            StopIteration,
            subprocess.TimeoutExpired,
        ) as error:
            item["error"] = str(error) or type(error).__name__
            item["busy"] = isinstance(error, OSError) and error.errno == errno.EBUSY
        result.append(item)
    return result


def verify_identity(expected: dict[str, Any]) -> dict[str, Any]:
    drive = next((d for d in discover_drives() if d["id"] == expected["id"]), None)
    if (
        drive is None
        or not drive["ready"]
        or drive["device"] != expected["device"]
        or drive.get("sg") != expected.get("sg")
        or drive["serial"] != expected["serial"]
        or drive["medium_serial"] != expected["medium_serial"]
    ):
        raise SafetyError(
            "Laufwerk, Medium oder Schreibschutz weicht von der ausdrücklichen Freigabe ab"
        )
    return drive


class LinuxMaintenance:
    """No root shell, no arbitrary device names or commands, no automatic retry."""

    def __init__(self, expected: dict[str, Any], lock_root: Path):
        self.expected = expected
        self.device = expected["device"]
        self.lock_root = lock_root

    @contextmanager
    def locked(self):
        self.lock_root.mkdir(mode=0o700, exist_ok=True)
        fd = os.open(
            self.lock_root / (self.expected["id"] + ".lock"),
            os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW,
            0o600,
        )
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise SafetyError("Laufwerk wird bereits von OTAM verwendet") from error
            verify_identity(self.expected)
            yield
        finally:
            os.close(fd)

    def check(self):
        verify_identity(self.expected)

    def mt(self, operation: str, *args: str):
        if operation not in ("rewind", "setblk", "compression", "erase"):
            raise SafetyError("Nicht erlaubte Bandoperation")
        run(
            ["mt", "-f", self.device, operation, *args],
            timeout=24 * 3600 if operation == "erase" else 900,
        )

    def writer(self):
        fd = os.open(self.device, os.O_WRONLY | os.O_NOFOLLOW)
        if (
            not stat.S_ISCHR(os.fstat(fd).st_mode)
            or os.major(os.fstat(fd).st_rdev) != 9
        ):
            os.close(fd)
            raise SafetyError("Ungültiges Bandgerät")
        return fd

    def reader(self):
        return os.open(self.device, os.O_RDONLY | os.O_NOFOLLOW)

    def write(self, fd: int, block: bytes) -> int:
        return os.write(fd, block)

    def read(self, fd: int) -> bytes:
        return os.read(fd, BLOCK_SIZE)

    def close(self, fd: int):
        os.close(fd)

    def alerts(self) -> dict[str, Any]:
        from .diagnostics import collect

        sink = getattr(self, "diagnostic_sink", None)
        # All web maintenance jobs supply durable persistence before TapeAlert reads.
        if sink is None:
            return {"unavailable": "Kein dauerhafter Diagnosespeicher konfiguriert"}
        return collect(self.expected, sink)


def pattern(seed: str) -> bytes:
    return hashlib.shake_256(bytes.fromhex(seed)).digest(PATTERN_SIZE)


def test_block(index: int, seed: str, data: bytes) -> bytes:
    if index == 0:
        header = (
            MAGIC
            + json.dumps(
                {
                    "format": "otam-qualification-v1",
                    "seed": seed,
                    "block_size": BLOCK_SIZE,
                    "pattern_bytes": PATTERN_SIZE,
                },
                sort_keys=True,
            ).encode()
            + b"\n"
        )
        return header + data[: BLOCK_SIZE - len(header)]
    offset = ((index - 1) % (len(data) // BLOCK_SIZE)) * BLOCK_SIZE
    return struct.pack(">Q", index) + data[offset + 8 : offset + BLOCK_SIZE]


def qualify(
    device: Any,
    seed: str,
    progress: Callable[..., None],
    *,
    max_bytes: int = 20_000_000_000_000,
    sample: bool = False,
    write_seconds: float = 3000,
) -> dict[str, Any]:
    """Fill to the first ENOSPC early warning, then verify every accepted record.

    Partial writes and close/filemark errors are failures, never qualified media.
    No attempt to write past early warning or continue after a device error.
    """
    if not re.fullmatch("[0-9a-f]{64}", seed):
        raise SafetyError("Ungültiger reproduzierbarer Testseed")
    if sample and (
        max_bytes < 2 * BLOCK_SIZE
        or max_bytes % BLOCK_SIZE
        or not 0 < write_seconds <= 3000
    ):
        raise SafetyError("Ungültige Grenzen für begrenzten Bandtest")
    data = pattern(seed)
    before = device.alerts()
    accepted = 0
    eom = False
    expected = hashlib.sha256()
    progress(phase="PREPARING", bytes=0, seed=seed)
    device.check()
    device.mt("rewind")
    device.mt("setblk", "0")
    device.mt("compression", "0")
    device.check()
    fd = device.writer()
    started = time.monotonic()
    last = started
    try:
        while accepted * BLOCK_SIZE < max_bytes:
            if sample and accepted >= 2 and time.monotonic() - started >= write_seconds:
                break
            block = test_block(accepted, seed, data)
            try:
                n = device.write(fd, block)
            except OSError as error:
                if error.errno == errno.ENOSPC:
                    eom = True
                    break
                raise
            if n != len(block):
                raise SafetyError("Kurzer Band-Schreibvorgang; Test unvollständig")
            accepted += 1
            expected.update(block)
            now = time.monotonic()
            if now - last >= 2:
                progress(
                    phase="TAPE_WRITE",
                    bytes=accepted * BLOCK_SIZE,
                    bytes_per_second=accepted * BLOCK_SIZE / max(now - started, 0.001),
                )
                last = now
    finally:
        device.close(fd)
    write_elapsed = time.monotonic() - started
    if not eom and not sample:
        raise SafetyError(
            "Sicherheitslimit erreicht, ohne Bandende; keine Vollqualifikation"
        )
    if accepted < 2:
        raise SafetyError("Bandende ohne nutzbaren Testdatenbereich")
    progress(
        phase="READBACK_POSITIONING",
        bytes=0,
        bytes_per_second=None,
        total_bytes=accepted * BLOCK_SIZE,
        written_bytes=accepted * BLOCK_SIZE,
        expected_sha256=expected.hexdigest(),
        eom=eom,
    )
    device.check()
    device.mt("rewind")
    device.check()
    fd = device.reader()
    progress(
        phase="TAPE_READBACK",
        bytes=0,
        bytes_per_second=None,
        total_bytes=accepted * BLOCK_SIZE,
    )
    actual = hashlib.sha256()
    count = 0
    started = time.monotonic()
    last = started
    try:
        while block := device.read(fd):
            if count >= accepted or block != test_block(count, seed, data):
                raise SafetyError("Testdaten fehlen, sind vertauscht oder beschädigt")
            actual.update(block)
            count += 1
            now = time.monotonic()
            if now - last >= 2:
                progress(
                    phase="TAPE_READBACK",
                    bytes=count * BLOCK_SIZE,
                    total_bytes=accepted * BLOCK_SIZE,
                    bytes_per_second=count * BLOCK_SIZE / max(now - started, 0.001),
                )
                last = now
    finally:
        device.close(fd)
    if count != accepted or actual.hexdigest() != expected.hexdigest():
        raise SafetyError("Vollständige Rückleseverifikation fehlgeschlagen")
    device.check()
    return {
        "state": "SAMPLE_VERIFIED" if sample else "VERIFIED",
        "scope": "bounded_sample" if sample else "full_medium",
        "write_seconds": write_elapsed,
        "read_seconds": time.monotonic() - started,
        "bytes": count * BLOCK_SIZE,
        "sha256": actual.hexdigest(),
        "seed": seed,
        "eom": eom,
        "before": before,
        "after": device.alerts(),
        "compression": "disabled",
        "capacity_meaning": (
            "sample only; no full-media qualification"
            if sample
            else "usable capacity to first early-warning ENOSPC; not forced physical EOT"
        ),
    }


def erase(device: Any, long: bool, progress: Callable[..., None]) -> dict[str, Any]:
    before = device.alerts()
    progress(phase="ERASING", bytes=0)
    device.check()
    device.mt("rewind")
    device.check()
    device.mt("erase", "1" if long else "0")
    device.check()
    return {
        "state": "ERASE_COMMAND_COMPLETED",
        "method": "long" if long else "short",
        "sanitization_certified": False,
        "before": before,
        "after": device.alerts(),
    }
