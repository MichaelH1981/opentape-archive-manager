"""Hardware boundary. Real tape writes intentionally unavailable before acceptance."""
from __future__ import annotations

import fcntl
import os
import tempfile
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, BinaryIO, Callable, Iterator, Protocol, ContextManager

from .archive import metadata_tar, read_metadata
from .common import BLOCK, FORMAT, SafetyError, sync_dir


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
    def __init__(self, device: Path):
        raise SafetyError("Real tape backend disabled: test-band acceptance and explicit write approval required")
