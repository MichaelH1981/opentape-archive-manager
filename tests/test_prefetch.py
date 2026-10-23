import io
import threading
import time
from unittest import TestCase
from otam.prefetch import PrefetchReader


class Records(io.RawIOBase):
    def __init__(self, chunks):
        self.chunks=iter(chunks);self.calls=0
    def readable(self):return True
    def read(self, n=-1):
        self.calls+=1
        value=next(self.chunks)
        if isinstance(value,BaseException):raise value
        return value


class PrefetchSafety(TestCase):
    def test_direct_reads_assemble_short_records_and_keep_first_filemark(self):
        source=Records([b'abc',b'de',b'fghi',b'',AssertionError('crossed filemark')])
        with PrefetchReader(source,4,8) as reader:
            self.assertEqual(reader.read(0),b'')
            self.assertEqual(reader.read(4),b'abcd')
            self.assertEqual(reader.read(3),b'efg')
            self.assertEqual(reader.read(),b'hi')
            self.assertEqual(reader.read(100),b'')
            self.assertEqual(reader.metrics()['read_buffered_bytes'],0)
        self.assertEqual(source.calls,4)
        with self.assertRaises(ValueError):reader.read(1)

    def test_record_api_avoids_source_readinto_and_forwards_device_metrics(self):
        class Source(Records):
            def read_record(self):return super().read(4)
            def read(self,n=-1):raise AssertionError('extra source copy')
            def metrics(self):return {'device_read_bytes':4,'reader_mode':'synchronous'}
        source=Source([b'abcd',b''])
        with PrefetchReader(source,4,8) as reader:
            self.assertEqual(reader.read(4),b'abcd')
            self.assertEqual(reader.read(4),b'')
            metrics=reader.metrics()
            self.assertEqual(metrics['device_read_bytes'],4)
            self.assertEqual(metrics['reader_mode'],'prefetch')
            self.assertLessEqual(metrics['read_buffer_peak_bytes'],12)

    def test_direct_reader_propagates_error_without_false_eof(self):
        source=Records([b'abcd',OSError('physical failure')])
        with PrefetchReader(source,4,8) as reader:
            self.assertEqual(reader.read(4),b'abcd')
            with self.assertRaisesRegex(OSError,'physical failure'):reader.read(1)

    def test_invalid_oversized_record_is_not_accepted(self):
        with PrefetchReader(Records([b'too big']),4,8) as reader:
            with self.assertRaisesRegex(ValueError,'invalid tape record'):reader.read(4)

    def test_first_filemark_latched_no_crossing_and_order_preserved(self):
        source=Records([b'abc',b'def',b'',AssertionError('crossed filemark')])
        reader=PrefetchReader(source,4,8)
        with io.BufferedReader(reader,buffer_size=4) as stream:
            self.assertEqual(stream.read(2),b'ab')
            self.assertEqual(stream.read(),b'cdef')
            self.assertEqual(stream.read(),b'')
        self.assertEqual(source.calls,3)
        self.assertFalse(reader.thread.is_alive())

    def test_read_error_reaches_consumer_after_queued_bytes(self):
        source=Records([b'abc',OSError('tape failure')]);reader=PrefetchReader(source,4,8)
        with io.BufferedReader(reader,buffer_size=4) as stream:
            self.assertEqual(stream.read(3),b'abc')
            with self.assertRaisesRegex(OSError,'tape failure'):stream.read()
        self.assertFalse(reader.thread.is_alive())

    def test_close_unblocks_full_queue_and_joins_single_producer(self):
        source=Records([b'abcd']*100);reader=PrefetchReader(source,4,8)
        deadline=time.monotonic()+2
        while not reader.items.full() and time.monotonic()<deadline:time.sleep(.001)
        self.assertTrue(reader.items.full())
        self.assertLessEqual(reader.received,12) # queue plus one in-flight record
        reader.close();self.assertFalse(reader.thread.is_alive())
        self.assertTrue(source.closed)
        with self.assertRaises(ValueError):reader.readinto(bytearray(1))

    def test_close_does_not_release_source_during_an_inflight_read(self):
        entered=threading.Event();release=threading.Event()
        class Blocking(Records):
            def read(self,n=-1):entered.set();release.wait();return b'abcd'
        source=Blocking([]);reader=PrefetchReader(source,4,8)
        self.assertTrue(entered.wait(1))
        closer=threading.Thread(target=reader.close);closer.start()
        time.sleep(.01);self.assertTrue(closer.is_alive());self.assertFalse(source.closed)
        release.set();closer.join(1)
        self.assertFalse(closer.is_alive());self.assertTrue(source.closed)
