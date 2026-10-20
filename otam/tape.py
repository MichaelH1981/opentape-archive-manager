"""Tape boundaries; the physical backend remains gated by operator workflows."""
from __future__ import annotations

import fcntl
import hashlib
import os
import re
import stat
import tempfile
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, BinaryIO, Callable, Iterator, Protocol, ContextManager

from .archive import metadata_tar, read_metadata
from .common import BLOCK, FORMAT, SafetyError, sha256, sync_dir


class Tape(Protocol):
    def locked(self) -> ContextManager[None]: ...
    def header(self) -> dict[str, Any]: ...
    def positions(self) -> list[int]: ...
    def read(self, position: int) -> Path: ...
    def open_read(self, position: int) -> ContextManager[BinaryIO]: ...
    def set_monitor(self, callback: Callable[[dict[str, Any]], None] | None) -> None: ...
    def append(self, source: Path, expected_media: str) -> int: ...
    def used(self) -> int: ...
    def has_partial(self) -> bool: ...


class SimulatedTape:
    """Persistent append-only tape files; faults are injected by tests only."""
    def __init__(self, path: Path, *, fail_after: int | None = None,
                 read_error: int | None = None, interrupt_after: int | None = None):
        self.path = path.resolve()
        if self.path == Path("/dev") or Path("/dev") in self.path.parents:
            raise SafetyError("Simulator may never use /dev")
        if not self.path.is_dir() or not (self.path / "SIMULATED_TAPE").is_file():
            raise SafetyError("Not an initialized simulator medium")
        self.fail_after = fail_after
        self.interrupt_after = interrupt_after
        self.read_error = read_error
        self._locked = False
        self._monitor: Callable[[dict[str, Any]], None] | None = None

    @classmethod
    def create(cls, path: Path, label: str, capacity: int, media_class: str = "permanent") -> SimulatedTape:
        path = path.resolve()
        if path == Path("/dev") or Path("/dev") in path.parents or capacity < 32768:
            raise SafetyError("Invalid simulator path or capacity")
        if media_class not in ("permanent", "rotation"):
            raise SafetyError("Unknown media class")
        path.mkdir(parents=True, exist_ok=False)
        (path / "SIMULATED_TAPE").write_text("OTAM simulator only\n")
        header = {"format": FORMAT, "media_id": str(uuid.uuid4()), "label": label,
                  "capacity": capacity, "class": media_class, "created": time.time(),
                  "backend": "simulator"}
        metadata_tar(path / "00000000.tar", "media.json", header, recovery=True)
        with (path / "00000000.tar").open("rb") as stream:
            os.fsync(stream.fileno())
        sync_dir(path)
        return cls(path)

    @contextmanager
    def locked(self) -> Iterator[None]:
        if self._locked:
            raise SafetyError("Nested device access")
        with (self.path / ".lock").open("a+b") as stream:
            try:
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise SafetyError("Drive is already locked") from error
            self._locked = True
            try:
                yield
            finally:
                self._locked = False
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)

    def header(self) -> dict[str, Any]:
        header = read_metadata(self.read(0), "media.json", recovery=True)
        if header.get("format") != FORMAT or header.get("backend") != "simulator":
            raise SafetyError("Unknown medium format")
        uuid.UUID(header["media_id"])
        return header

    def positions(self) -> list[int]:
        positions = sorted(int(p.stem) for p in self.path.glob("*.tar"))
        if positions != list(range(len(positions))):
            raise SafetyError("Tape file sequence has a gap")
        return positions

    def read(self, position: int) -> Path:
        if not self._locked:
            raise SafetyError("Device lock required")
        if self.read_error == position:
            raise OSError("Injected tape read error")
        result = self.path / f"{position:08d}.tar"
        if not result.is_file() or result.is_symlink():
            raise SafetyError("Missing or unsafe tape file")
        return result

    @contextmanager
    def open_read(self, position: int) -> Iterator[BinaryIO]:
        with self.read(position).open("rb") as stream:
            yield stream

    def set_monitor(self, callback: Callable[[dict[str, Any]], None] | None) -> None:
        self._monitor = callback

    def has_partial(self) -> bool:
        return any(self.path.glob("*.partial"))

    def used(self) -> int:
        return sum(p.stat().st_size for p in self.path.iterdir() if p.suffix in (".tar", ".partial"))

    def append(self, source: Path, expected_media: str) -> int:
        if not self._locked:
            raise SafetyError("Device lock required")
        header = self.header()
        if expected_media != header["media_id"]:
            raise SafetyError("Wrong medium inserted")
        if self.has_partial():
            raise SafetyError("Incomplete tail: append is forbidden")
        positions = self.positions()
        position = len(positions)
        if source.stat().st_size + self.used() > header["capacity"]:
            raise SafetyError("End of medium: no archive splitting")
        partial = self.path / f"{position:08d}.partial"
        transferred = 0
        started = time.monotonic()
        with partial.open("xb") as target, source.open("rb") as incoming:
            while chunk := incoming.read(BLOCK):
                limit = self.fail_after if self.fail_after is not None else self.interrupt_after
                if limit is not None and transferred + len(chunk) > limit:
                    target.write(chunk[:max(0, limit - transferred)])
                    target.flush()
                    os.fsync(target.fileno())
                    sync_dir(self.path)
                    if self.interrupt_after is not None:
                        raise KeyboardInterrupt("Injected interrupted tape write")
                    raise OSError("Injected tape write error")
                target.write(chunk)
                transferred += len(chunk)
                if self._monitor:
                    self._monitor({"bytes": transferred, "bytes_per_second": transferred / max(time.monotonic() - started, 1e-9),
                                   "buffer_fill": None, "drive_status": "simulator", "repositions": None})
            target.flush()
            os.fsync(target.fileno())
        # Exclusive link publishes without replacing an existing tape file.
        os.link(partial, self.path / f"{position:08d}.tar")
        partial.unlink()
        sync_dir(self.path)
        return position


class LinuxTape:
    """Conservative Linux st backend for an already initialized OTAM medium.

    A missing receipt, an uncertain EOD, or an interrupted write blocks further
    appends.  Initialization/overwriting is deliberately a separate operation.
    """

    def __init__(self, expected: dict[str, Any], state: Path | None = None, *, buffer_mib: int = 512):
        from .physical import LinuxMaintenance

        if state is None or not isinstance(expected, dict):
            raise SafetyError("Physical tape requires a discovered drive, MAM identity and state directory")
        if not 64 <= buffer_mib <= 4096:
            raise SafetyError("Invalid mbuffer size")
        if not expected.get("medium_serial") or not expected.get("serial"):
            raise SafetyError("Physical drive and MAM serial are required")
        if not re.fullmatch(r"/dev/nst[0-9]+", expected.get("device", "")):
            raise SafetyError("Only Linux non-rewinding tape devices are supported")
        self.device = LinuxMaintenance(expected, state / "drive-locks", writable=False)
        self.state = state
        self.buffer_mib = buffer_mib
        self._locked = False
        self._monitor: Callable[[dict[str, Any]], None] | None = None
        self._metadata: list[Path] = []
        self._metadata_cache: dict[int, Path] = {}
        self._count_cache: int | None = None
        self._pending = state / "physical-pending" / (hashlib.sha256(
            expected["medium_serial"].encode()).hexdigest() + ".json")
        self._next_receipt: int | None = None
        self._pending_used: int | None = None
        self._receipt_expected: dict[str, Any] | None = None

    @contextmanager
    def locked(self) -> Iterator[None]:
        if self._locked:
            raise SafetyError("Nested device access")
        with self.device.locked():
            self._locked = True
            try:
                self._driver_mode()
                self.device.mt("setblk", "0")
                yield
            finally:
                self._locked = False
                self._next_receipt = None
                self._pending_used = None
                self._receipt_expected = None
                for path in self._metadata:
                    path.unlink(missing_ok=True)
                self._metadata.clear()
                self._metadata_cache.clear()
                self._count_cache = None

    def _driver_mode(self) -> None:
        """Only the Linux st close/EOF semantics validated on the test medium."""
        path = Path("/sys/class/scsi_tape") / Path(self.device.device).name / "options"
        try:
            options = int(path.read_text().strip(), 16)
        except (OSError, ValueError) as error:
            raise SafetyError("Cannot establish Linux st filemark/EOF mode") from error
        # buffer-writes, async-writes, read-ahead, can-bsr. In particular no
        # two-fm, fast-mteom, sysv, nowait or nowait-eof may be enabled.
        if options & ~0x107:
            raise SafetyError("Linux st options differ from the accepted filemark/EOF mode")

    def _check(self) -> None:
        if not self._locked:
            raise SafetyError("Device lock required")
        self.device.check()

    def _move(self, operation: str, count: int | None = None) -> None:
        from .physical import run

        arguments = ["mt", "-f", self.device.device, operation]
        if count is not None:
            arguments.append(str(count))
        run(arguments, timeout=900)

    def _count(self, *, force: bool = False) -> int:
        from .physical import status

        self._check()
        if self._count_cache is not None and not force:
            return self._count_cache
        self._move("eod")
        value = status(self.device.device)
        count = value["file_number"]
        if not value["eod"] or value["block_number"] != -1 or not 0 <= count <= 4095:
            raise SafetyError("Physical EOD/file count is not confirmed")
        self._count_cache = count
        return count

    def _seek(self, position: int) -> None:
        from .physical import status

        self._check()
        if position < 0 or position >= self._count():
            raise SafetyError("Tape file does not exist")
        current = status(self.device.device)
        if current["file_number"] == position and current["block_number"] == 0:
            return
        self._move("rewind")
        if position:
            self._move("fsf", position)
        value = status(self.device.device)
        if value["file_number"] != position or value["block_number"] != 0:
            raise SafetyError("Physical tape position is unconfirmed")

    def positions(self) -> list[int]:
        return list(range(self._count()))

    def has_partial(self) -> bool:
        return self._pending.exists() or self._count() % 2 == 0

    def read(self, position: int) -> Path:
        """Materialize only the small header/receipt TARs used by the service."""
        self._check()
        if position != 0 and position % 2:
            raise SafetyError("Large data archives must be read as a stream")
        if position in self._metadata_cache:
            return self._metadata_cache[position]
        self.state.mkdir(parents=True, exist_ok=True, mode=0o700)
        with tempfile.NamedTemporaryFile(prefix="otam-tape-meta-", suffix=".tar",
                                         dir=self.state, delete=False) as target:
            path = Path(target.name)
            self._metadata.append(path)
            with self.open_read(position) as incoming:
                total = 0
                while chunk := incoming.read(BLOCK):
                    total += len(chunk)
                    if total > 64 * 1024 * 1024:
                        raise SafetyError("Physical metadata TAR exceeds 64 MiB")
                    target.write(chunk)
            target.flush()
            os.fsync(target.fileno())
        self._metadata_cache[position] = path
        return path

    @contextmanager
    def open_read(self, position: int) -> Iterator[BinaryIO]:
        self._seek(position)
        fd = self.device.reader()
        try:
            with os.fdopen(fd, "rb", buffering=0) as stream:
                yield stream
        finally:
            # fdopen owns the descriptor, including exceptional exits.
            pass

    def header(self) -> dict[str, Any]:
        header = read_metadata(self.read(0), "media.json", recovery=True)
        if (header.get("format") != FORMAT or header.get("backend") != "physical"
                or header.get("medium_serial") != self.device.expected["medium_serial"]):
            raise SafetyError("Unknown physical format or wrong MAM medium")
        uuid.UUID(header["media_id"])
        return header

    def set_monitor(self, callback: Callable[[dict[str, Any]], None] | None) -> None:
        self._monitor = callback

    def initialize(self, label: str, capacity: int, media_class: str,
                   confirmation: str) -> dict[str, Any]:
        """Explicit destructive initialization, separate from ordinary append."""
        import json
        from .physical import status

        self._check()
        self._driver_mode()
        serial = self.device.expected["medium_serial"]
        if confirmation != f"INITIALIZE {serial}":
            raise SafetyError("Explicit MAM-bound initialization confirmation is required")
        if (not 1 <= len(label.strip()) <= 100
                or media_class not in ("permanent", "rotation")
                or not 32768 <= capacity <= 100_000_000_000_000):
            raise SafetyError("Invalid physical media metadata")
        if self._pending.exists():
            raise SafetyError("Previous physical operation is unresolved")
        self._metadata_cache.clear()
        self._count_cache = None
        header = {"format": FORMAT, "media_id": str(uuid.uuid4()), "label": label.strip(),
                  "capacity": capacity, "class": media_class, "created": time.time(),
                  "backend": "physical", "medium_serial": serial}
        self.state.mkdir(parents=True, exist_ok=True, mode=0o700)
        with tempfile.NamedTemporaryFile(prefix="otam-new-header-", suffix=".tar",
                                         dir=self.state, delete=False) as target:
            path = Path(target.name)
        try:
            metadata_tar(path, "media.json", header, recovery=True)
            checksum = sha256(path)
            self.device.mt("setblk", "0")
            self.device.mt("compression", "0")
            self.device.check()
            self._move("rewind")
            value = status(self.device.device)
            if (not value["bot"] or value["file_number"] != 0
                    or value["block_number"] != 0 or value["write_protected"]):
                raise SafetyError("Physical BOT or write protection is unconfirmed")
            self._pending.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            with self._pending.open("x") as marker:
                json.dump({"operation": "initialize", "medium_serial": serial,
                           "media_id": header["media_id"], "started": time.time()}, marker)
                marker.flush()
                os.fsync(marker.fileno())
            sync_dir(self._pending.parent)
            fd = self.device.writer()
            try:
                with path.open("rb") as source:
                    while chunk := source.read(BLOCK):
                        if os.write(fd, chunk) != len(chunk):
                            raise SafetyError("Incomplete physical header write")
            finally:
                os.close(fd)
            value = status(self.device.device)
            if value["file_number"] != 1 or value["block_number"] != 0:
                raise SafetyError("Physical header filemark was not confirmed")
            if self._count(force=True) != 1 or self.header() != header or sha256(self.read(0)) != checksum:
                raise SafetyError("Physical header readback mismatch")
            self._pending.unlink()
            sync_dir(self._pending.parent)
            return header
        finally:
            path.unlink(missing_ok=True)

    def used(self) -> int:
        count = self._count()
        if count == 0:
            return 0
        if count % 2 == 0 and count == self._next_receipt and self._pending_used is not None:
            return self._pending_used
        if count % 2 == 0 or self._pending.exists():
            return self.header()["capacity"]
        total = self.read(0).stat().st_size
        for position in range(2, count, 2):
            receipt = self.read(position)
            value = read_metadata(receipt, "receipt.json")
            if value.get("tape_file") != position - 1 or not isinstance(value.get("bytes"), int):
                raise SafetyError("Invalid physical receipt; capacity unknown")
            total += value["bytes"] + receipt.stat().st_size
        return total

    def append(self, source: Path, expected_media: str) -> int:
        import json
        import subprocess
        from .physical import BLOCK_SIZE, status

        self._check()
        self._driver_mode()
        header = self.header()
        if header["media_id"] != expected_media:
            raise SafetyError("Wrong physical medium")
        count = self._count()
        if self._pending.exists() or (count % 2 == 0 and count != self._next_receipt):
            raise SafetyError("Incomplete or uncertain physical tape tail")
        if not source.is_file() or source.is_symlink():
            raise SafetyError("Unsafe staged TAR")
        if count % 2 == 0:
            receipt = read_metadata(source, "receipt.json")
            if (self._receipt_expected is None
                    or any(receipt.get(key) != value for key, value in self._receipt_expected.items())):
                raise SafetyError("Receipt differs from the data just written")
        from .storage import require_local
        require_local(source.parent)
        size = source.stat().st_size
        used_before = self.used()
        if size <= 0 or used_before + size + 10240 > header["capacity"] * 95 // 100:
            raise SafetyError("Archive exceeds conservative physical capacity")
        # Recheck identity and exact EOD immediately before opening for write.
        self.device.mt("setblk", "0")
        self.device.mt("compression", "0")
        if self._count(force=True) != count:
            raise SafetyError("Physical file count changed")
        value = status(self.device.device)
        if (not value["eod"] or value["file_number"] != count
                or value["block_number"] != -1 or value["write_protected"]):
            raise SafetyError("Append position or write protection is unconfirmed")
        self._pending.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self._pending.open("x") as marker:
            json.dump({"medium_serial": self.device.expected["medium_serial"],
                       "media_id": expected_media, "position": count,
                       "source": str(source), "bytes": size, "started": time.time()}, marker)
            marker.flush()
            os.fsync(marker.fileno())
        sync_dir(self._pending.parent)
        started = time.monotonic()
        written = 0
        written_hash = hashlib.sha256()
        source_fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            before = os.fstat(source_fd)
            if (not stat.S_ISREG(before.st_mode) or before.st_size != size
                    or before.st_mode & 0o222 or size % 512):
                raise SafetyError("Staged TAR changed before write")
            tape_fd = self.device.writer()
            try:
                command = ["mbuffer", "-e", "-q", "-s", "256k", "-m",
                           f"{self.buffer_mib}M", "-i", f"/proc/self/fd/{source_fd}"]
                with tempfile.TemporaryFile(dir=self.state) as errors:
                    with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=errors,
                                          pass_fds=(source_fd,)) as process:
                        try:
                            assert process.stdout is not None
                            while chunk := process.stdout.read(BLOCK_SIZE):
                                if written + len(chunk) > size:
                                    raise SafetyError("Staged TAR grew during physical write")
                                # A short record can be early EOM. Never retry.
                                if os.write(tape_fd, chunk) != len(chunk):
                                    raise SafetyError("Short physical tape write; medium is incomplete")
                                written += len(chunk)
                                written_hash.update(chunk)
                                if self._monitor:
                                    self._monitor({"bytes": written,
                                        "bytes_per_second": written / max(time.monotonic() - started, 1e-9),
                                        "buffer_fill": None, "drive_status": "writing", "repositions": None})
                            result = process.wait()
                            errors.seek(max(0, errors.tell() - 512))
                            error = errors.read(512)
                            if result or written != size:
                                raise SafetyError("mbuffer failed or wrote an incomplete tape file: "
                                                  + error.decode(errors="replace"))
                        finally:
                            if process.poll() is None:
                                process.terminate()
                                try:
                                    process.wait(timeout=5)
                                except subprocess.TimeoutExpired:
                                    process.kill()
                                    process.wait()
            finally:
                os.close(tape_fd)  # st writes one filemark on close in the accepted mode.
            after = os.fstat(source_fd)
            if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
                    after.st_size, after.st_mtime_ns, after.st_ctime_ns):
                raise SafetyError("Staged TAR changed during physical write")
            value = status(self.device.device)
            if value["file_number"] != count + 1 or value["block_number"] != 0:
                raise SafetyError("Tape filemark was not confirmed after write")
            self._count_cache = count + 1
            self._pending.unlink()
            sync_dir(self._pending.parent)
            if count % 2:
                self._next_receipt = count + 1
                self._pending_used = used_before + size
                self._receipt_expected = {"media_id": expected_media, "tape_file": count,
                                          "sha256": written_hash.hexdigest(), "bytes": size}
            else:
                self._next_receipt = None
                self._pending_used = None
                self._receipt_expected = None
            return count
        finally:
            os.close(source_fd)
