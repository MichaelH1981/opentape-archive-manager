"""Bounded single-reader prefetch; never position or cross the first filemark."""
from __future__ import annotations

import io
import queue
import threading
import time
from typing import Callable


class PrefetchReader(io.RawIOBase):
    """One producer owns reads; close joins it before releasing device ownership.

    A blocked physical read is allowed to finish under the existing kernel
    timeout. No descriptor is closed from a different thread, and no seek can
    race a reader left running after the context manager exits.
    """
    def __init__(self, source: io.RawIOBase, block: int, capacity: int):
        super().__init__()
        if block <= 0 or capacity < block:
            raise ValueError("Invalid prefetch capacity")
        self.source = source
        self.block = block
        self.capacity = capacity // block * block
        self.items = queue.Queue(maxsize=capacity // block)
        self.stop = threading.Event()
        self.finished = threading.Event()
        self.error: BaseException | None = None
        self.pending = memoryview(b'')
        self.received = 0
        self.consumed = 0
        self.started = time.monotonic()
        self.thread = threading.Thread(target=self._produce, name='otam-read-prefetch', daemon=False)
        self.thread.start()

    def _produce(self):
        try:
            while not self.stop.is_set():
                chunk = self.source.read(self.block)
                if not chunk:
                    break  # Latch first filemark: no subsequent source read.
                self.received += len(chunk)
                while not self.stop.is_set():
                    try:
                        self.items.put(chunk, timeout=0.05)
                        break
                    except queue.Full:
                        continue
        except BaseException as error:
            self.error = error
        finally:
            self.finished.set()

    def readable(self):
        return True

    def readinto(self, target):
        if self.closed:
            raise ValueError('Read from closed prefetch stream')
        if not len(target):
            return 0
        while not self.pending:
            try:
                self.pending = memoryview(self.items.get(timeout=0.05))
            except queue.Empty:
                if self.finished.is_set() and self.items.empty():
                    if self.error is not None:
                        raise self.error
                    return 0
        count = min(len(target),len(self.pending))
        target[:count] = self.pending[:count]
        self.pending = self.pending[count:]
        self.consumed += count
        return count

    def metrics(self):
        elapsed = max(time.monotonic()-self.started, 1e-9)
        return {'read_buffer_bytes': self.capacity,
                'read_buffered_bytes': max(0,self.received-self.consumed),
                'reader_bytes_per_second': self.received/elapsed}

    def close(self):
        if not self.closed:
            self.stop.set()
            self.thread.join()
            try:
                self.source.close()
            finally:
                self.pending = memoryview(b'')
                while not self.items.empty():
                    self.items.get_nowait()
                super().close()
