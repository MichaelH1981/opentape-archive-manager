"""Single source pass into privately finalized, independently inspected TARs."""
import time
import json
import hashlib
from .common import SafetyError
from .archive import estimate
from .staging import StagingStore


def progress_recorder(catalog, job):
    last = -float('inf')
    def report(data):
        nonlocal last
        now = time.monotonic()
        final = data.get('complete',False)
        if now-last < 1 and not final:
            return
        catalog.event(job, 'planning_progress', **data)
        last = now
    return report


def prepare_combined(catalog, job, root, manifests, expected, spool, *, source_job=None):
    """Never publish a plan with placeholder hashes; interrupted files stay owned."""
    spool=spool.resolve()
    if spool.is_relative_to(root) or root.is_relative_to(spool):
        # An explicitly owned, sealed source snapshot is the only exception.
        from .source_capture import validate as validate_capture
        from .common import encode
        row=catalog.db.execute("SELECT plan_json FROM jobs WHERE id=? AND kind='source-plan'",(source_job,)).fetchone()
        draft=json.loads(row['plan_json']) if row else {}
        if not draft.get('source_capture') or draft.get('sha256')!=hashlib.sha256(encode({k:v for k,v in draft.items() if k!='sha256'})).hexdigest():
            raise SafetyError('Staging and source must be separate')
        captured,_=validate_capture(spool,source_job,draft['source_capture'])
        if root!=captured:raise SafetyError('Staging and source must be separate')
    if catalog.path.is_relative_to(spool):
        raise SafetyError('Staging must not contain the catalog')
    store = StagingStore(catalog, spool)
    store.require_space(sum(estimate(m['files'])+10240 for m in manifests))
    if catalog.db.execute('SELECT 1 FROM jobs WHERE id=?', (job,)).fetchone() is None:
        now=time.time()
        with catalog.db:
            catalog.db.execute("INSERT INTO jobs(id,kind,state,media_id,created,updated,phase) VALUES(?,'archive','PLANNING',?,?,?,'INVENTORY')",
                               (job,manifests[0]['media_id'],now,now))
    if source_job:
        catalog.event(source_job, "planning_child", child_job=job)
    try:
        # Caller has checked the complete metadata selection; each open below
        # rechecks the original fingerprint, including ctime, before and after copy.
        with catalog.db:
            for m in manifests:
                catalog.db.execute("INSERT INTO staged_archives(job_id,archive_id,phase,state,total_bytes,updated) VALUES(?,?,'INVENTORY','COMPLETE',?,?)",
                                   (job,m['archive_id'],sum(e['size'] for e in m['files']),time.time()))
        for m in manifests:
            store.prepare(job,root,m,single_pass=True,expected=expected)
        catalog.event(job,'combined_capture_complete',archives=len(manifests),
                      bytes=sum(e['size'] for m in manifests for e in m['files']),source_payload_passes=1)
    except BaseException as error:
        catalog.finish(job,'INTERRUPTED' if isinstance(error,(KeyboardInterrupt,SystemExit)) else 'FAILED',str(error))
        raise
