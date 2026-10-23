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

    def test_pending_marker_refuses_without_header_reads_or_tape_motion(self):
        self.tape._pending.parent.mkdir()
        self.tape._pending.write_text("interrupted")
        with patch.object(self.tape, "header") as header, \
                patch.object(self.tape, "_move") as move, \
                patch.object(self.tape, "_count") as count:
            with self.assertRaisesRegex(SafetyError, "Incomplete or uncertain"):
                self.tape.append(Path(self.root.name) / "not-needed.tar", "media")
        header.assert_not_called()
        count.assert_not_called()
        move.assert_not_called()
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

    def test_forward_seek_uses_relative_filemarks_and_checks_result(self):
        with patch.object(self.tape, "_count", return_value=9), \
                patch("otam.physical.status", side_effect=[
                    {"file_number": 2, "block_number": 10},
                    {"file_number": 5, "block_number": 0}]), \
                patch.object(self.tape, "_move") as move:
            self.tape._seek(5)
            move.assert_called_once_with("fsf", 3)

    def test_positioning_metrics_count_host_commands_without_claiming_mechanical_moves(self):
        with patch('otam.physical.run'):
            self.tape._move('eod')
            self.tape._move('fsf',3)
            self.tape._move('rewind')
        self.assertEqual(self.tape._positioning_commands,{'eod':1,'fsf':1,'rewind':1})

    def test_unknown_forward_position_keeps_conservative_rewind(self):
        with patch.object(self.tape, "_count", return_value=9), \
                patch("otam.physical.status", side_effect=[
                    {"file_number": -1, "block_number": -1},
                    {"file_number": 5, "block_number": 0}]), \
                patch.object(self.tape, "_move") as move:
            self.tape._seek(5)
            self.assertEqual([call.args for call in move.call_args_list], [("rewind",), ("fsf", 5)])

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

    def test_used_cache_never_overrides_pending_and_invalidates_on_new_eod(self):
        self.tape._count_cache=3
        self.tape._used_cache=(3,12345)
        with patch.object(self.tape,'read') as read:
            self.assertEqual(self.tape.used(),12345)
            read.assert_not_called()
        self.tape._pending.parent.mkdir()
        self.tape._pending.write_text('uncertain')
        with patch.object(self.tape,'header',return_value={'capacity':800000000000}):
            self.assertEqual(self.tape.used(),800000000000)
        with patch.object(self.tape,'_move'),patch('otam.physical.status',return_value={
                'eod':True,'file_number':5,'block_number':-1}):
            self.assertEqual(self.tape._count(force=True),5)
        self.assertIsNone(self.tape._used_cache)

    def test_used_cache_is_discarded_when_exclusive_session_ends(self):
        from contextlib import nullcontext
        self.tape._locked=False
        with patch.object(self.device,'locked',return_value=nullcontext()):
            with self.tape.locked():
                self.tape._used_cache=(3,12345)
        self.assertIsNone(self.tape._used_cache)
        self.assertIsNone(self.tape._count_cache)

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
    def test_prefetch_budget_metadata_and_safe_synchronous_fallback(self):
        with TemporaryDirectory() as folder:
            path=Path(folder)/'data';path.write_bytes(b'payload'*1000)
            for enabled,memory,position,mode in ((True,8*1024**3,1,'prefetch'),
                    (False,8*1024**3,1,'synchronous'),(True,64*1024**2,1,'synchronous'),
                    (True,8*1024**3,0,'synchronous'),(True,None,1,'synchronous')):
                with self.subTest(enabled=enabled,memory=memory,position=position):
                    device=Mock();fd=os.open(path,os.O_RDONLY);device.reader.return_value=fd
                    with patch('otam.physical.LinuxMaintenance',return_value=device):
                        tape=LinuxTape(DRIVE,Path(folder),read_ahead=enabled)
                    with patch.object(tape,'_seek'),patch('otam.benchmark.available_memory',
                            return_value=memory,side_effect=SafetyError('unknown memory') if memory is None else None) as available:
                        with tape.open_read(position) as stream:
                            self.assertEqual(stream.read(),b'payload'*1000)
                            metrics=tape.read_metrics();self.assertEqual(metrics['reader_mode'],mode)
                            self.assertGreaterEqual(metrics['consumer_cpu_seconds'],0)
                            if mode=='prefetch':self.assertLessEqual(metrics['read_buffer_bytes'],64*1024**2)
                        if not enabled or position==0:available.assert_not_called()
                    with self.assertRaises(OSError):os.fstat(fd)

    def test_direct_record_after_partial_read_preserves_remainder_and_eof(self):
        with patch('otam.tape.os.read',side_effect=[b'abcdef',b'',AssertionError('next tape file')]) as read, \
                patch('otam.tape.os.close'):
            with TapeRecordReader(123) as raw:
                out=bytearray(2);self.assertEqual(raw.readinto(out),2)
                self.assertEqual(out,b'ab')
                self.assertEqual(raw.read_record(),b'cdef')
                self.assertEqual(raw.read_record(),b'')
                self.assertEqual(raw.read_record(),b'')
                self.assertEqual(read.call_count,2)
    def test_payload_context_checks_full_archive_and_closes_at_first_filemark(self):
        import hashlib
        from otam.common import BLOCK
        with TemporaryDirectory() as folder:
            path = Path(folder) / "metadata.tar"
            # A valid metadata TAR is sufficient to exercise the physical
            # stream boundary; inspect its bytes without asking for payloads.
            metadata_tar(path, "proof.json", {"message": "boundary proof"})
            data = path.read_bytes()
            device = Mock()
            device.reader.return_value = 123
            with patch("otam.physical.LinuxMaintenance", return_value=device):
                tape = LinuxTape(DRIVE, Path(folder))
            with patch.object(tape, "_seek") as seek, \
                    patch("otam.tape.os.read", side_effect=[data, b"", AssertionError("crossed filemark")]) as read, \
                    patch("otam.tape.os.close") as close:
                with tape.open_read(1) as incoming:
                    hasher = hashlib.sha256()
                    while chunk := incoming.read(257):
                        hasher.update(chunk)
                    self.assertEqual(incoming.read(BLOCK), b"")
                    self.assertEqual(hasher.hexdigest(), hashlib.sha256(data).hexdigest())
                    metrics = tape.read_metrics()
                    self.assertEqual(metrics['device_read_bytes'], len(data))
                    self.assertEqual(metrics['device_read_calls'], 2)
                    self.assertGreaterEqual(metrics['device_read_seconds'], 0)
                    self.assertGreaterEqual(metrics['reader_elapsed_seconds'], metrics['device_read_seconds'])
                    close.assert_not_called()
                seek.assert_called_once_with(1)
                self.assertEqual(read.call_count, 2)
                close.assert_called_once_with(123)
                self.assertEqual(tape.read_metrics(), {})

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
