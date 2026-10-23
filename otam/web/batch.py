"""Explicit review of verification order; existing plans never switch silently."""
import hashlib
import json
import time
from ..archive import estimate
from ..catalog import Catalog
from ..common import SafetyError, encode
from ..sets import next_child
from ..staging import StagingStore, fingerprint
from ..storage import io_lock
from . import resources, maintenance, physical_archive


def review(catalog, payload, *, apply=False):
    if (set(payload) != {'job_id','plan_hash','confirm','verify_mode'}
            or any(not isinstance(payload.get(k),str) for k in ('job_id','plan_hash','confirm','verify_mode'))
            or payload.get('confirm') != payload.get('job_id')
            or payload.get('verify_mode') not in ('archive','media')):
        raise SafetyError('Plan-ID, unveränderter Planhash und Verifikationsmodus bestätigen')
    row, next_item = next_child(catalog,payload['job_id'])
    parent=json.loads(row['plan_json'])
    if row['state'] not in ('PLANNED','WAITING_MEDIA') or parent['sha256']!=payload['plan_hash']:
        raise SafetyError('Aktueller unveränderter, untätiger Mehrbandplan erforderlich')
    old_parent_hash=parent['sha256'];changes=[];updated=[];now=time.time()
    for child in parent['children']:
        r=catalog.db.execute('SELECT * FROM jobs WHERE id=?',(child['job_id'],)).fetchone()
        if r['state']=='VERIFIED':continue
        if r['state'] not in ('PLANNED','STAGED') or catalog.db.execute('SELECT 1 FROM archives WHERE job_id=? LIMIT 1',(child['job_id'],)).fetchone():
            raise SafetyError('Begonnenes oder unterbrochenes Medium benötigt gesonderte Prüfung')
        plan=json.loads(r['plan_json']);old=plan.pop('sha256')
        if (hashlib.sha256(encode(plan)).hexdigest()!=old or plan.get('parent_job')!=payload['job_id']
                or plan.get('media_id')!=child['media_id']):
            raise SafetyError('Kindplan verändert oder falsch gebunden')
        changes.append({'job_id':child['job_id'],'previous_sha256':old,'previous_mode':plan.get('verify_mode','archive')})
        plan['verify_mode']=payload['verify_mode']
        plan['verification_review']={'previous_sha256':old,'time':now}
        plan['sha256']=hashlib.sha256(encode(plan)).hexdigest();updated.append((child['job_id'],plan))
    parent['verify_mode']=payload['verify_mode']
    parent['verification_review']={'previous_sha256':old_parent_hash,'children':changes,'time':now}
    parent.pop('sha256');parent['sha256']=hashlib.sha256(encode(parent)).hexdigest()
    if apply:
        with catalog.db:
            for ident,plan in updated:
                catalog.db.execute('UPDATE jobs SET plan_json=?,updated=? WHERE id=?',(encode(plan).decode(),now,ident))
            catalog.db.execute('UPDATE jobs SET plan_json=?,updated=? WHERE id=?',(encode(parent).decode(),now,payload['job_id']))
            catalog.db.execute('INSERT INTO events(job_id,time,level,event,details_json) VALUES(?,?,?,?,?)',
                (payload['job_id'],now,'INFO','verification_mode_reviewed',encode({'previous_sha256':old_parent_hash,'sha256':parent['sha256'],'mode':payload['verify_mode'],'children':changes}).decode()))
    return {'job_id':payload['job_id'],'sha256':parent['sha256'],'verify_mode':payload['verify_mode']}


def validate(config,control,payload):
    if maintenance.mode(config,control)=='physical':physical_archive.require_mode(config,control)
    c=Catalog(config.catalog)
    try:review(c,payload)
    finally:c.close()


def execute(config,control,payload):
    with io_lock():
        validate(config,control,payload)
        c=Catalog(config.catalog)
        try:return review(c,payload,apply=True)
        finally:c.close()


def offer(config,control,job):
    c=Catalog(config.catalog)
    try:
        row,child=next_child(c,job)
        if row['state'] not in ('PLANNED','WAITING_MEDIA'):
            raise SafetyError('Batch-Auswahl nur vor Beginn des nächsten Mediums')
        r=c.db.execute('SELECT state,plan_json FROM jobs WHERE id=?',(child['job_id'],)).fetchone()
        if r['state'] not in ('PLANNED','STAGED'):
            raise SafetyError('Nächstes Medium nicht bereit')
        plan=json.loads(r['plan_json'])
        binding=control.get('job_storage:'+child['job_id']) or control.get('job_storage:'+job)
        if not binding:raise SafetyError('Staging-Bindung fehlt')
        root=resources.staging_for(config,control,binding['staging_id']);store=StagingStore(c,root)
        missing=0
        for m in plan['archives']:
            row=store.row(child['job_id'],m['archive_id']);ready=False
            if row['path'] and row['sha256'] and row['fingerprint_json']:
                try:
                    from pathlib import Path
                    p=Path(row['path'])
                    ready=(p.resolve().is_relative_to(root.resolve()) and not p.is_symlink()
                           and not p.stat().st_mode & 0o222 and fingerprint(p)==json.loads(row['fingerprint_json']))
                except (OSError,SafetyError):pass
            if not ready:missing+=estimate(m['files'])+10240
        info=resources.require_local(root)
        return {'job_id':job,'child_job_id':child['job_id'],'required_new_bytes':missing,
                'free_bytes':info['free'],'available':info['free']>=missing,
                'verify_mode':plan.get('verify_mode','archive'),'archives':len(plan['archives'])}
    finally:c.close()
