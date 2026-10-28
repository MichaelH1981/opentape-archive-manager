"""Low-frequency worker counters; no devices, subprocesses or sample history."""
from __future__ import annotations

import os
import time
from pathlib import Path


class Sampler:
    def __init__(self):
        self.cpu_count = os.cpu_count() or 1
        self.previous = None

    def sample(self):
        now, cpu = time.monotonic(), time.process_time()
        host = None
        try:
            with Path('/proc/stat').open() as stream:
                fields = stream.readline().split()
            if fields[0] == 'cpu':
                host = tuple(int(v) for v in fields[1:9])
                if len(host) != 8:
                    host = None
        except (OSError, ValueError, IndexError):
            pass  # Linux counters are optional; process CPU works on macOS too.
        result = {'time': time.time(), 'interval_seconds': None,
                  'cpu_count': self.cpu_count, 'worker_cpu_percent': None,
                  'host_cpu_percent': None, 'host_iowait_percent': None}
        if self.previous:
            then, previous_cpu, previous_host = self.previous
            elapsed = now - then
            if elapsed > 0:
                result['interval_seconds'] = elapsed
                result['worker_cpu_percent'] = max(0, 100 * (cpu - previous_cpu) / elapsed)
                if host is not None and previous_host is not None:
                    delta = [v - u for u, v in zip(previous_host, host)]
                    total = sum(delta)
                    if total > 0 and min(delta) >= 0:
                        result['host_cpu_percent'] = 100 * (total - delta[3] - delta[4]) / total
                        result['host_iowait_percent'] = 100 * delta[4] / total
        self.previous = (now, cpu, host)
        return result


def publish(control, sampler):
    """Reuse the heartbeat transaction; one small record overwritten every 5s."""
    import json
    sample = sampler.sample()
    with control.connect() as db:
        db.executemany(
            'INSERT INTO settings VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
            [('worker_heartbeat', json.dumps(sample['time'])),
             ('worker_telemetry', json.dumps(sample))])


def snapshot(control, heartbeat):
    sample = control.get('worker_telemetry')
    if not isinstance(sample, dict):
        return None
    now = time.time()
    return {**sample, 'fresh': (0 <= now - sample.get('time', 0) <= 20
                               and 0 <= now - heartbeat <= 20)}
