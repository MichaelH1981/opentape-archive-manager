"""Physical-backend safety checks with no real device access."""

import io
import os
from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, patch

from otam.common import FORMAT, SafetyError
from otam.archive import metadata_tar
from otam.tape import LinuxTape, TapeRecordReader


DRIVE = {"id": "test-drive", "device": "/dev/nst0", "serial": "DRIVE-1",
         "medium_serial": "CARTRIDGE-1", "sg": "/dev/sg0"}


class LinuxTapeSafety(TestCase):
    def setUp(self):
        self.root = TemporaryDirectory()
        self.addCleanup(self.root.cleanup)
        self.device = Mock()
        self.device.expected = DRIVE
        self.device.device = DRIVE["device"]
        with patch("otam.physical.LinuxMaintenance", return_value=self.device):
            self.tape = LinuxTape(DRIVE, Path(self.root.name))
        self.tape._locked = True
        mode = patch.object(self.tape, "_driver_mode")
        mode.start()
        self.addCleanup(mode.stop)

    def test_even_file_count_after_restart_blocks_append_before_open(self):
        source = Path(self.root.name) / "receipt.tar"
        source.write_bytes(b"placeholder")
        with patch.object(self.tape, "header", return_value={
                "format": FORMAT, "media_id": "media", "capacity": 800_000_000_000}), \
                patch.object(self.tape, "_count", return_value=2):
            with self.assertRaisesRegex(SafetyError, "Incomplete or uncertain"):
                self.tape.append(source, "media")
        self.device.writer.assert_not_called()

    def test_pending_marker_blocks_even_a_complete_file_count(self):
        self.tape._pending.parent.mkdir()
        self.tape._pending.write_text("interrupted")
        with patch.object(self.tape, "_count", return_value=3):
            self.assertTrue(self.tape.has_partial())
        with patch.object(self.tape, "header", return_value={
                "format": FORMAT, "media_id": "media", "capacity": 800_000_000_000}), \
                patch.object(self.tape, "_count", return_value=3):
            with self.assertRaisesRegex(SafetyError, "Incomplete or uncertain"):
                self.tape.append(Path(self.root.name) / "unused.tar", "media")
        self.device.writer.assert_not_called()

    def test_unconfirmed_seek_does_not_open_reader(self):
        with patch.object(self.tape, "_count", return_value=3), \
                patch("otam.physical.status", return_value={
                    "file_number": 1, "block_number": -1}), \
                patch.object(self.tape, "_move"):
            with self.assertRaisesRegex(SafetyError, "unconfirmed"):
                with self.tape.open_read(1):
                    pass
        self.device.reader.assert_not_called()

    def test_identity_is_required_before_positioning(self):
        self.tape._locked = False
        with self.assertRaisesRegex(SafetyError, "Device lock"):
            self.tape.positions()
        self.device.check.assert_not_called()

    def test_old_device_path_api_remains_disabled(self):
        with self.assertRaises(SafetyError):
            LinuxTape(Path("/dev/nst0"))

    def test_initialization_requires_exact_cartridge_serial(self):
        with self.assertRaisesRegex(SafetyError, "MAM-bound"):
            self.tape.initialize("Test", 800_000_000_000, "rotation", "INITIALIZE OTHER")
        self.device.writer.assert_not_called()

    def transfer(self, *, short=False):
        """Exercise the real append state machine with an inert producer/fd."""
        source = Path(self.root.name) / "source.tar"
        source.write_bytes(b"p" * 10240)
        source.chmod(0o400)
        target = Path(self.root.name) / "inert-output"
        self.device.writer.return_value = os.open(target, os.O_CREAT | os.O_WRONLY, 0o600)
        producer = Mock()
        producer.stdout = io.BytesIO(b"p" * 10240)
        producer.poll.return_value = None if short else 0
        producer.wait.return_value = 0
        context = Mock()
        context.__enter__ = Mock(return_value=producer)
        context.__exit__ = Mock(return_value=False)
        with ExitStack() as stack:
            stack.enter_context(patch.object(self.tape, "header", return_value={
                "media_id": "media", "capacity": 1_000_000}))
            stack.enter_context(patch.object(self.tape, "_count", return_value=1))
            stack.enter_context(patch.object(self.tape, "used", return_value=10240))
            stack.enter_context(patch("otam.physical.status", side_effect=[
                {"eod": True, "file_number": 1, "block_number": -1, "write_protected": False},
                {"file_number": 2, "block_number": 0}]))
            stack.enter_context(patch("subprocess.Popen", return_value=context))
            stack.enter_context(patch("otam.storage.require_local"))
            stack.enter_context(patch("otam.benchmark.available_memory", return_value=8 * 1024**3))
            writer = stack.enter_context(patch("otam.tape.os.write", return_value=1 if short else 10240))
            if short:
                with self.assertRaisesRegex(SafetyError, "Short physical"):
                    self.tape.append(source, "media")
            else:
                self.assertEqual(self.tape.append(source, "media"), 1)
            self.assertEqual(writer.call_count, 1)
        return producer

    def test_short_write_is_not_retried_and_survives_restart(self):
        producer = self.transfer(short=True)
        self.assertTrue(self.tape._pending.exists())
        producer.terminate.assert_called_once()
        self.assertIsNone(self.tape._next_receipt)

    def test_successful_data_write_permits_only_same_process_receipt(self):
        producer = self.transfer()
        self.assertFalse(self.tape._pending.exists())
        self.assertEqual(self.tape._next_receipt, 2)
        self.assertEqual(self.tape._pending_used, 20480)
        producer.terminate.assert_not_called()

    def test_unaccepted_driver_filemark_and_nowait_modes_are_rejected(self):
        for flag in (0x10, 0x20, 0x1000, 0x2000, 0x8000):
            with patch.object(Path, "read_text", return_value=hex(0x107 | flag)):
                with self.assertRaisesRegex(SafetyError, "filemark/EOF mode"):
                    LinuxTape._driver_mode(self.tape)
        with patch.object(Path, "read_text", return_value="0x00000107"):
            LinuxTape._driver_mode(self.tape)

    def test_receipt_cannot_commit_a_different_data_checksum(self):
        self.transfer()
        receipt = Path(self.root.name) / "wrong-receipt.tar"
        metadata_tar(receipt, "receipt.json", {"media_id": "media", "tape_file": 1,
                     "bytes": 10240, "sha256": "0" * 64})
        self.device.writer.reset_mock()
        with patch.object(self.tape, "header", return_value={"media_id": "media"}), \
                patch.object(self.tape, "_count", return_value=2):
            with self.assertRaisesRegex(SafetyError, "Receipt differs"):
                self.tape.append(receipt, "media")
        self.device.writer.assert_not_called()

    def test_eod_count_is_cached_only_inside_lock_and_force_rechecks(self):
        with patch.object(self.tape, "_move") as move, patch("otam.physical.status", return_value={
                "eod": True, "file_number": 3, "block_number": -1}):
            self.assertEqual(self.tape._count(), 3)
            self.assertEqual(self.tape._count(), 3)
            move.assert_called_once_with("eod")
            self.assertEqual(self.tape._count(force=True), 3)
            self.assertEqual(move.call_count, 2)

    def test_supported_dropdown_rate_prefill_and_log_reach_mbuffer(self):
        expected = {**DRIVE, "vendor": "IBM", "model": "ULT3580-HH4",
                    "status": {"online": True, "density_code": 0x46}}
        with patch("otam.physical.LinuxMaintenance", return_value=self.device):
            for rate in (30, 48, 66, 84, 103, 120):
                tape = LinuxTape(expected, Path(self.root.name), buffer_mib=2368,
                                 write_rate=rate * 1_000_000)
                command = tape._mbuffer_command(123, Path(self.root.name) / "status.log")
                self.assertEqual(command[command.index("-R") + 1], str(rate * 1_000_000))
                self.assertEqual(command[command.index("-P") + 1], "90")
                self.assertEqual(command[command.index("-m") + 1], "2368M")
                self.assertIn("-l", command)
            with self.assertRaises(SafetyError):
                LinuxTape(expected, Path(self.root.name), write_rate=80_000_000)
            with self.assertRaises(SafetyError):
                LinuxTape(DRIVE, Path(self.root.name), write_rate=120_000_000)

    def test_live_buffer_log_uses_last_sample_and_rejects_invalid_values(self):
        log = Path(self.root.name) / "buffer.log"
        log.write_bytes(b"mbuffer: buffer  88% full\nmbuffer: buffer   9% full\n")
        self.assertEqual(self.tape._buffer_percent(log), 9.0)
        log.write_bytes(b"mbuffer: buffer 101% full\n")
        self.assertIsNone(self.tape._buffer_percent(log))
        log.write_bytes(b"summary without a status sample\n")
        self.assertIsNone(self.tape._buffer_percent(log))

    def test_low_memory_refuses_before_opening_tape_or_creating_pending_marker(self):
        source = Path(self.root.name) / "ready.tar"
        source.write_bytes(b"x" * 10240)
        source.chmod(0o400)
        with patch.object(self.tape, "header", return_value={"media_id": "media"}), \
                patch.object(self.tape, "_count", return_value=1), \
                patch("otam.storage.require_local"), \
                patch("otam.benchmark.available_memory", return_value=256 * 1024**2):
            with self.assertRaisesRegex(SafetyError, "available RAM"):
                self.tape.append(source, "media")
        self.device.writer.assert_not_called()
        self.assertFalse(self.tape._pending.exists())


class TapeRecordReads(TestCase):
    def test_small_reads_receive_large_records_and_never_cross_filemark(self):
        records = [b"a" * (512 * 1024), b"b" * 10240, b"", b"NEXT TAPE FILE"]
        with patch("otam.tape.os.read", side_effect=records) as read, \
                patch("otam.tape.os.close") as close:
            with io.BufferedReader(TapeRecordReader(123), buffer_size=1024**2) as incoming:
                payload = bytearray()
                while chunk := incoming.read(10240):
                    payload.extend(chunk)
                self.assertEqual(bytes(payload), records[0] + records[1])
                self.assertEqual(incoming.read(10240), b"")
                self.assertEqual(incoming.read(), b"")
                self.assertEqual(read.call_count, 3)
                self.assertTrue(all(call.args == (123, 1024**2) for call in read.call_args_list))
            close.assert_called_once_with(123)

    def test_read_error_propagates_instead_of_becoming_eof(self):
        with patch("otam.tape.os.read", side_effect=OSError("medium read failure")), \
                patch("otam.tape.os.close"):
            with io.BufferedReader(TapeRecordReader(123), buffer_size=1024**2) as incoming:
                with self.assertRaisesRegex(OSError, "medium read failure"):
                    incoming.read(10240)
