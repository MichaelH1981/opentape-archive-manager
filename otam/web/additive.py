"""Additive selection from explicitly attributable VERIFIED catalog entries.

Source identity is the configured source ID and resolved root on this node.
Simulator receipts never establish a physical backup baseline (or vice versa).
No file contents are read here; metadata equality is not an integrity claim.
"""
import json
import hashlib
from ..common import SafetyError, encode


def baseline(catalog, source_id, root, backend):
    jobs = set()
    for row in catalog.db.execute("SELECT plan_json,report_json FROM jobs WHERE kind='source-plan' AND state='BOUND'"):
        draft = json.loads(row['plan_json'] or '{}')
        if draft.get('source_id') != source_id or draft.get('source') != str(root):
            continue
        if draft.get('sha256') != hashlib.sha256(encode({k:v for k,v in draft.items() if k!='sha256'})).hexdigest():
            raise SafetyError('Additive Quellenzuordnung im Katalog wurde verändert')
        report = json.loads(row['report_json'] or '{}')
        bound = report.get('job_id')
        job = catalog.db.execute('SELECT kind,plan_json FROM jobs WHERE id=?', (bound,)).fetchone()
        if job is None:
            continue
        if job['kind'] == 'archive':
            jobs.add(bound)
        elif job['kind'] == 'archive-set':
            jobs.update(child['job_id'] for child in json.loads(job['plan_json'])['children'])
    result = {}; versions = {}
    # Restrict reads to attributable jobs; unrelated catalogs can be very large.
    for job_id in jobs:
        for row in catalog.db.execute("""SELECT f.path,f.size,f.mtime_ns,a.id,a.created,a.rowid AS ordinal,m.header_json
                FROM archives a JOIN files f ON a.id=f.archive_id JOIN media m ON m.id=a.media_id
                WHERE a.job_id=? AND a.state='VERIFIED' AND m.state NOT IN ('SUSPECT','RETIRED')""", (job_id,)):
            if json.loads(row['header_json']).get('backend') != backend:
                continue
            version = (row['created'], row['ordinal'])
            if version > versions.get(row['path'], (-1, -1)):
                versions[row['path']] = version
                result[row['path']] = {'size': row['size'], 'mtime_ns': row['mtime_ns'], 'archive_id': row['id']}
    return result


def select(entries, known, changed_policy):
    if changed_policy not in ('skip', 'include'):
        raise SafetyError('Ungültige Behandlung geänderter Dateien')
    selected = []; changed = []; unchanged = 0; new = 0
    for entry in entries:
        old = known.get(entry['path'])
        if old is None:
            selected.append(entry); new += 1
        elif (old['size'], old['mtime_ns']) == (entry['size'], entry['mtime_ns']):
            unchanged += 1
        else:
            changed.append(entry['path'])
            if changed_policy == 'include':
                selected.append(entry)
    return selected, {'new_files': new, 'unchanged_files': unchanged,
                      'changed_files': len(changed), 'changed_paths': changed[:100],
                      'changed_paths_truncated': len(changed) > 100,
                      'changed_policy': changed_policy, 'baseline_files': len(known),
                      'comparison': 'relative path, size and mtime; skipped contents not hashed'}
