"""Read-only Linux O_DIRECT staging benchmark. Never creates test payloads."""
from __future__ import annotations

import json
import mmap
import os
import platform
import stat
import time
import uuid
from pathlib import Path
from typing import Any

from .catalog import Catalog
from .common import SafetyError, encode
from .storage import io_lock, require_local

TARGET_RATE = 120_000_000  # decimal MB/s, deliberately not MiB/s
MIN_DURATION = 1800
MIN_FILE = 10 * 1024 ** 3
CHUNK = 4 * 1024 ** 2


def run_benchmark(catalog: Catalog, root: Path, source: Path, *, seconds: float = MIN_DURATION,
                  min_rate: int = TARGET_RATE) -> dict[str, Any]:
    if seconds <= 0 or min_rate <= 0:
        raise SafetyError("Benchmark duration and required throughput must be positive")
    if platform.system() != "Linux" or not hasattr(os, "O_DIRECT"):
        raise SafetyError("Qualification benchmark requires Linux O_DIRECT; no cached-read fallback")
    root = root.resolve(strict=True)
    source = Path(os.path.abspath(source))
    if source.is_symlink() or not source.resolve(strict=True).is_relative_to(root):
        raise SafetyError("Benchmark file must be a regular file inside local staging")
    with io_lock():
        storage = require_local(root)
        file_storage = require_local(source)
        if (file_storage["source"], file_storage["mount"]) != (storage["source"], storage["mount"]):
            raise SafetyError("Benchmark file must be on the staging filesystem, not a nested mount")
        fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW | os.O_DIRECT)
        try:
            before = os.fstat(fd)
            if not stat.S_ISREG(before.st_mode) or before.st_size < CHUNK:
                raise SafetyError("Benchmark needs a regular file of at least 4 MiB")
            # O_DIRECT buffers and offsets are page aligned. A final unaligned tail is omitted.
            usable = before.st_size // mmap.PAGESIZE * mmap.PAGESIZE
            job = catalog.job("staging_benchmark", None)
            ident = str(uuid.uuid4())
            report: dict[str, Any] = {"id": ident, "job_id": job, "state": "RUNNING", "qualified": False,
                "storage": storage, "source": str(source), "file_bytes": before.st_size,
                "requested_seconds": seconds, "required_rate": min_rate, "direct_io": True}
            with catalog.db:
                catalog.db.execute("INSERT INTO storage_benchmarks VALUES(?,?,?,?)",
                                   (ident, time.time(), str(root), encode(report).decode()))
            started = last = time.monotonic()
            done = window = offset = 0
            samples = []
            try:
                with mmap.mmap(-1, CHUNK) as buffer:
                    view = memoryview(buffer)
                    try:
                        while time.monotonic() - started < seconds:
                            length = min(CHUNK, usable - offset)
                            piece = view[:length]
                            try:
                                count = os.readv(fd, [piece])
                            finally:
                                piece.release()
                            if count != length:
                                raise SafetyError("Benchmark short read; file changed or disk read failed")
                            done += count
                            window += count
                            offset += count
                            now = time.monotonic()
                            if now - last >= 1:
                                sample = {"elapsed": now - started, "seconds": now - last,
                                          "bytes": window, "bytes_per_second": window / (now - last)}
                                samples.append(sample)
                                catalog.event(job, "staging_read_sample", **sample)
                                window = 0
                                last = now
                            if offset == usable:
                                os.lseek(fd, 0, os.SEEK_SET)
                                offset = 0
                        ended = time.monotonic()
                        if window:
                            sample = {"elapsed": ended - started, "seconds": ended - last,
                                      "bytes": window, "bytes_per_second": window / max(ended - last, 1e-9)}
                            samples.append(sample)
                            catalog.event(job, "staging_read_sample", **sample)
                    finally:
                        view.release()
                after = os.fstat(fd)
                if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
                        after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns):
                    raise SafetyError("Benchmark input changed during read test")
                elapsed = ended - started
                minimum = min(s["bytes_per_second"] for s in samples)
                qualified = (seconds >= MIN_DURATION and elapsed >= MIN_DURATION and before.st_size >= MIN_FILE
                             and min_rate >= TARGET_RATE and minimum >= min_rate)
                report.update(state="COMPLETE", seconds=elapsed, bytes=done, average_rate=done / elapsed,
                              minimum_sample_rate=minimum, samples=samples, qualified=qualified,
                              qualification_note="Requires >=1800s, >=10GiB input, every sample >=120 MB/s; no throughput guarantee outside measured conditions")
                catalog.finish(job, "VERIFIED" if qualified else "FAILED",
                               None if qualified else "Benchmark did not meet production qualification requirements", report)
                return report
            except BaseException as error:
                report.update(state="FAILED", error=str(error), qualified=False)
                catalog.finish(job, "FAILED", str(error), report)
                raise
            finally:
                with catalog.db:
                    catalog.db.execute("UPDATE storage_benchmarks SET report_json=? WHERE id=?", (encode(report).decode(), ident))
        finally:
            os.close(fd)


def require_qualification(catalog: Catalog, root: Path) -> None:
    current = require_local(root)
    rows = catalog.db.execute("SELECT report_json FROM storage_benchmarks WHERE root=? ORDER BY time DESC", (str(root.resolve()),))
    for row in rows:
        report = json.loads(row[0])
        storage = report["storage"]
        if (report.get("qualified") and report.get("direct_io")
                and report.get("seconds", 0) >= MIN_DURATION and report.get("required_rate", 0) >= TARGET_RATE
                and report.get("file_bytes", 0) >= MIN_FILE
                and report.get("minimum_sample_rate", 0) >= TARGET_RATE
                and all(storage[key] == current[key] for key in ("mount", "type", "source", "device"))):
            return
    raise SafetyError("No passing long-duration direct-I/O benchmark for this staging filesystem")
