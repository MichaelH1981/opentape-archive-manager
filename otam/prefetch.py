"""Bounded single-reader prefetch; never position or cross the first filemark."""
from __future__ import annotations

import io
import queue
import threading
import time
import operator


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
        self.buffer_peak = 0
        self.consumer_wait_seconds = 0.0
        self.producer_wait_seconds = 0.0
        self.producer_cpu_seconds = 0.0
        self.started = time.monotonic()
        self.thread = threading.Thread(target=self._produce, name='otam-read-prefetch', daemon=False)
        self.thread.start()

    def _produce(self):
        cpu_started = time.thread_time()
        try:
            read_record = getattr(self.source, 'read_record', None)
            while not self.stop.is_set():
                chunk = read_record() if read_record else self.source.read(self.block)
                if not chunk:
                    break  # Latch first filemark: no subsequent source read.
                if not isinstance(chunk, bytes) or len(chunk) > self.block:
                    raise ValueError('Source returned an invalid tape record')
                self.received += len(chunk)
                self.buffer_peak = max(self.buffer_peak, self.received-self.consumed)
                while not self.stop.is_set():
                    started = time.monotonic()
                    try:
                        self.items.put(chunk, timeout=0.05)
                        break
                    except queue.Full:
                        continue
                    finally:
                        self.producer_wait_seconds += time.monotonic()-started
                        self.producer_cpu_seconds = time.thread_time()-cpu_started
        except BaseException as error:
            self.error = error
        finally:
            self.producer_cpu_seconds = time.thread_time()-cpu_started
            self.finished.set()

    def readable(self):
        return True

    def _next(self):
        while not self.pending:
            if self.finished.is_set() and self.items.empty():
                if self.error is not None:
                    raise self.error
                return False
            started = time.monotonic()
            try:
                self.pending = memoryview(self.items.get(timeout=0.05))
            except queue.Empty:
                if self.finished.is_set() and self.items.empty():
                    if self.error is not None:
                        raise self.error
                    return False
            finally:
                self.consumer_wait_seconds += time.monotonic()-started
        return True

    def read(self, size=-1):
        """Keep immutable records; copy only when assembling/slicing a read.

        The TAR parser requests bounded reads. It does not need another
        BufferedReader plus RawIOBase's zero-filled readinto allocation here.
        """
        if self.closed:
            raise ValueError('Read from closed prefetch stream')
        size = -1 if size is None else operator.index(size)
        if size < 0:
            return self.readall()
        if not size:
            return b''
        parts = []
        while size and self._next():
            count = min(size, len(self.pending))
            parts.append(self.pending[:count])
            self.pending = self.pending[count:]
            self.consumed += count
            size -= count
        if len(parts) == 1:
            part = parts[0]
            return part.obj if len(part) == len(part.obj) else part.tobytes()
        return b''.join(parts)

    def readinto(self, target):
        if self.closed:
            raise ValueError('Read from closed prefetch stream')
        if not len(target):
            return 0
        if not self._next():
            return 0
        count = min(len(target),len(self.pending))
        target[:count] = self.pending[:count]
        self.pending = self.pending[count:]
        self.consumed += count
        return count

    def metrics(self):
        elapsed = max(time.monotonic()-self.started, 1e-9)
        device = self.source.metrics() if hasattr(self.source, 'metrics') else {}
        return {**device, 'reader_mode': 'prefetch', 'read_buffer_bytes': self.capacity,
                'read_buffered_bytes': max(0,self.received-self.consumed),
                'read_buffer_peak_bytes': self.buffer_peak,
                'consumer_wait_seconds': self.consumer_wait_seconds,
                'producer_wait_seconds': self.producer_wait_seconds,
                'producer_cpu_seconds': self.producer_cpu_seconds,
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
