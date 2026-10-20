#!/usr/bin/env python3
"""Small explicit per-medium child plans exercise a real two-cartridge exchange.

This is a hardware exchange proof, NOT a physical capacity-overflow proof. It
never changes media capacity/consumption to force distribution. Uses the LIVE
catalog, device locks and pending journal, separate private test control, and
only own synthetic sources. Stop the idle live worker for each invocation and
arrange its restart on both success and failure. No automatic resume/retry.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
import uuid
from contextlib import contextmanager
from dataclasses import asdict, replace
from pathlib import Path
from unittest.mock import patch

from otam.catalog import Catalog
from otam.common import SafetyError, encode, sha256, sync_dir
from otam.physical import discover_drives
from otam.sets import next_child
from otam.storage import require_local
from otam.tape import LinuxTape
from otam.transfer import selected_speed_profile
from otam.web import resources
from otam.web.config import WebConfig, Resource
from otam.web.control import Control
from otam.web.worker import execute, worker_lock


def save(root: Path, report: dict) -> None:
    with (root / 'report.json.tmp').open('w') as stream:
        json.dump(report, stream, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(root / 'report.json.tmp', root / 'report.json')
    sync_dir(root)


def explicit_parent(catalog: Catalog, plans: list[dict], source: Path) -> dict:
    """Assemble two valid per-medium child plans, without changing capacity.

    Only acceptance scaffolding: normal backup_set_step still validates hashes,
    source inventory, next medium, real identity/EOD/receipts and full readback.
    """
    if len(plans) != 2 or len({p['job_id'] for p in plans}) != 2:
        raise SafetyError('Two distinct prepared child plans required')
    ident, children, originals = str(uuid.uuid4()), [], []
    for summary in plans:
        row = catalog.db.execute('SELECT state,plan_json FROM jobs WHERE id=?', (summary['job_id'],)).fetchone()
        if row is None or row['state'] != 'PLANNED':
            raise SafetyError('Children must be fresh unexecuted plans')
        plan = json.loads(row['plan_json'])
        digest = plan.pop('sha256')
        if hashlib.sha256(encode(plan)).hexdigest() != digest or Path(plan['source']) != source:
            raise SafetyError('Child plan integrity/source mismatch')
        if plan.get('parent_job') or plan['verify_mode'] != 'media':
            raise SafetyError('Unexpected child plan scope')
        originals.append(plan)
        children.append({'job_id': summary['job_id'], 'media_id': plan['media_id'],
                         'archives': len(plan['archives']), 'files': plan['file_count'],
                         'payload_bytes': plan['payload_bytes'], 'required_estimate': plan['required_estimate']})
    if len({p['media_id'] for p in originals}) != 2:
        raise SafetyError('Exchange requires distinct media')
    parent = {'source': str(source), 'children': children,
              'media_ids': [p['media_id'] for p in originals], 'verify_mode': 'media',
              'target': 2_000_000, 'file_count': sum(p['file_count'] for p in originals),
              'payload_bytes': sum(p['payload_bytes'] for p in originals),
              'planning_basis': 'acceptance: explicitly assigned small per-medium children; no capacity overflow claimed'}
    parent['sha256'] = hashlib.sha256(encode(parent)).hexdigest()
    now = time.time()
    with catalog.db:
        catalog.db.execute("INSERT INTO jobs(id,kind,state,created,updated,plan_json,phase) VALUES(?,'archive-set','PLANNED',?,?,?,'INVENTORY')",
                           (ident, now, now, encode(parent).decode()))
        for child, plan in zip(children, originals):
            plan['parent_job'] = ident
            plan['sha256'] = hashlib.sha256(encode(plan)).hexdigest()
            catalog.db.execute('UPDATE jobs SET plan_json=?,updated=? WHERE id=?',
                               (encode(plan).decode(), now, child['job_id']))
    catalog.event(ident, 'acceptance_explicit_exchange_plan', media=parent['media_ids'], scope=parent['planning_basis'])
    return {'job_id': ident, **parent}


def main() -> None:
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--report-root', type=Path, required=True)
    parser.add_argument('--action', choices=('prepare', 'step'), required=True)
    parser.add_argument('--drive-serial', required=True)
    parser.add_argument('--first-serial', required=True)
    parser.add_argument('--second-serial', required=True)
    parser.add_argument('--confirm', required=True, help='PREPARE <drive> <first> <second> or APPEND <drive> <next serial>')
    args = parser.parse_args()
    if args.first_serial == args.second_serial:
        raise SafetyError('Two distinct authorized cartridges required')
    live = WebConfig.load(args.config)
    root = args.report_root.resolve()
    if (root.is_relative_to(live.state) or live.state.is_relative_to(root)
            or root.is_relative_to(live.staging) or live.staging.is_relative_to(root)
            or live.catalog.is_relative_to(root)):
        raise SafetyError('Private report must be separate from live state/catalog/staging')
    if args.action == 'prepare' and args.confirm != f'PREPARE {args.drive_serial} {args.first_serial} {args.second_serial}':
        raise SafetyError('Explicit drive and both cartridge confirmations required')
    with worker_lock(live):
        live_control = Control(live.state)
        with live_control.connect() as db:
            if live_control.shutdown_pending() or db.execute("SELECT 1 FROM commands WHERE state IN ('QUEUED','RUNNING')").fetchone():
                raise SafetyError('Live queue must be idle and no shutdown pending')
        catalog = Catalog(live.catalog)
        try:
            if args.action == 'prepare':
                root.mkdir(parents=True, exist_ok=False, mode=0o700)
                bindings = live_control.get('physical_media_bindings', {})
                media = []
                for serial in (args.first_serial, args.second_serial):
                    matches = [m for m, b in bindings.items() if b.get('medium_serial') == serial and b.get('drive_serial') == args.drive_serial]
                    if len(matches) != 1:
                        raise SafetyError('Each authorized cartridge needs one existing binding')
                    media.append(matches[0])
                    pending = live.state / 'physical-pending' / (hashlib.sha256(serial.encode()).hexdigest() + '.json')
                    if pending.exists() or pending.is_symlink():
                        raise SafetyError('Unresolved live write journal')
                source = root / 'synthetic-source'
                source.mkdir(mode=0o700)
                files = []
                for number in (1, 2):
                    path = source / (str(uuid.uuid4()) + f'-exchange-{number}.bin')
                    with path.open('xb') as stream:
                        stream.write(hashlib.shake_256(f'OTAM exchange {number}'.encode()).digest(1024**2))
                        stream.flush()
                        os.fsync(stream.fileno())
                    files.append(path.name)
                config = replace(live, state=root / 'state', sources=(Resource('exchange-source', 'Own exchange fixtures', source),),
                                 directory_roots=(source,), restore_root=live.staging / ('acceptance-exchange-' + root.name),
                                 physical_archiving=True, physical_multivolume=True)
                config.validate()
                control = Control(config.state)
                staging = [r for r in resources.entries(live, live_control) if r['kind'] == 'staging']
                if len(staging) != 1 or Path(staging[0]['path']).resolve() != live.staging.resolve():
                    raise SafetyError('Exactly one confirmed live staging resource expected')
                staging_id = staging[0]['id']
                policy = live_control.get('transfer_settings:' + staging_id)
                if not policy:
                    # The live installed version only earmarks settings. Persist
                    # the previously accepted 120 MB/s, 2368 MiB policy ONLY in
                    # this test control, using a real fresh profile/fingerprint.
                    inventory = {'time': time.time(), 'drives': discover_drives()}
                    drives = [d for d in inventory['drives'] if d.get('serial') == args.drive_serial
                              and d.get('medium_serial') == args.first_serial and d.get('ready')]
                    profile = selected_speed_profile(inventory, drives[0]['id']) if len(drives) == 1 else None
                    if profile is None or 120_000_000 not in profile['speed_steps_bytes_per_second']:
                        raise SafetyError('Accepted transfer rate needs confirmed current drive/media profile')
                    storage = require_local(live.staging)
                    policy = {key: profile[key] for key in ('drive_id', 'drive_serial', 'profile_id', 'medium_density_code')}
                    policy.update(write_rate_bytes_per_second=120_000_000, buffer_bytes=2368 * 1024**2,
                                  storage={key: storage[key] for key in ('mount', 'source', 'device', 'type')})
                control.set('storage_resources', staging + [{'id': 'exchange-source', 'label': 'Own exchange fixtures', 'kind': 'source', 'path': str(source)}])
                control.set('physical_media_bindings', bindings)
                control.set('operation_mode', 'physical')
                control.set('transfer_settings:' + staging_id, policy)
                # Planning checks the live pending directory as well above. Every
                # actual adapter below uses live.state for ALL hardware journals.
                plans = [execute(config, control, 'plan', {'media_id': m, 'source_id': 'exchange-source',
                          'selected_paths': [name], 'staging_id': staging_id, 'verify_mode': 'media', 'target': 2_000_000})
                         for m, name in zip(media, files)]
                parent = explicit_parent(catalog, plans, source)
                control.set('job_storage:' + parent['job_id'], control.get('job_storage:' + plans[0]['job_id']))
                report = {'state': 'PREPARING', 'started': time.time(), 'drive_serial': args.drive_serial,
                          'serials': [args.first_serial, args.second_serial], 'media_ids': media, 'parent': parent,
                          'source_hashes': {n: sha256(source / n) for n in files}, 'files': files,
                          'transfer_policy': policy,
                          'data_reads': [], 'moves': [], 'writes': [], 'steps': [],
                          'baseline': [dict(r) for r in catalog.db.execute('SELECT id,media_id,tape_file,state,sha256 FROM archives ORDER BY id')],
                          'scope': parent['planning_basis']}
                save(root, report)
                (root / 'node.json').write_text(json.dumps(asdict(config), default=str, indent=2))
                for plan in plans:
                    execute(config, control, 'stage', {'job_id': plan['job_id']})
                report['state'] = 'READY'
                save(root, report)
                return
            report = json.loads((root / 'report.json').read_text())
            if (report['drive_serial'] != args.drive_serial or report['serials'] != [args.first_serial, args.second_serial]
                    or report['state'] not in ('READY', 'WAITING_MEDIA')):
                raise SafetyError('Mismatched or already executed/uncertain exchange report')
            config = WebConfig.load(root / 'node.json')
            if config.catalog != live.catalog or config.staging != live.staging or config.state != root / 'state':
                raise SafetyError('Saved test paths no longer match live resources')
            control = Control(config.state)
            _, child = next_child(catalog, report['parent']['job_id'])
            index = report['media_ids'].index(child['media_id'])
            serial = report['serials'][index]
            if args.confirm != f'APPEND {args.drive_serial} {serial}':
                raise SafetyError('Exact next drive/cartridge authorization required')
            matches = [d for d in discover_drives() if d.get('serial') == args.drive_serial and d.get('medium_serial') == serial and d.get('ready')]
            if len(matches) != 1:
                raise SafetyError('Next authorized cartridge is not loaded')
            class ObservedTape(LinuxTape):
                def __init__(self, expected, state, **options):
                    # Same live device locks, pending markers and transfer logs.
                    super().__init__(expected, live.state, **options)

                def _move(self, operation, count=None):
                    report['moves'].append({'medium_serial': serial, 'operation': operation, 'count': count})
                    save(root, report)
                    return super()._move(operation, count)

                @contextmanager
                def open_read(self, position):
                    if position % 2:
                        report['data_reads'].append({'medium_serial': serial, 'position': position})
                        save(root, report)
                    with super().open_read(position) as stream:
                        yield stream

                def append(self, source, expected_media):
                    if (expected_media != child['media_id'] or self.device.expected['serial'] != args.drive_serial
                            or self.device.expected['medium_serial'] != serial):
                        raise SafetyError('Another cartridge/drive is forbidden')
                    result = super().append(source, expected_media)
                    report['writes'].append({'medium_serial': serial, 'position': result})
                    save(root, report)
                    return result

                def initialize(self, *values, **options):
                    raise SafetyError('Exchange acceptance never initializes')

            report['state'] = 'RUNNING'
            save(root, report)
            try:
                before = len(report['writes'])
                child_plan = json.loads(catalog.db.execute('SELECT plan_json FROM jobs WHERE id=?', (child['job_id'],)).fetchone()[0])
                position = child_plan['expected_tape_files']
                with patch('otam.web.physical_archive.LinuxTape', ObservedTape):
                    result = execute(config, control, 'backup-set', {'job_id': report['parent']['job_id'],
                        'confirm': report['parent']['job_id'], 'plan_hash': report['parent']['sha256'], 'media_id': child['media_id']})
                    restore = execute(config, control, 'restore', {'media_id': child['media_id'], 'paths': [report['files'][index]],
                                                                  'target_name': 'medium-' + str(index + 1)})
                if sha256(config.restore_root / ('medium-' + str(index + 1)) / report['files'][index]) != report['source_hashes'][report['files'][index]]:
                    raise SafetyError('Restored fixture SHA-256 mismatch')
                if [w['position'] for w in report['writes'][before:]] != [position, position + 1]:
                    raise SafetyError('Unexpected new physical write positions')
                if [r['position'] for r in report['data_reads'] if r['medium_serial'] == serial] != [position, position]:
                    raise SafetyError('Expected exactly one new payload read for backup and restore')
                for old in report['baseline']:
                    actual = catalog.db.execute('SELECT id,media_id,tape_file,state,sha256 FROM archives WHERE id=?', (old['id'],)).fetchone()
                    if actual is None or dict(actual) != old:
                        raise SafetyError('Historical archive prefix changed')
                expected_state = 'WAITING_MEDIA' if index == 0 else 'VERIFIED'
                if result['state'] != expected_state or restore['state'] != 'VERIFIED':
                    raise SafetyError('Exchange state progression or restore incomplete')
                samples = [json.loads(r[0]) for r in catalog.db.execute(
                    "SELECT details_json FROM events WHERE job_id=? AND event='io_progress'", (child['job_id'],))]
                samples = [s for s in samples if s.get('phase') == 'TAPE_WRITE']
                policy = report['transfer_policy']
                if not samples or any(s.get('write_rate_bytes_per_second') != policy['write_rate_bytes_per_second']
                                      or s.get('buffer_bytes') != policy['buffer_bytes'] for s in samples):
                    raise SafetyError('Actual write samples do not confirm the saved transfer policy')
                report['steps'].append({'medium_serial': serial, 'result': result, 'restore': restore,
                                        'source_target_sha256_equal': True, 'transfer_samples': samples, 'time': time.time()})
                report.update(state=expected_state, archive_prefix_unchanged=True, updated=time.time())
                save(root, report)
            except BaseException as error:
                report.update(state='FAILED', error=str(error), updated=time.time())
                save(root, report)
                raise
        finally:
            catalog.close()


if __name__ == '__main__':
    main()
