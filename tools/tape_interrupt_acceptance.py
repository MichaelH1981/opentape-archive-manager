#!/usr/bin/env python3
"""Deliberate small process death during a real, explicitly authorized append.

Leaves the LIVE pending journal and uncertain tail intact. Never clears a
marker, retries a write, initializes, erases or cleans sources/staging. Requires
the completed exchange report, idle live queue and supervising worker restart.
This is a process-death test, not power-failure or full-medium qualification.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import signal
import subprocess
import sys
import time
from dataclasses import asdict, replace
from pathlib import Path
from unittest.mock import patch

from otam.catalog import Catalog
from otam.common import SafetyError, sha256
from otam.physical import discover_drives
from otam.tape import LinuxTape
from otam.web.config import WebConfig, Resource
from otam.web.control import Control
from otam.web.worker import execute, worker_lock
from tools.tape_exchange_acceptance import save

EXIT_CODE = 79
FIRST_RECORD = 512 * 1024


def exit_after_record(callback, pending: Path, root: Path, sample: dict) -> None:
    """Persist normal progress, then crash only after an accepted real write."""
    callback(sample)
    if sample['bytes'] < FIRST_RECORD:
        return
    if not pending.is_file() or pending.is_symlink():
        raise SafetyError('A durable real write journal must precede the interruption')
    proof = {'accepted_bytes': sample['bytes'], 'pending_sha256': sha256(pending),
             'process_id': os.getpid(), 'time': time.time(), 'scope': 'os.write returned; process death, not power failure'}
    # Exclusive claim: never silently replace a previous crash proof.
    with (root / 'crash-proof.json').open('x') as stream:
        json.dump(proof, stream)
        stream.flush()
        os.fsync(stream.fileno())
    from otam.common import sync_dir
    sync_dir(root)
    os._exit(EXIT_CODE)


def refuse_pending(drive: dict, live_state: Path, source: Path, media: str) -> str:
    """Fresh adapter refuses before motion/header/another writer is opened."""
    tape = LinuxTape(drive, live_state)
    def forbidden(*args, **kwargs):
        raise AssertionError('Uncertain tail must be refused before motion/read/write')
    tape._move = forbidden
    tape.header = forbidden
    tape.device.writer = forbidden
    with tape.locked():
        try:
            tape.append(source, media)
        except SafetyError as error:
            if 'uncertain physical tape tail' not in str(error):
                raise
            return str(error)
    raise SafetyError('A fresh adapter accepted an uncertain tail')


def main() -> None:
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True, type=Path)
    parser.add_argument('--exchange-root', required=True, type=Path)
    parser.add_argument('--report-root', required=True, type=Path)
    parser.add_argument('--drive-serial', required=True)
    parser.add_argument('--medium-serial', required=True)
    parser.add_argument('--confirm', required=True, help='INTERRUPT <drive> <MAM>; leaves a blocked tail')
    parser.add_argument('--child', choices=('write', 'refuse'), help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.confirm != f'INTERRUPT {args.drive_serial} {args.medium_serial}':
        raise SafetyError('Exact intentional physical write interruption confirmation required')
    live = WebConfig.load(args.config)
    root = args.report_root.resolve()
    if (root.is_relative_to(live.state) or live.state.is_relative_to(root)
            or root.is_relative_to(live.staging) or live.staging.is_relative_to(root)
            or live.catalog.is_relative_to(root)):
        raise SafetyError('Report must be separate from live resources')
    drives = [d for d in discover_drives() if d.get('serial') == args.drive_serial
              and d.get('medium_serial') == args.medium_serial and d.get('ready')]
    if len(drives) != 1:
        raise SafetyError('Exact authorized drive/cartridge is not present')
    drive = drives[0]
    tape = LinuxTape(drive, live.state)
    if args.child:
        report = json.loads((root / 'report.json').read_text())
        config = WebConfig.load(root / 'node.json')
        if (config.catalog != live.catalog or config.staging != live.staging or config.state != root / 'state'
                or report['drive_serial'] != args.drive_serial or report['medium_serial'] != args.medium_serial):
            raise SafetyError('Saved test resource/identity mismatch')
        if args.child == 'refuse':
            reason = refuse_pending(drive, live.state, Path(report['staged_path']), report['media_id'])
            with (root / 'fresh-refusal.json').open('x') as stream:
                json.dump({'state': 'REFUSED', 'reason': reason}, stream)
            return
        if report['state'] != 'ARMED' or report['parent_pid'] != os.getppid():
            raise SafetyError('Write child requires the active supervising parent')
        with (root / 'write-child-claim').open('x') as stream:
            stream.write(str(os.getpid()))
            stream.flush()
            os.fsync(stream.fileno())
        class InterruptedTape(LinuxTape):
            def __init__(self, expected, state, **options):
                super().__init__(expected, live.state, **options)
            def initialize(self, *values, **options):
                raise SafetyError('Interruption acceptance never initializes')
            def append(self, source, media):
                if (self.device.expected['serial'] != args.drive_serial
                        or self.device.expected['medium_serial'] != args.medium_serial
                        or media != report['media_id'] or str(source) != report['staged_path']):
                    raise SafetyError('Only the reviewed small data TAR may start writing')
                return super().append(source, media)
            def set_monitor(self, callback):
                if callback is None:
                    return super().set_monitor(None)
                def observed(sample):
                    # During receipt preflight no payload monitor is installed.
                    # In this callback append already completed os.write(record).
                    if sample.get('drive_status') == 'writing':
                        exit_after_record(callback, self._pending, root, sample)
                    else:
                        callback(sample)
                super().set_monitor(observed)
        with patch('otam.web.physical_archive.LinuxTape', InterruptedTape):
            execute(config, Control(config.state), 'backup', {'job_id': report['job_id'],
                    'confirm': report['job_id'], 'plan_hash': report['plan_hash']})
        raise SafetyError('The intentional process interruption did not occur')

    with worker_lock(live):
        control = Control(live.state)
        with control.connect() as db:
            if control.shutdown_pending() or db.execute("SELECT 1 FROM commands WHERE state IN ('RUNNING','QUEUED')").fetchone():
                raise SafetyError('Live worker must be idle')
        if tape._pending.exists() or tape._pending.is_symlink():
            raise SafetyError('An uncertain write already exists; never retry')
        exchange = json.loads((args.exchange_root / 'report.json').read_text())
        if (exchange['state'] != 'VERIFIED' or len(exchange['steps']) != 2
                or args.medium_serial not in exchange['serials'] or exchange['drive_serial'] != args.drive_serial):
            raise SafetyError('Completed positive physical exchange is required first')
        root.mkdir(parents=True, mode=0o700, exist_ok=False)
        report = {'state': 'PREPARING', 'started': time.time(), 'drive_serial': args.drive_serial,
                  'medium_serial': args.medium_serial, 'parent_pid': os.getpid(),
                  'scope': 'small physical process interruption; no power-loss claim'}
        save(root, report)
        catalog = Catalog(live.catalog)
        try:
            before = [dict(r) for r in catalog.db.execute('SELECT id,media_id,tape_file,state,sha256 FROM archives ORDER BY id')]
            previous = WebConfig.load(args.exchange_root / 'node.json')
            prior_control = Control(previous.state)
            resource_list = prior_control.get('storage_resources')
            staging = [r for r in resource_list if r['kind'] == 'staging']
            if len(staging) != 1 or Path(staging[0]['path']).resolve() != live.staging.resolve():
                raise SafetyError('Confirmed single staging resource required')
            source = root / 'synthetic-source'
            source.mkdir(mode=0o700)
            payload = source / 'interrupted-8MiB.bin'
            with payload.open('xb') as stream:
                stream.write(hashlib.shake_256(b'OTAM deliberate small interruption').digest(8 * 1024**2))
                stream.flush()
                os.fsync(stream.fileno())
            config = replace(live, state=root / 'state', sources=(Resource('interruption-source', 'Own interruption fixture', source),),
                             directory_roots=(source,), physical_archiving=True)
            config.validate()
            test_control = Control(config.state)
            test_control.set('operation_mode', 'physical')
            test_control.set('physical_media_bindings', control.get('physical_media_bindings'))
            test_control.set('storage_resources', staging + [{'id': 'interruption-source', 'label': 'Own interruption fixture',
                                                             'path': str(source), 'kind': 'source'}])
            test_control.set('transfer_settings:' + staging[0]['id'], prior_control.get('transfer_settings:' + staging[0]['id']))
            bindings = control.get('physical_media_bindings')
            matching = [m for m,b in bindings.items() if b['medium_serial'] == args.medium_serial and b['drive_serial'] == args.drive_serial]
            if len(matching) != 1:
                raise SafetyError('One registered authorized medium required')
            media = matching[0]
            plan = execute(config, test_control, 'plan', {'media_id': media, 'source_id': 'interruption-source',
                'staging_id': staging[0]['id'], 'target': 16 * 1024**2, 'verify_mode': 'archive'})
            execute(config, test_control, 'stage', {'job_id': plan['job_id']})
            staged = dict(catalog.db.execute('SELECT * FROM staged_archives WHERE job_id=?', (plan['job_id'],)).fetchone())
            report.update(state='ARMED', media_id=media, job_id=plan['job_id'], plan_hash=plan['sha256'],
                          archive_id=staged['archive_id'], staged_path=staged['path'], staged_sha256=staged['sha256'],
                          source_sha256=sha256(payload), baseline=before)
            (root / 'node.json').write_text(json.dumps(asdict(config), default=str, indent=2))
            save(root, report)
            command = [sys.executable, '-u', str(Path(__file__).resolve()), '--config', str(args.config),
                       '--exchange-root', str(args.exchange_root), '--report-root', str(root),
                       '--drive-serial', args.drive_serial, '--medium-serial', args.medium_serial, '--confirm', args.confirm]
            with (root / 'write-child.log').open('xb') as log:
                child = subprocess.Popen(command + ['--child', 'write'], stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
                code = child.wait()
                # An abruptly closed pipe can leave mbuffer alive briefly; only
                # this test's dedicated process group may be terminated.
                try:
                    os.killpg(child.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
            if code != EXIT_CODE:
                raise SafetyError('Unexpected writer exit; inspect retained evidence before any further action')
            proof = json.loads((root / 'crash-proof.json').read_text())
            if not FIRST_RECORD <= proof['accepted_bytes'] < staged['bytes'] or sha256(tape._pending) != proof['pending_sha256']:
                raise SafetyError('Physical partial-write and preserved pending proof incomplete')
            # Actual fresh CLI process reconciles metadata without issuing a job.
            restarted = subprocess.run([sys.executable, '-m', 'otam', 'worker', '--config', str(root / 'node.json'), '--once'],
                                       capture_output=True)
            (root / 'restart.log').write_bytes(restarted.stdout + restarted.stderr)
            if restarted.returncode:
                raise SafetyError('Fresh CLI worker reconciliation failed')
            states = {
                'job': catalog.db.execute('SELECT state FROM jobs WHERE id=?', (plan['job_id'],)).fetchone()[0],
                'archive': catalog.db.execute('SELECT state FROM archives WHERE id=?', (staged['archive_id'],)).fetchone()[0],
                'staging': catalog.db.execute('SELECT state FROM staged_archives WHERE job_id=?', (plan['job_id'],)).fetchone()[0],
                'medium': catalog.db.execute('SELECT state FROM media WHERE id=?', (media,)).fetchone()[0]}
            if states != {'job':'INTERRUPTED','archive':'INCOMPLETE','staging':'INTERRUPTED','medium':'SUSPECT'}:
                raise SafetyError('Process restart produced unsafe catalog states: ' + str(states))
            refused = subprocess.run(command + ['--child', 'refuse'], capture_output=True)
            (root / 'refusal.log').write_bytes(refused.stdout + refused.stderr)
            if refused.returncode or json.loads((root / 'fresh-refusal.json').read_text())['state'] != 'REFUSED':
                raise SafetyError('Fresh process did not refuse before further device movement/write')
            if sha256(tape._pending) != proof['pending_sha256'] or sha256(Path(staged['path'])) != staged['sha256'] or sha256(payload) != report['source_sha256']:
                raise SafetyError('Pending, source or staged artifact was changed')
            for old in before:
                if dict(catalog.db.execute('SELECT id,media_id,tape_file,state,sha256 FROM archives WHERE id=?', (old['id'],)).fetchone()) != old:
                    raise SafetyError('Verified prefix changed')
            report.update(state='VERIFIED', finished=time.time(), crash=proof, recovered_states=states,
                          pending_preserved=True, source_and_staging_preserved=True, archive_prefix_unchanged=True,
                          warning='Test cartridge remains SUSPECT with unresolved live pending; no automatic recovery or reuse')
            save(root, report)
        except BaseException as error:
            report.update(state='FAILED', finished=time.time(), error=str(error))
            save(root, report)
            raise
        finally:
            catalog.close()


if __name__ == '__main__':
    main()
