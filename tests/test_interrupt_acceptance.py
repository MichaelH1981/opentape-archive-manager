"""Small process-death harness checks; never opens physical tape devices."""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from otam.common import SafetyError
from tools.tape_interrupt_acceptance import exit_after_record, refuse_pending, main, FIRST_RECORD, EXIT_CODE
from tests.test_linux_tape_flow import FileST


class InterruptAcceptance(TestCase):
    def test_real_process_exits_after_first_file_record_and_preserves_proof(self):
        with tempfile.TemporaryDirectory(dir=os.environ.get('OTAM_TEST_TMPDIR')) as name:
            root = Path(name).resolve()
            marker = root / 'pending.json'
            marker.write_text('{"test": "software-only"}')
            script = '''
import os,sys
from pathlib import Path
from tools.tape_interrupt_acceptance import exit_after_record,FIRST_RECORD
root=Path(sys.argv[1]); fd=os.open(root/'accepted-record.bin',os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
count=os.write(fd,b'x'*FIRST_RECORD)
def progress(sample):
    (root/'progress.json').write_text(str(sample['bytes']))
exit_after_record(progress,root/'pending.json',root,{'bytes':count})
os.write(fd,b'forbidden second record')
'''
            result = subprocess.run([sys.executable, '-c', script, str(root)], capture_output=True)
            self.assertEqual(result.returncode, EXIT_CODE, result.stderr)
            self.assertEqual((root / 'accepted-record.bin').stat().st_size, FIRST_RECORD)
            self.assertEqual((root / 'progress.json').read_text(), str(FIRST_RECORD))
            proof = json.loads((root / 'crash-proof.json').read_text())
            self.assertEqual(proof['accepted_bytes'], FIRST_RECORD)
            self.assertEqual(marker.read_text(), '{"test": "software-only"}')

    def test_short_progress_never_exits_and_missing_or_symlink_journal_fails(self):
        with tempfile.TemporaryDirectory() as name, patch('os._exit') as exited:
            root = Path(name)
            seen = []
            exit_after_record(seen.append, root / 'absent', root, {'bytes': 10})
            self.assertEqual(seen, [{'bytes': 10}])
            with self.assertRaises(SafetyError):
                exit_after_record(seen.append, root / 'absent', root, {'bytes': FIRST_RECORD})
            (root / 'real').write_text('pending')
            (root / 'link').symlink_to(root / 'real')
            with self.assertRaises(SafetyError):
                exit_after_record(seen.append, root / 'link', root, {'bytes': FIRST_RECORD})
            exited.assert_not_called()

    def test_fresh_real_backend_refuses_pending_without_movement_or_writer(self):
        from otam.tape import LinuxTape
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            drive = {'id': 'drive', 'serial': 'DRIVE', 'medium_serial': 'MAM', 'device': '/dev/nst0'}
            fake = FileST(root, drive)
            with patch('otam.physical.LinuxMaintenance', return_value=fake), patch.object(LinuxTape, '_driver_mode'):
                tape = LinuxTape(drive, root)
                tape._pending.parent.mkdir()
                tape._pending.write_text('uncertain software test')
                reason = refuse_pending(drive, root, root / 'not-opened.tar', 'not-used')
                self.assertIn('uncertain physical tape tail', reason)
                self.assertEqual(fake.position, 0)
                self.assertEqual(fake.files, [])
                self.assertTrue(tape._pending.is_file())

    def test_wrong_destructive_confirmation_fails_before_configuration_or_discovery(self):
        with patch('sys.argv', ['acceptance', '--config', '/absent', '--exchange-root', '/absent',
                  '--report-root', '/absent', '--drive-serial', 'DRIVE', '--medium-serial', 'MAM', '--confirm', 'wrong']), \
                patch('tools.tape_interrupt_acceptance.discover_drives') as discovery:
            with self.assertRaises(SafetyError):
                main()
            discovery.assert_not_called()
