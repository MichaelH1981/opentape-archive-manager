"""Pure software tests. No Linux device nodes are ever opened."""

import errno
import struct
import unittest
from unittest.mock import patch
from otam.common import SafetyError
from otam.physical import mam_serial, qualify, erase, BLOCK_SIZE, test_block, pattern


class MemoryDrive:
    def __init__(self, capacity=4, fault=None):
        self.capacity = capacity
        self.records = []
        self.cursor = 0
        self.fault = fault
        self.calls = []

    def check(self):
        self.calls.append("identity")

    def alerts(self):
        return {"unavailable": "simulated"}

    def mt(self, operation, *args):
        self.calls.append((operation, args))
        if operation == "rewind":
            self.cursor = 0

    def writer(self):
        return 1

    def reader(self):
        if self.fault == "corrupt":
            self.records[1] = b"x" + self.records[1][1:]
        if self.fault == "truncate":
            self.records.pop()
        if self.fault == "extra":
            self.records.append(self.records[-1])
        return 2

    def write(self, fd, block):
        if self.fault == "short":
            return len(block) - 1
        if self.fault == "io":
            raise OSError(errno.EIO, "simulated medium error")
        if len(self.records) == self.capacity:
            raise OSError(errno.ENOSPC, "simulated EOM")
        self.records.append(block)
        return len(block)

    def read(self, fd):
        if self.cursor == len(self.records):
            return b""
        value = self.records[self.cursor]
        self.cursor += 1
        return value

    def close(self, fd):
        if self.fault == "close" and fd == 1:
            raise OSError(errno.EIO, "simulated filemark failure")


class PhysicalBoundary(unittest.TestCase):
    def test_mam_requires_complete_unambiguous_medium_serial(self):
        value = b"CARTRIDGE-123"
        record = b"\x04\x01\x01" + len(value).to_bytes(2, "big") + value
        data = len(record).to_bytes(4, "big") + record
        self.assertEqual(mam_serial(data), "CARTRIDGE-123")
        for invalid in [b"", data[:-1], data[:5], b"\0\0\0\0"]:
            with self.assertRaises(SafetyError):
                mam_serial(invalid)

    def test_fill_and_full_readback_require_eom_matching_counts_and_digest(self):
        progress = []
        device = MemoryDrive()
        with patch("otam.physical.PATTERN_SIZE", 2 * BLOCK_SIZE):
            result = qualify(device, "a" * 64, lambda **v: progress.append(v))
        self.assertEqual(result["state"], "VERIFIED")
        self.assertTrue(result["eom"])
        self.assertEqual(result["bytes"], 4 * BLOCK_SIZE)
        self.assertIn(("compression", ("0",)), device.calls)
        self.assertIn(b"OTAM-QUALIFICATION-V1", device.records[0])
        self.assertTrue(any(p["phase"] == "TAPE_READBACK" for p in progress))
        positioning = next(p for p in progress if p["phase"] == "READBACK_POSITIONING")
        self.assertIsNone(positioning["bytes_per_second"])
        self.assertEqual(positioning["total_bytes"], 4 * BLOCK_SIZE)

    def test_faults_never_qualify_or_blindly_continue(self):
        for fault in ("short", "io", "corrupt", "truncate", "extra", "close"):
            with (
                self.subTest(fault=fault),
                patch("otam.physical.PATTERN_SIZE", 2 * BLOCK_SIZE),
            ):
                with self.assertRaises((SafetyError, OSError)):
                    qualify(MemoryDrive(fault=fault), "a" * 64, lambda **v: None)
        with patch("otam.physical.PATTERN_SIZE", 2 * BLOCK_SIZE):
            with self.assertRaises(SafetyError):
                qualify(
                    MemoryDrive(capacity=100),
                    "a" * 64,
                    lambda **v: None,
                    max_bytes=2 * BLOCK_SIZE,
                )

    def test_reconstruction_detects_record_order_and_content(self):
        with patch("otam.physical.PATTERN_SIZE", 2 * BLOCK_SIZE):
            data = pattern("b" * 64)
            first = test_block(1, "b" * 64, data)
            self.assertNotEqual(first, test_block(2, "b" * 64, data))
            self.assertEqual(first, test_block(1, "b" * 64, pattern("b" * 64)))

    def test_bounded_sample_does_not_claim_full_medium_verification(self):
        with patch("otam.physical.PATTERN_SIZE", 2 * BLOCK_SIZE):
            result = qualify(
                MemoryDrive(capacity=100),
                "a" * 64,
                lambda **v: None,
                sample=True,
                max_bytes=3 * BLOCK_SIZE,
            )
        self.assertEqual(result["state"], "SAMPLE_VERIFIED")
        self.assertFalse(result["eom"])
        self.assertEqual(result["bytes"], 3 * BLOCK_SIZE)
        for fault in ("short", "io", "corrupt", "truncate", "extra", "close"):
            with (
                self.subTest(fault=fault),
                patch("otam.physical.PATTERN_SIZE", 2 * BLOCK_SIZE),
            ):
                with self.assertRaises((SafetyError, OSError)):
                    qualify(
                        MemoryDrive(capacity=100, fault=fault),
                        "a" * 64,
                        lambda **v: None,
                        sample=True,
                        max_bytes=3 * BLOCK_SIZE,
                    )

    def test_bounded_sample_stops_at_time_limit_and_still_reads_back(self):
        import itertools

        with (
            patch("otam.physical.PATTERN_SIZE", 2 * BLOCK_SIZE),
            patch("otam.physical.time.monotonic", side_effect=itertools.count()),
        ):
            result = qualify(
                MemoryDrive(capacity=100),
                "a" * 64,
                lambda **v: None,
                sample=True,
                max_bytes=100 * BLOCK_SIZE,
                write_seconds=1,
            )
        self.assertEqual(result["state"], "SAMPLE_VERIFIED")
        self.assertEqual(result["bytes"], 2 * BLOCK_SIZE)
        self.assertFalse(result["eom"])

    def test_prefetch_never_crosses_filemark_or_declared_read_limit(self):
        from otam.physical import prefetched_records

        calls = []

        class Reader:
            def read(self, fd):
                calls.append(fd)
                if len(calls) > 3:
                    raise AssertionError("Read beyond first filemark")
                return b"record" if len(calls) < 3 else b""

        with prefetched_records(Reader(), 7) as records:
            self.assertEqual(list(records), [b"record", b"record"])
        self.assertEqual(len(calls), 3)
        calls.clear()
        with prefetched_records(Reader(), 7, max_records=1) as records:
            self.assertEqual(list(records), [b"record"])
        self.assertEqual(len(calls), 1)
        with self.assertRaises(SafetyError):
            with prefetched_records(Reader(), 7, max_records=0):
                pass

    def test_prefetch_propagates_read_errors_instead_of_treating_them_as_eof(self):
        from otam.physical import prefetched_records

        for fail_at in (1, 2):

            class Reader:
                calls = 0

                def read(self, fd):
                    self.calls += 1
                    if self.calls == fail_at:
                        raise OSError(errno.EIO, "simulated read failure")
                    return b"record"

            with self.subTest(fail_at=fail_at), self.assertRaises(OSError):
                with prefetched_records(Reader(), 7) as records:
                    list(records)

    def test_prefetch_waits_for_outstanding_read_before_descriptor_can_close(self):
        from otam.physical import prefetched_records
        import threading

        entered = threading.Event()
        release = threading.Event()
        finished = threading.Event()

        class Reader:
            calls = 0

            def read(self, fd):
                self.calls += 1
                if self.calls == 1:
                    return b"first"
                entered.set()
                if not release.wait(2):
                    raise AssertionError("Reader was not released")
                finished.set()
                return b"second"

        timer = threading.Timer(0.02, release.set)
        timer.start()
        try:
            with self.assertRaisesRegex(SafetyError, "consumer failed"):
                with prefetched_records(Reader(), 7) as records:
                    self.assertEqual(next(records), b"first")
                    self.assertTrue(entered.wait(2))
                    raise SafetyError("consumer failed")
            self.assertTrue(finished.is_set())
        finally:
            release.set()
            timer.join()

    def test_vpd_serial_matches_direct_scsi_response(self):
        from otam.physical import inquiry_serial

        self.assertEqual(inquiry_serial(b"\x01\x80\x00\x04ABCD"), "ABCD")
        for invalid in (
            b"",
            b"\x01\x81\x00\x04ABCD",
            b"\x01\x80\x00\x05ABCD",
            b"\x01\x80\x00\x03x\x00x",
        ):
            with self.assertRaises((SafetyError, UnicodeError)):
                inquiry_serial(invalid)

    def test_erase_methods_are_explicit_not_certified_sanitization(self):
        for long in (False, True):
            device = MemoryDrive()
            result = erase(device, long, lambda **v: None)
            self.assertIn(("erase", ("1" if long else "0",)), device.calls)
            self.assertFalse(result["sanitization_certified"])
            self.assertNotEqual(result["state"], "VERIFIED")
