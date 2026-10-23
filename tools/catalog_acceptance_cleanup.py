"""Explicit, reviewed test-row cleanup. Never touches files or tape devices.

Caller must first preserve independent SQLite backups and provenance. Media and
job IDs are an audited allowlist, not inferred from labels or filename patterns.
Both preview and apply refuse unknown/missing rows and concurrent catalog drift.
Control/safety journals are intentionally outside this database-only function.
"""
from __future__ import annotations

import hashlib
import json

from otam.catalog import Catalog
from otam.common import SafetyError, encode


def preview(catalog: Catalog, media_ids: list[str], job_ids: list[str]) -> dict:
    if not media_ids or not job_ids or len(set(media_ids)) != len(media_ids) or len(set(job_ids)) != len(job_ids):
        raise SafetyError('Explicit distinct media and job IDs required')
    media, jobs = set(media_ids), set(job_ids)
    existing_media = {r[0] for r in catalog.db.execute('SELECT id FROM media')}
    existing_jobs = {r[0] for r in catalog.db.execute('SELECT id FROM jobs')}
    if not media <= existing_media or not jobs <= existing_jobs:
        raise SafetyError('Cleanup allowlist contains unknown IDs')
    archives = {r['id'] for r in catalog.db.execute('SELECT id,media_id,job_id FROM archives')
                if r['media_id'] in media}
    for row in catalog.db.execute('SELECT id,media_id,job_id FROM archives'):
        if (row['id'] in archives and row['job_id'] not in jobs) or (row['job_id'] in jobs and row['media_id'] not in media):
            raise SafetyError('Archive references cross the reviewed cleanup boundary')
    for row in catalog.db.execute('SELECT id,media_id,state,plan_json FROM jobs'):
        if row['media_id'] in media and row['id'] not in jobs:
            raise SafetyError('A retained job references test media')
        if row['id'] in jobs:
            if row['state'] in ('RUNNING','PLANNING') or (row['media_id'] is not None and row['media_id'] not in media):
                raise SafetyError('Active or unrelated jobs cannot be removed')
            plan = json.loads(row['plan_json'] or '{}')
            if plan.get('media_ids') and not set(plan['media_ids']) <= media:
                raise SafetyError('Archive set references unrelated media')
    exported = catalog.export()
    # Hash the entire current catalog, including unrelated retained records.
    # A change anywhere between review and apply requires a fresh preview.
    fingerprint = hashlib.sha256(encode(exported)).hexdigest()
    plan = {'media_ids': sorted(media), 'job_ids': sorted(jobs), 'archive_ids': sorted(archives),
            'files': sum(r['archive_id'] in archives for r in exported['files']), 'catalog_sha256': fingerprint}
    return {**plan, 'sha256': hashlib.sha256(encode(plan)).hexdigest()}


def apply(catalog: Catalog, plan: dict, confirmation: str) -> dict:
    if confirmation != 'REMOVE TEST CATALOG ' + plan['sha256']:
        raise SafetyError('Exact reviewed cleanup hash confirmation required')
    with catalog.db:
        catalog.db.execute('BEGIN IMMEDIATE')
        if preview(catalog, plan['media_ids'], plan['job_ids']) != plan:
            raise SafetyError('Catalog changed since cleanup review')
        def remove(table, column, values):
            for value in values:
                catalog.db.execute(f'DELETE FROM {table} WHERE {column}=?', (value,))
        for table in ('staging_artifacts','staged_archives','restores','events','verifications'):
            remove(table, 'job_id', plan['job_ids'])
        remove('verifications', 'archive_id', plan['archive_ids'])
        remove('files', 'archive_id', plan['archive_ids'])
        remove('archives', 'id', plan['archive_ids'])
        remove('jobs', 'id', plan['job_ids'])
        remove('media', 'id', plan['media_ids'])
        if catalog.db.execute('PRAGMA foreign_key_check').fetchall():
            raise SafetyError('Cleanup would violate catalog references')
    return {'removed_media': len(plan['media_ids']), 'removed_jobs': len(plan['job_ids']),
            'removed_archives': len(plan['archive_ids']), 'removed_files': plan['files'], 'review_sha256': plan['sha256']}
