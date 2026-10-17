from __future__ import annotations

import io
import json
import os
import platform
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from otam.archive import create_archive, verify_stream
from otam.benchmark import require_qualification, run_benchmark
from otam.catalog import Catalog, SCHEMA
from otam.cli import main
from otam.common import SafetyError, sha256
from otam.service import ArchiveService
from otam.staging import StagingStore
from otam.storage import filesystem, io_lock, require_local, local_block_device
from otam.tape import SimulatedTape
from tests import test_workflows as fixtures


class Staging(unittest.TestCase):
    setUp = fixtures.Workflows.setUp
    tearDown = fixtures.Workflows.tearDown

    def plan(self, target=75000000000):
        return self.service.plan(self.source, self.media, target)

    def rows(self, job):
        return [dict(r) for r in self.catalog.db.execute("SELECT * FROM staged_archives WHERE job_id=? ORDER BY archive_id", (job,))]

    def test_prepared_archive_survives_restart_and_missing_source(self):
        plan = self.plan()
        self.service.stage(plan['job_id'], self.spool)
        row = self.rows(plan['job_id'])[0]
        path = Path(row['path'])
        self.assertEqual(row['phase'], 'READY')
        self.assertEqual(row['state'], 'COMPLETE')
        self.assertEqual(path.stat().st_mode & 0o222, 0)
        checksum = sha256(path)
        shutil.rmtree(self.source)  # Only this test's synthetic temporary source.
        self.catalog.close()
        self.catalog = Catalog(self.base/'catalog.sqlite')
        self.service = ArchiveService(self.catalog, SimulatedTape(self.tape.path))
        self.assertEqual(sha256(path), checksum)
        result = self.service.backup(plan['job_id'], plan['job_id'], self.spool)
        self.assertEqual(result['state'], 'VERIFIED')
        self.assertFalse(path.exists())
        self.assertEqual(self.rows(plan['job_id'])[0]['phase'], 'STAGING_CLEANUP')

    def test_incomplete_staging_is_retained_and_restarted_without_overwrite(self):
        plan = self.plan()
        def interrupted(path, root, manifest, progress=None):
            path.write_bytes(b'incomplete TAR')
            raise KeyboardInterrupt('staging interrupted')
        with patch('otam.staging.create_archive', side_effect=interrupted):
            with self.assertRaises(KeyboardInterrupt):
                self.service.stage(plan['job_id'], self.spool)
        first = self.rows(plan['job_id'])[0]
        old = Path(first['path'])
        self.assertTrue(old.exists())
        self.assertEqual(first['state'], 'INTERRUPTED')
        self.assertEqual(self.catalog.db.execute('SELECT state FROM media').fetchone()[0], 'READY')
        self.service.stage(plan['job_id'], self.spool)
        self.assertEqual(old.read_bytes(), b'incomplete TAR')
        self.service.backup(plan['job_id'], plan['job_id'], self.spool)
        self.assertFalse(old.exists())  # Managed obsolete attempts are removed only after VERIFIED.

    def test_failed_write_retains_ready_archive_and_blocks_blind_resume(self):
        plan = self.plan()
        faulty = SimulatedTape(self.tape.path, fail_after=700)
        with self.assertRaises(OSError):
            ArchiveService(self.catalog, faulty).backup(plan['job_id'], plan['job_id'], self.spool)
        row = self.rows(plan['job_id'])[0]
        self.assertTrue(Path(row['path']).is_file())
        self.assertEqual(sha256(Path(row['path'])), row['sha256'])
        with self.assertRaises(SafetyError):
            self.service.backup(plan['job_id'], plan['job_id'], self.spool, resume=True)
        self.assertTrue(Path(row['path']).exists())

    def test_explicit_resume_rechecks_committed_pair_without_rewriting(self):
        plan = self.plan(target=1000)
        original = self.tape.append
        def crash_after_receipt(path, media):
            position = original(path, media)
            if path.name.startswith('receipt-'):
                raise SystemExit('crash after receipt before catalog commit')
            return position
        with patch.object(self.tape, 'append', side_effect=crash_after_receipt):
            with self.assertRaises(SystemExit):
                self.service.backup(plan['job_id'], plan['job_id'], self.spool)
        with self.tape.locked():
            first_hash = sha256(self.tape.read(1))
            self.assertEqual(self.tape.positions(), [0,1,2])
        self.assertEqual(self.service.backup(plan['job_id'], plan['job_id'], self.spool, resume=True)['state'], 'VERIFIED')
        with self.tape.locked():
            self.assertEqual(self.tape.positions(), [0,1,2,3,4,5,6])
            self.assertEqual(sha256(self.tape.read(1)), first_hash)
        self.assertEqual(self.catalog.db.execute('SELECT writes FROM media').fetchone()[0], 3)

    def test_stream_verification_never_materializes_a_second_data_tar(self):
        plan = self.plan()
        original_read = self.tape.read
        original_open = self.tape.open_read
        from contextlib import contextmanager
        def metadata_only(position):
            if position % 2 == 1:
                raise AssertionError('Data TAR must be consumed via streaming API')
            return original_read(position)
        @contextmanager
        def incoming(position):
            with original_read(position).open('rb') as stream:
                yield stream
        with patch.object(self.tape, 'read', side_effect=metadata_only), patch.object(self.tape, 'open_read', side_effect=incoming):
            self.service.backup(plan['job_id'], plan['job_id'], self.spool)
            self.assertEqual(self.service.verify(self.media)['state'], 'VERIFIED')

    def test_failed_readback_retains_original_tar(self):
        plan = self.plan()
        with self.assertRaises(OSError):
            ArchiveService(self.catalog, SimulatedTape(self.tape.path, read_error=1)).backup(plan['job_id'], plan['job_id'], self.spool)
        row = self.rows(plan['job_id'])[0]
        self.assertEqual(row['phase'], 'TAPE_READBACK')
        self.assertTrue(Path(row['path']).is_file())
        with self.assertRaises(SafetyError):
            StagingStore(self.catalog, self.spool).cleanup(plan['job_id'], row['archive_id'])

    def test_ready_tar_tampering_is_detected_before_any_tape_write(self):
        plan = self.plan()
        self.service.stage(plan['job_id'], self.spool)
        row = self.rows(plan['job_id'])[0]
        data = Path(row['path'])
        data.chmod(0o600)
        with data.open('r+b') as output:
            output.seek(1000)
            output.write(b'tamper')
        data.chmod(0o400)
        with self.assertRaises(SafetyError):
            self.service.backup(plan['job_id'], plan['job_id'], self.spool)
        with self.tape.locked():
            self.assertEqual(self.tape.positions(), [0])
        self.assertTrue(data.exists())

    def test_cleanup_preserves_unmanaged_files_and_replaced_artifacts(self):
        plan = self.plan()
        self.service.stage(plan['job_id'], self.spool)
        row = self.rows(plan['job_id'])[0]
        data = Path(row['path'])
        personal = data.parent/'personal.txt'
        personal.write_text('not OTAM owned')
        self.service.backup(plan['job_id'], plan['job_id'], self.spool)
        self.assertEqual(personal.read_text(), 'not OTAM owned')
        self.assertFalse(data.exists())

    def test_cleanup_refuses_artifact_replaced_by_symlink(self):
        plan = self.plan()
        self.service.stage(plan['job_id'], self.spool)
        row = self.rows(plan['job_id'])[0]
        path = Path(row['path'])
        # Emulate a verified archive but retain staging for ownership protection test.
        self.catalog.record_archive(plan['archives'][0], plan['job_id'], 1, 'VERIFIED', row['bytes'], row['sha256'])
        outside = self.base/'outside'
        outside.write_text('keep')
        path.unlink()
        path.symlink_to(outside)
        with self.assertRaises(SafetyError):
            StagingStore(self.catalog, self.spool).cleanup(plan['job_id'], row['archive_id'])
        self.assertEqual(outside.read_text(), 'keep')

    def test_space_is_checked_before_source_reads_and_before_each_archive(self):
        plan = self.plan(target=1000)
        original = __import__('otam.staging', fromlist=['require_local']).require_local
        def no_space(path):
            return {**original(path), 'free': 0}
        with patch('otam.staging.require_local', side_effect=no_space):
            with self.assertRaises(SafetyError), patch('otam.staging.create_archive') as create:
                self.service.backup(plan['job_id'], plan['job_id'], self.spool)
            create.assert_not_called()
        with self.tape.locked():
            self.assertEqual(self.tape.positions(), [0])

    def test_sequential_staging_does_not_require_full_band_capacity(self):
        plan = self.plan(target=1000)
        # Enough for one archive, not the complete plan.
        original = __import__('otam.staging', fromlist=['require_local']).require_local
        def constrained(path):
            return {**original(path), 'free': 42000}
        with patch('otam.staging.require_local', side_effect=constrained):
            self.assertEqual(self.service.backup(plan['job_id'], plan['job_id'], self.spool)['state'], 'VERIFIED')
        self.assertTrue(all(r['state'] == 'COMPLETE' for r in self.rows(plan['job_id'])))

    def test_prepare_all_finishes_before_first_tape_write(self):
        plan = self.plan(target=1000)
        original = self.tape.append
        count = 0
        def append(path, media):
            nonlocal count
            if count == 0:
                self.assertEqual(sum(Path(r['path']).is_file() for r in self.rows(plan['job_id'])), 3)
            count += 1
            return original(path, media)
        with patch.object(self.tape, 'append', side_effect=append):
            self.service.backup(plan['job_id'], plan['job_id'], self.spool, prepare_all=True)
        self.assertEqual(count, 6)

    def test_io_lock_blocks_all_staging_and_tape_operations(self):
        plan = self.plan()
        with io_lock():
            with self.assertRaises(SafetyError):
                self.service.stage(plan['job_id'], self.spool)
            with self.assertRaises(SafetyError):
                self.service.backup(plan['job_id'], plan['job_id'], self.spool)

    def test_network_unknown_and_ram_filesystems_rejected(self):
        for kind in ('nfs', 'nfs4', 'cifs', 'fuse.sshfs', 'tmpfs', 'overlay', 'unknown'):
            with self.subTest(kind=kind), patch('otam.storage.filesystem', return_value={'local': False, 'read_only': False, 'type': kind}):
                with self.assertRaises(SafetyError):
                    require_local(self.base)
        # A nested NFS mount wins over its local ancestor; escaped mountpoint names are decoded.
        info = '1 0 8:1 / / rw - ext4 /dev/sda1 rw\n2 1 0:1 / /srv/staging\\040data rw - nfs nas:/share rw\n'
        with patch('otam.storage.platform.system', return_value='Linux'), patch('pathlib.Path.read_text', return_value=info), patch('pathlib.Path.resolve', return_value=Path('/srv/staging data/sub')), patch('otam.storage.os.stat') as st, patch('otam.storage.shutil.disk_usage', return_value=(100, 20, 80)):
            st.return_value.st_dev = 1
            result = filesystem(Path('/srv/staging data/sub'))
        self.assertEqual(result['type'], 'nfs')
        self.assertFalse(result['local'])

    def test_linux_local_block_chain_rejects_network_and_opaque_devices(self):
        sysfs = self.base/'sysfs'
        sysfs.mkdir()
        for index, target in enumerate(('devices/pci0000/ata1/block/sda/sda2',
                                        'devices/pci0000/host7/session2/target/block/sdb',
                                        'devices/virtual/block/loop0', 'devices/virtual/block/nbd0')):
            directory = self.base/target
            directory.mkdir(parents=True)
            (sysfs/f'8:{index}').symlink_to(directory, target_is_directory=True)
        self.assertTrue(local_block_device('8:0', sysfs))
        for minor in (1,2,3):
            self.assertFalse(local_block_device(f'8:{minor}', sysfs))
        self.assertFalse(local_block_device('99:99', sysfs))
        dm = self.base/'devices/virtual/block/dm-0'
        (dm/'slaves').mkdir(parents=True)
        (dm/'slaves'/'sda2').symlink_to(self.base/'devices/pci0000/ata1/block/sda/sda2')
        (sysfs/'253:0').symlink_to(dm)
        self.assertTrue(local_block_device('253:0', sysfs))
        (dm/'slaves'/'remote').symlink_to(self.base/'devices/virtual/block/nbd0')
        self.assertFalse(local_block_device('253:0', sysfs))

    def test_stream_readback_hashes_padding_and_detects_truncation(self):
        plan = self.plan()
        data = self.base/'stream.tar'
        create_archive(data, self.source, plan['archives'][0])
        content = data.read_bytes()
        self.assertEqual(verify_stream(io.BytesIO(content), sha256(data), len(content))['archive_id'], plan['archives'][0]['archive_id'])
        for bad in (content[:-512], content + b'trailing bytes', content[:-1] + b'x'):
            with self.assertRaises(SafetyError):
                verify_stream(io.BytesIO(bad), sha256(data), len(content))

    def test_write_and_readback_phases_persist_and_original_exists_until_verified(self):
        plan = self.plan()
        original_read = self.tape.open_read
        from contextlib import contextmanager
        @contextmanager
        def read(position):
            if position == 1:
                row = self.rows(plan['job_id'])[0]
                self.assertTrue(Path(row['path']).is_file())
                self.assertEqual(row['phase'], 'TAPE_READBACK')
            with original_read(position) as stream:
                yield stream
        with patch.object(self.tape, 'open_read', side_effect=read):
            self.service.backup(plan['job_id'], plan['job_id'], self.spool)
        phases = [json.loads(r[0])['phase'] for r in self.catalog.db.execute("SELECT details_json FROM events WHERE job_id=? AND event='archive_phase' ORDER BY seq", (plan['job_id'],))]
        for phase in ('STAGING','VALIDATION','READY','TAPE_WRITE','TAPE_READBACK','VERIFIED','STAGING_CLEANUP'):
            self.assertIn(phase, phases)
        metrics = self.catalog.db.execute("SELECT details_json FROM events WHERE event='io_progress'").fetchall()
        self.assertTrue(any(json.loads(r[0])['phase'] == 'TAPE_WRITE' for r in metrics))
        self.assertTrue(any(json.loads(r[0])['phase'] == 'TAPE_READBACK' for r in metrics))

    def test_publication_crash_is_recovered_from_durable_intent(self):
        plan = self.plan()
        original = Path.unlink
        def fail_unlink(path, *args, **kwargs):
            if path.suffix == '.partial' and (path.parent/'ready.tar').exists():
                raise KeyboardInterrupt('publication crash')
            return original(path, *args, **kwargs)
        with patch('pathlib.Path.unlink', fail_unlink):
            with self.assertRaises(KeyboardInterrupt):
                self.service.stage(plan['job_id'], self.spool)
        row = self.rows(plan['job_id'])[0]
        self.assertIsNone(row['fingerprint_json'])
        self.service.stage(plan['job_id'], self.spool)
        self.assertEqual(self.rows(plan['job_id'])[0]['phase'], 'READY')
        self.service.backup(plan['job_id'], plan['job_id'], self.spool)

    def test_v1_catalog_migrates_without_losing_media(self):
        path = self.base/'v1.sqlite'
        db = sqlite3.connect(path)
        db.executescript(SCHEMA)
        db.execute("INSERT INTO media(id,label,class,capacity,header_json) VALUES('existing','keep','permanent',123,'{}')")
        db.commit()
        db.close()
        upgraded = Catalog(path)
        try:
            self.assertEqual(upgraded.db.execute('PRAGMA user_version').fetchone()[0], 2)
            self.assertEqual(upgraded.db.execute('SELECT label FROM media').fetchone()[0], 'keep')
            self.assertEqual(upgraded.export()['staged_archives'], [])
        finally:
            upgraded.close()

    def test_cli_stage_has_no_tape_dependency_and_status_shows_capacity(self):
        plan = self.plan()
        output = io.StringIO()
        with patch('sys.stdout', output):
            self.assertEqual(main(['--db', str(self.catalog.path), 'stage', plan['job_id'], '--staging', str(self.spool)]), 0)
        self.assertEqual(json.loads(output.getvalue())['state'], 'STAGED')
        output = io.StringIO()
        with patch('sys.stdout', output):
            self.assertEqual(main(['--db', str(self.catalog.path), 'staging-status', '--staging', str(self.spool)]), 0)
        status = json.loads(output.getvalue())
        self.assertGreater(status['storage']['free'], 0)
        self.assertEqual(status['archives'][0]['phase'], 'READY')

    def test_production_requires_long_benchmark_not_simulator(self):
        self.spool.mkdir()
        with self.assertRaises(SafetyError):
            require_qualification(self.catalog, self.spool)
        plan = self.plan()
        self.assertEqual(self.service.backup(plan['job_id'], plan['job_id'], self.spool)['state'], 'VERIFIED')

    @unittest.skipUnless(platform.system() == 'Linux', 'Linux O_DIRECT qualification only')
    def test_short_direct_io_benchmark_cannot_qualify_for_production(self):
        self.spool.mkdir()
        path = self.spool/'bench-input'
        path.write_bytes(b'x' * (8 * 1024 * 1024))
        report = run_benchmark(self.catalog, self.spool, path, seconds=0.03, min_rate=1)
        self.assertFalse(report['qualified'])
        self.assertTrue(report['direct_io'])
        self.assertGreater(report['bytes'], 0)
        self.assertEqual(path.stat().st_size, 8 * 1024 * 1024)
        with self.assertRaises(SafetyError):
            require_qualification(self.catalog, self.spool)


if __name__ == '__main__':
    unittest.main()
