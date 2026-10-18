"""Hardware acceptance harness safety, using only in-memory tape records."""

import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from otam.archive import read_metadata
from otam.common import SafetyError, sha256
from tools.tape_layout_acceptance import Acceptance, fixtures


class RecordTape:
    def __init__(self, fault=None):
        self.expected = {"id": "simulated"}
        self.device = "/never-open-this-device"
        self.files = []
        self.file = 0
        self.cursor = 0
        self.fault = fault
        self.write_count = 0

    def check(self):
        pass

    def mt(self, operation, *args):
        if operation == "rewind":
            self.file = self.cursor = 0

    def writer(self):
        self.pending = []
        return "write"

    def write(self, fd, block):
        self.pending.append(block)
        return len(block) - 1 if self.fault == "short" else len(block)

    def reader(self):
        self.cursor = 0
        return "read"

    def read(self, fd):
        if self.cursor >= len(self.files[self.file]):
            return b""
        block = self.files[self.file][self.cursor]
        self.cursor += 1
        return b"x" + block[1:] if self.fault == "corrupt" else block

    def close(self, fd):
        if fd == "write":
            self.files = self.files[: self.file] + [self.pending]
            self.write_count += 1
        self.file += 1
        self.cursor = 0

    def status(self, _):
        return {"file_number": self.file, "block_number": 0}

    def run(self, args, **kwargs):
        if args[0] == "mt":
            if args[3] == "rewind":
                self.file = 0
            elif args[3] == "fsf":
                self.file += int(args[4])
            elif args[3] == "eod":
                self.file = len(self.files) + (1 if self.fault == "unknown-eod" else 0)
            self.cursor = 0
        return b""


class LayoutHarness(unittest.TestCase):
    def test_append_preserves_prefix_and_receipts_follow_actual_readback(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            archives = fixtures(root / "staged", payload_mib=1)
            self.assertEqual(
                read_metadata(archives[0], "media.json", recovery=True)["class"],
                "rotation",
            )
            self.assertIsNone(read_metadata(archives[2], "receipt.json")["verified_at"])
            tape = RecordTape()
            acceptance = Acceptance(tape, root)
            with (
                patch("tools.tape_layout_acceptance.status", tape.status),
                patch("tools.tape_layout_acceptance.run", tape.run),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                acceptance.execute(archives)
            self.assertEqual(acceptance.report["state"], "LAYOUT_READBACK_VERIFIED")
            self.assertEqual(tape.write_count, 5)
            self.assertEqual(
                [b"".join(v) for v in tape.files], [p.read_bytes() for p in archives]
            )
            self.assertEqual(
                read_metadata(archives[4], "receipt.json")["previous"],
                sha256(archives[2]),
            )
            events = acceptance.report["events"]
            first_read = next(
                i
                for i, e in enumerate(events)
                if e["phase"] == "READBACK_VERIFIED" and e["tape_file"] == 1
            )
            receipt_ready = next(
                i
                for i, e in enumerate(events)
                if e["phase"] == "RECEIPT_READY_AFTER_READBACK" and e["tape_file"] == 2
            )
            self.assertGreater(receipt_ready, first_read)

    def test_corruption_short_write_or_unconfirmed_eod_prevents_success(self):
        for fault in ("corrupt", "short", "unknown-eod"):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                archives = fixtures(root / "staged", payload_mib=1)
                tape = RecordTape(fault)
                acceptance = Acceptance(tape, root)
                with (
                    patch("tools.tape_layout_acceptance.status", tape.status),
                    patch("tools.tape_layout_acceptance.run", tape.run),
                    contextlib.redirect_stdout(io.StringIO()),
                ):
                    with self.assertRaises(SafetyError):
                        acceptance.execute(archives)
                self.assertEqual(acceptance.report["state"], "FAILED_INCOMPLETE")
                self.assertLess(tape.write_count, 4)


class ReadbackProbe(unittest.TestCase):
    def test_prefix_recheck_checks_every_record_and_rejects_early_filemark(self):
        from tools.tape_readback_probe import verify_prefix
        from otam.physical import BLOCK_SIZE, pattern, test_block
        from tests.test_physical import MemoryDrive

        seed = "a" * 64
        with patch("otam.physical.PATTERN_SIZE", 2 * BLOCK_SIZE):
            data = pattern(seed)
            tape = MemoryDrive()
            tape.records = [test_block(i, seed, data) for i in range(4)]
            result = verify_prefix(tape, 2, seed, 3 * BLOCK_SIZE, lambda **v: None)
            self.assertEqual(result["state"], "PREFIX_VERIFIED")
            self.assertEqual(tape.cursor, 3)
            tape.cursor = 0
            tape.records[1] = b"damaged"
            with self.assertRaises(SafetyError):
                verify_prefix(tape, 2, seed, 3 * BLOCK_SIZE, lambda **v: None)
            tape.cursor = 0
            tape.records = [test_block(0, seed, data)]
            with self.assertRaises(SafetyError):
                verify_prefix(tape, 2, seed, 3 * BLOCK_SIZE, lambda **v: None)
