"""Media-independent local PAX capture; consume once into ordinary bound TARs.

Only private local manifest bytes are changed. No tape operation is performed.
A durable intent makes any interrupted adoption fail closed, without retries.
"""
import hashlib
import json
import os
import time
import uuid
from .archive import (create_archive, estimate_entries, plan_archives, inventory,
                      inspect_stream, MANIFEST, MAX_META)
from .common import SafetyError, encode, sync_dir
from .staging import fingerprint
from .storage import require_local
from .source_capture import location
from .capture import progress_recorder

FORMAT = 'otam-packed-source-v1'
UNBOUND = '00000000-0000-0000-0000-000000000000'
RESERVE = 8192  # Includes the bounded portable rotation recovery descriptor.


def load(catalog, source_job):
    if not source_job:
        return None
    row = catalog.db.execute("SELECT plan_json FROM jobs WHERE id=? AND kind='source-plan'", (source_job,)).fetchone()
    draft = json.loads(row['plan_json']) if row and row['plan_json'] else {}
    capture = draft.get('source_capture', {})
    if capture.get('format') != FORMAT:
        return None
    if draft.get('sha256') != hashlib.sha256(encode({k:v for k,v in draft.items() if k != 'sha256'})).hexdigest():
        raise SafetyError('Packed source plan changed')
    return capture


def parent_for(staging, job):
    parent = location(staging, job)
    if parent.is_symlink() or parent.resolve().parent != staging.resolve():
        raise SafetyError('Unsafe packed source directory')
    marker = parent / 'owner.json'
    if marker.is_symlink() or json.loads(marker.read_bytes()) != {'format': FORMAT, 'job_id': job}:
        raise SafetyError('Packed source ownership changed')
    return parent


def path_for(parent, item):
    ident = item['manifest']['archive_id']; uuid.UUID(ident)
    return parent / (ident + '.tar')


def validate(staging, job, capture):
    parent = parent_for(staging, job)
    for item in capture['archives']:
        path = path_for(parent, item)
        try:
            changed = fingerprint(path) != item['fingerprint'] or path.stat().st_mode & 0o222
        except OSError as error:
            raise SafetyError('Packed source missing; interrupted binding requires diagnosis') from error
        if (changed
                or path.with_suffix('.binding.json').exists() or path.with_suffix('.binding.json').is_symlink()):
            raise SafetyError('Packed source changed or binding already attempted')
    return parent, capture['entries']


def validate_bound(catalog, staging, generation):
    """A rolling capture remains complete in its final immutable staged TARs."""
    from .staging import StagingStore
    def plan_for(job):
        row = catalog.db.execute('SELECT plan_json FROM jobs WHERE id=?', (job,)).fetchone()
        plan = json.loads(row[0]) if row and row[0] else {}
        if plan.get('sha256') != hashlib.sha256(encode({k:v for k,v in plan.items() if k != 'sha256'})).hexdigest():
            raise SafetyError('Bound packed plan changed')
        return plan
    parent = plan_for(generation['archive_job'])
    jobs = [v['job_id'] for v in parent['children']] if 'children' in parent else [generation['archive_job']]
    store = StagingStore(catalog, staging); entries = []
    for job in jobs:
        plan = plan_for(job)
        if plan.get('packed_source_job') != generation['source_job']:
            raise SafetyError('Packed generation source changed')
        for manifest in plan['archives']:
            store.assert_ready_identity(job, manifest)
            entries.extend(manifest['files'])
    capture = load(catalog, generation['source_job'])
    if sorted(entries, key=lambda e:e['path']) != sorted(capture['entries'], key=lambda e:e['path']):
        raise SafetyError('Bound generation differs from captured inventory')


def prepare(catalog, job, draft, staging):
    from pathlib import Path
    source = Path(draft['source']); staging = staging.resolve()
    if staging.is_relative_to(source) or source.is_relative_to(staging) or catalog.path.is_relative_to(staging):
        raise SafetyError('Staging und Quelle/Katalog müssen getrennt sein')
    if require_local(staging)['free'] < draft['required_estimate']:
        raise SafetyError('Nicht genügend Platz für die vorbereiteten TARs')
    inventory(source, draft['selected_paths'], metadata_only=True,
              excluded=draft.get('excluded_paths'), expected=draft.get('inventory_entries', draft['source_entries']))
    parent = location(staging, job); parent.mkdir(mode=0o700, exist_ok=False)
    with (parent / 'owner.json').open('xb') as stream:
        stream.write(encode({'format': FORMAT, 'job_id': job})); stream.flush(); os.fsync(stream.fileno())
    sync_dir(parent); sync_dir(staging)
    manifests = plan_archives(estimate_entries(draft['source_entries']), UNBOUND, draft['target'])
    report = progress_recorder(catalog, job); done = 0; started = time.monotonic(); archives = []
    for index, manifest in enumerate(manifests):
        manifest['capture_only'] = True
        capacity = len(encode(manifest)) + RESERVE
        if capacity > MAX_META:
            raise SafetyError('Packed manifest exceeds metadata limit')
        path = parent / (manifest['archive_id'] + '.tar')
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600); os.close(fd)
        def progress(current):
            report({'phase': 'STAGING', 'bytes': done + current, 'total_bytes': draft['payload_bytes'],
                    'archive': index + 1, 'total_archives': len(manifests),
                    'elapsed_seconds': time.monotonic() - started})
        create_archive(path, source, manifest, progress, validate=False, single_pass=True,
                       expected=draft['source_entries'], manifest_capacity=capacity)
        # One independent local pass verifies all file hashes and the full TAR.
        def validating(current):
            report({'phase': 'VALIDATION', 'bytes': current, 'total_bytes': path.stat().st_size,
                    'archive': index + 1, 'total_archives': len(manifests)})
        with path.open('rb') as stream:
            _, checksum, size = inspect_stream(stream, manifest, validating)
            os.fsync(stream.fileno())
        if size > draft['archive_sizes'][index]:
            raise SafetyError('Prepared TAR exceeds reserved planning budget')
        path.chmod(0o400); sync_dir(parent)
        archives.append({'manifest': manifest, 'capacity': capacity, 'sha256': checksum,
                         'fingerprint': fingerprint(path)})
        done += sum(e['size'] for e in manifest['files'])
    capture = {'format': FORMAT, 'archives': archives, 'entries': [e for m in manifests for e in m['files']],
               'bytes': done, 'created': time.time()}
    validate(staging, job, capture)
    report({'phase': 'STAGING', 'bytes': done, 'total_bytes': done, 'complete': True})
    return capture


def adopt(store, job, manifest, source_job, capture):
    """Move one inode, patch reserved JSON, independently validate, publish READY.

    On failure both the source intent and any moved partial survive; no retry or
    original-source fallback can silently replace them.
    """
    parent = parent_for(store.root, source_job)
    names = [e['path'] for e in manifest['files']]
    matches = [a for a in capture['archives'] if [e['path'] for e in a['manifest']['files']] == names]
    if len(matches) != 1:
        raise SafetyError('Packed TAR grouping changed; create a new source plan')
    item = matches[0]; path = path_for(parent, item)
    if fingerprint(path) != item['fingerprint'] or path.stat().st_mode & 0o222:
        raise SafetyError('Packed source changed before binding')
    # Compare every captured entry, not just names or byte counts.
    expected = estimate_entries(item['manifest']['files'])
    if expected != manifest['files']:
        raise SafetyError('Packed source selection changed')
    manifest['files'] = [dict(e) for e in item['manifest']['files']]
    final = encode(manifest)
    if len(final) > item['capacity']:
        raise SafetyError('Final manifest exceeds reserved space')
    directory = store.directory(job, manifest['archive_id'])
    partial = directory / (str(uuid.uuid4()) + '.partial')
    ready = directory / 'ready.tar'
    if ready.exists() or ready.is_symlink():
        raise SafetyError('Ready TAR already exists')
    intent = path.with_suffix('.binding.json')
    with intent.open('xb') as stream:
        stream.write(encode({'format': FORMAT, 'source_job': source_job, 'job_id': job,
                             'archive_id': manifest['archive_id'], 'path': str(partial)}))
        stream.flush(); os.fsync(stream.fileno())
    sync_dir(parent)
    # Same filesystem by construction: no copy, no second payload allocation.
    os.link(path, partial); path.unlink(); sync_dir(parent); sync_dir(directory)
    store.track(job, manifest['archive_id'], partial)
    store.phase(job, manifest['archive_id'], 'VALIDATION', path=str(partial))
    try:
        partial.chmod(0o600)
        fd = os.open(partial, os.O_RDWR | os.O_NOFOLLOW)
        with os.fdopen(fd, 'r+b') as stream:
            # The reserved manifest is the first plain TAR member at offset 512.
            import tarfile
            header = tarfile.TarInfo.frombuf(stream.read(512), 'utf-8', 'strict')
            if header.name != MANIFEST or not header.isfile() or header.size != item['capacity']:
                raise SafetyError('Packed manifest header changed')
            if json.loads(stream.read(header.size)) != item['manifest']:
                raise SafetyError('Packed manifest changed')
            stream.seek(512); stream.write(final.ljust(header.size, b' ')); stream.flush(); os.fsync(stream.fileno())
        partial.chmod(0o400)
        checksum = store._inspect(partial, manifest, None, job)
        # The plan is not published until every adopted TAR passed this check.
        os.link(partial, ready); partial.unlink(); sync_dir(directory)
        store.track(job, manifest['archive_id'], ready)
        info = fingerprint(ready)
        with store.catalog.db:
            store.catalog.db.execute('DELETE FROM staging_artifacts WHERE job_id=? AND archive_id=? AND name=?',
                                     (job, manifest['archive_id'], partial.name))
        store.phase(job, manifest['archive_id'], 'READY', 'COMPLETE', path=str(ready), sha256=checksum,
                    bytes=info[2], fingerprint_json=encode(info).decode(), progress_bytes=info[2], total_bytes=info[2])
        store._validated[(job, manifest['archive_id'])] = (info, checksum)
        store.catalog.event(source_job, 'packed_tar_bound', child_job=job, archive=manifest['archive_id'],
                            media_id=manifest['media_id'], bytes=info[2])
    except BaseException as error:
        store.phase(job, manifest['archive_id'], 'VALIDATION', 'INTERRUPTED', str(error))
        raise
