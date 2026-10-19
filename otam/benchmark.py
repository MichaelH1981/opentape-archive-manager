"""Linux O_DIRECT staging benchmark and explicitly managed test fixture."""
from __future__ import annotations

import json
import mmap
import os
import platform
import shutil
import stat
import time
import uuid
from contextlib import nullcontext
from pathlib import Path
from typing import Any, Callable

from .catalog import Catalog
from .common import SafetyError, encode
from .storage import io_lock, require_local

TARGET_RATE = 120_000_000  # decimal MB/s, deliberately not MiB/s
MIN_DURATION = 1800
MIN_FILE = 10 * 1024 ** 3
CHUNK = 4 * 1024 ** 2
TEST_FILE_BYTES = 12 * 1024 ** 3
BUFFER_RESERVE_SECONDS = 15
RECOVERY_SECONDS = 5
BUFFER_USABLE_FRACTION = 0.75
AVERAGE_HEADROOM = 1.05
QUALIFICATION_VERSION = 2
Progress = Callable[[dict[str, Any]], None]


def available_memory() -> int:
    for line in Path('/proc/meminfo').read_text().splitlines():
        if line.startswith('MemAvailable:'):
            return int(line.split()[1]) * 1024
    raise SafetyError('Cannot determine available system memory')


def buffer_analysis(samples: list[dict[str, Any]], rate: int, buffer_bytes: int) -> dict[str, Any]:
    """Model a prefilled FIFO: excess input refills it, deficits consume it."""
    if not samples or rate <= 0 or buffer_bytes <= 0:
        raise SafetyError('Insufficient measurements for buffer analysis')
    backlog = peak = 0.0
    total_bytes = total_seconds = 0.0
    for sample in samples:
        seconds = float(sample['seconds'])
        incoming = float(sample['bytes'])
        if seconds <= 0 or incoming < 0:
            raise SafetyError('Invalid benchmark sample')
        total_bytes += incoming
        total_seconds += seconds
        backlog = max(0.0, backlog + rate * seconds - incoming)
        peak = max(peak, backlog)
    average = total_bytes / total_seconds
    reserve = rate * BUFFER_RESERVE_SECONDS
    recovery_allowance = rate * RECOVERY_SECONDS
    usable = buffer_bytes * BUFFER_USABLE_FRACTION
    return {
        'rate_bytes_per_second': rate,
        'buffer_bytes': buffer_bytes,
        'average_bytes_per_second': average,
        'average_headroom_percent': 100 * (average / rate - 1),
        'maximum_buffer_deficit_bytes': peak,
        'final_buffer_deficit_bytes': backlog,
        'reserve_bytes': reserve,
        'recovery_allowance_bytes': recovery_allowance,
        'usable_buffer_bytes': usable,
        'average_sufficient': average >= rate * AVERAGE_HEADROOM,
        'buffer_sufficient': peak + reserve <= usable,
        'recovered': backlog <= recovery_allowance,
        'qualified': (average >= rate * AVERAGE_HEADROOM
                      and peak + reserve <= usable and backlog <= recovery_allowance),
    }


def transfer_recommendation(samples: list[dict[str, Any]], *, memory_bytes: int,
                            drive_cap: int = TARGET_RATE) -> dict[str, Any]:
    """Choose the fastest measured sustainable host feed with a bounded buffer."""
    if not samples or memory_bytes <= 0 or drive_cap <= 0:
        raise SafetyError('Insufficient measurements for transfer recommendation')
    minimum = min(s['bytes_per_second'] for s in samples)
    average = sum(s['bytes'] for s in samples) / sum(s['seconds'] for s in samples)
    stressed = any(s.get('system_cpu_percent', 0) >= 85 or s.get('io_wait_percent', 0) >= 30
                   for s in samples)
    quantum = 64 * 1024 ** 2
    memory_cap = max(256 * 1024 ** 2, min(4 * 1024 ** 3, memory_bytes // 2))
    memory_cap = memory_cap // quantum * quantum
    rate = max(1_000_000, min(drive_cap, int(average / AVERAGE_HEADROOM)) // 1_000_000 * 1_000_000)
    requested = buffer_bytes = 0
    while rate >= 1_000_000:
        model = buffer_analysis(samples, rate, memory_cap)
        requested = max(512 * 1024 ** 2,
                        int((model['maximum_buffer_deficit_bytes'] + model['reserve_bytes'])
                            / BUFFER_USABLE_FRACTION + quantum - 1) // quantum * quantum)
        if model['qualified'] and requested <= memory_cap:
            buffer_bytes = requested
            break
        rate -= 1_000_000
    if not buffer_bytes:
        rate = 1_000_000
        buffer_bytes = memory_cap
    model = buffer_analysis(samples, rate, buffer_bytes)
    return {
        'write_rate_bytes_per_second': rate,
        'buffer_bytes': buffer_bytes,
        'buffer_limited_by_memory': requested > memory_cap,
        'observed_minimum_bytes_per_second': minimum,
        'drive_cap_bytes_per_second': drive_cap,
        'system_load_warning': stressed,
        'memory_warning': memory_bytes < 1024 ** 3,
        'buffer_model': model,
        'basis': '5% average headroom; measured peak FIFO deficit plus 15 s reserve; 75% usable buffer',
        'advisory_only': True,
    }


def system_sample(previous: tuple[int, int, int, float], elapsed: float) -> tuple[dict[str, float], tuple[int, int, int, float]]:
    """System-wide CPU busy/I/O wait plus this process's CPU use for one window."""
    fields = [int(value) for value in Path('/proc/stat').read_text().splitlines()[0].split()[1:]]
    total = sum(fields)
    idle = fields[3] + fields[4]
    iowait = fields[4]
    process = time.process_time()
    old_total, old_idle, old_iowait, old_process = previous
    ticks = max(total - old_total, 1)
    values = {
        'system_cpu_percent': max(0.0, min(100.0, 100 * (ticks - (idle - old_idle)) / ticks)),
        'io_wait_percent': max(0.0, min(100.0, 100 * (iowait - old_iowait) / ticks)),
        'process_cpu_percent': max(0.0, 100 * (process - old_process) / max(elapsed, 1e-9)),
        'load1': os.getloadavg()[0],
        'memory_available_bytes': available_memory(),
    }
    return values, (total, idle, iowait, process)


def cpu_snapshot() -> tuple[int, int, int, float]:
    fields = [int(value) for value in Path('/proc/stat').read_text().splitlines()[0].split()[1:]]
    return sum(fields), fields[3] + fields[4], fields[4], time.process_time()


def run_benchmark(catalog: Catalog, root: Path, source: Path, *, seconds: float = MIN_DURATION,
                  min_rate: int = TARGET_RATE, progress: Progress | None = None,
                  _already_locked: bool = False) -> dict[str, Any]:
    if seconds <= 0 or min_rate <= 0:
        raise SafetyError("Benchmark duration and required throughput must be positive")
    if platform.system() != "Linux" or not hasattr(os, "O_DIRECT"):
        raise SafetyError("Qualification benchmark requires Linux O_DIRECT; no cached-read fallback")
    root = root.resolve(strict=True)
    source = Path(os.path.abspath(source))
    if source.is_symlink() or not source.resolve(strict=True).is_relative_to(root):
        raise SafetyError("Benchmark file must be a regular file inside local staging")
    with nullcontext() if _already_locked else io_lock():
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
            report: dict[str, Any] = {"id": ident, "job_id": job, "time": time.time(), "state": "RUNNING", "qualified": False,
                "storage": storage, "source": str(source), "file_bytes": before.st_size,
                "requested_seconds": seconds, "required_rate": min_rate, "direct_io": True}
            with catalog.db:
                catalog.db.execute("INSERT INTO storage_benchmarks VALUES(?,?,?,?)",
                                   (ident, time.time(), str(root), encode(report).decode()))
            started = last = time.monotonic()
            cpu_before = cpu_snapshot()
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
                                load, cpu_before = system_sample(cpu_before, now - last)
                                sample.update(load)
                                samples.append(sample)
                                catalog.event(job, "staging_read_sample", **sample)
                                if progress:
                                    progress({'phase': 'READING', 'duration': seconds,
                                              **sample, 'total_read_bytes': done})
                                window = 0
                                last = now
                            if offset == usable:
                                os.lseek(fd, 0, os.SEEK_SET)
                                offset = 0
                        ended = time.monotonic()
                        if window:
                            sample = {"elapsed": ended - started, "seconds": ended - last,
                                      "bytes": window, "bytes_per_second": window / max(ended - last, 1e-9)}
                            load, cpu_before = system_sample(cpu_before, ended - last)
                            sample.update(load)
                            samples.append(sample)
                            catalog.event(job, "staging_read_sample", **sample)
                            if progress:
                                progress({'phase': 'READING', 'duration': seconds,
                                          **sample, 'total_read_bytes': done})
                    finally:
                        view.release()
                after = os.fstat(fd)
                if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
                        after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns):
                    raise SafetyError("Benchmark input changed during read test")
                elapsed = ended - started
                minimum = min(s["bytes_per_second"] for s in samples)
                recommendation = transfer_recommendation(
                    samples, memory_bytes=min(s['memory_available_bytes'] for s in samples))
                model = buffer_analysis(samples, min_rate, recommendation['buffer_bytes'])
                qualified = (seconds >= MIN_DURATION and elapsed >= MIN_DURATION and before.st_size >= MIN_FILE
                             and min_rate >= TARGET_RATE and model['qualified'])
                report.update(state="COMPLETE", seconds=elapsed, bytes=done, average_rate=done / elapsed,
                              minimum_sample_rate=minimum, samples=samples, qualified=qualified,
                              qualification_version=QUALIFICATION_VERSION, buffer_model=model,
                              average_system_cpu_percent=sum(s['system_cpu_percent'] for s in samples) / len(samples),
                              peak_system_cpu_percent=max(s['system_cpu_percent'] for s in samples),
                              average_io_wait_percent=sum(s['io_wait_percent'] for s in samples) / len(samples),
                              peak_io_wait_percent=max(s['io_wait_percent'] for s in samples),
                              peak_load1=max(s['load1'] for s in samples),
                              load_warning=any(s['system_cpu_percent'] >= 85 or s['io_wait_percent'] >= 30 for s in samples),
                              transfer_recommendation=recommendation,
                              qualification_note="Requires >=1800s, >=10GiB input, >=5% average headroom, measured deficits fitting the buffer with 15s reserve, and recovery within 5s output by test end; no throughput guarantee outside measured conditions")
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


def run_managed_speedtest(catalog: Catalog, root: Path, *, seconds: float = MIN_DURATION,
                          file_bytes: int = TEST_FILE_BYTES, progress: Progress | None = None) -> dict[str, Any]:
    """Create one real local test file, direct-read it, then remove only that file."""
    if (type(seconds) not in (int, float) or type(file_bytes) is not int
            or not 1 <= seconds <= 7200 or not MIN_FILE <= file_bytes <= 100 * 1024 ** 3
            or file_bytes % CHUNK):
        raise SafetyError('Invalid staging speedtest duration or file size')
    root = root.resolve(strict=True)
    with io_lock():
        require_local(root)
        if shutil.disk_usage(root).free < file_bytes + max(1024 ** 3, file_bytes // 10):
            raise SafetyError('Insufficient free local staging space for speedtest and reserve')
        folder = root / '.otam-speedtest'
        if folder.is_symlink():
            raise SafetyError('Unsafe speedtest directory')
        folder.mkdir(mode=0o700, exist_ok=True)
        info = folder.stat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise SafetyError('Speedtest directory must belong exclusively to OTAM')
        if any(folder.iterdir()):
            raise SafetyError('Incomplete prior speedtest fixture: inspect before cleanup')
        ident = str(uuid.uuid4())
        partial = folder / (ident + '.partial')
        ready = folder / (ident + '.bin')
        fd = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        created = time.monotonic()
        last_progress = created
        written = 0
        try:
            while written < file_bytes:
                block = os.urandom(min(CHUNK, file_bytes - written))
                while block:
                    count = os.write(fd, block)
                    if count <= 0:
                        raise SafetyError('Speedtest fixture short write')
                    written += count
                    block = block[count:]
                if progress and (time.monotonic() - last_progress >= 1 or written == file_bytes):
                    progress({'phase': 'PREPARING', 'bytes': written, 'total_bytes': file_bytes,
                              'elapsed': time.monotonic() - created})
                    last_progress = time.monotonic()
            os.fsync(fd)
            info = os.fstat(fd)
            if info.st_blocks * 512 < file_bytes * 0.98:
                raise SafetyError('Speedtest fixture is sparse or filesystem-compressed')
            os.close(fd)
            fd = -1
            os.link(partial, ready)
            partial.unlink()
            result = run_benchmark(catalog, root, ready, seconds=seconds, progress=progress,
                                   _already_locked=True)
            result['managed_fixture_bytes'] = file_bytes
            result['fixture_write_seconds'] = time.monotonic() - created - result['seconds']
            with catalog.db:
                catalog.db.execute('UPDATE storage_benchmarks SET report_json=? WHERE id=?',
                                   (encode(result).decode(), result['id']))
            return result
        finally:
            if fd >= 0:
                os.close(fd)
            # These names were generated for this invocation with O_EXCL. Never touch other files.
            partial.unlink(missing_ok=True)
            ready.unlink(missing_ok=True)


def require_qualification(catalog: Catalog, root: Path) -> None:
    current = require_local(root)
    rows = catalog.db.execute("SELECT report_json FROM storage_benchmarks WHERE root=? ORDER BY time DESC", (str(root.resolve()),))
    for row in rows:
        report = json.loads(row[0])
        storage = report["storage"]
        if (report.get("qualified") and report.get("direct_io")
                and report.get("seconds", 0) >= MIN_DURATION and report.get("required_rate", 0) >= TARGET_RATE
                and report.get("file_bytes", 0) >= MIN_FILE
                and report.get("qualification_version") == QUALIFICATION_VERSION
                and report.get("buffer_model", {}).get("qualified")
                and all(storage[key] == current[key] for key in ("mount", "type", "source", "device"))):
            return
    raise SafetyError("No passing long-duration direct-I/O benchmark for this staging filesystem")
