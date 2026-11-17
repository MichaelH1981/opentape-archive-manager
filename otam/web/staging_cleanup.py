"""Explicit cleanup of verified owned data; unknown files are never candidates."""
import hashlib
import json
from ..catalog import Catalog
from ..common import SafetyError, encode
from ..storage import io_lock
from ..staging import StagingStore
from . import resources, rotation


def preview(config, control, staging_id):
    root=resources.staging_for(config,control,staging_id)
    c=Catalog(config.catalog)
    try:
        generations=[];archives=[];size=0
        for g in c.db.execute("SELECT * FROM backup_generations WHERE state='VERIFIED'"):
            data=json.loads(g['data_json'])
            binding=control.get('job_storage:'+g['source_job'],{})
            if data.get('source_capture_retained') and binding.get('staging_id')==staging_id:
                generations.append(g['id']);size+=data.get('payload_bytes',0)
        for r in c.db.execute("SELECT s.job_id,s.archive_id,s.path,s.bytes FROM staged_archives s JOIN archives a ON a.id=s.archive_id AND a.job_id=s.job_id JOIN jobs j ON j.id=s.job_id WHERE a.state='VERIFIED' AND j.state='VERIFIED' AND s.root=? AND s.phase!='STAGING_CLEANUP'",(str(root),)):
            plan=json.loads(c.db.execute('SELECT plan_json FROM jobs WHERE id=?',(r['job_id'],)).fetchone()[0])
            # Rotation data must pass whole-generation availability checks.
            if any(m.get('rotation') for m in plan.get('archives',[])):continue
            archives.append([r['job_id'],r['archive_id']]);size+=r['bytes'] or 0
        result={'staging_id':staging_id,'generations':sorted(generations),'archives':sorted(archives),'estimated_bytes':size}
        result['preview_hash']=hashlib.sha256(encode(result)).hexdigest()
        return result
    finally:c.close()


def execute(config,control,payload):
    with io_lock():
        value=preview(config,control,payload['staging_id'])
        if value['preview_hash']!=payload['preview_hash']:
            raise SafetyError('Bereinigungsauswahl verändert; Vorschau erneut öffnen')
        for generation in value['generations']:
            rotation.cleanup(config,control,{'generation_id':generation},_locked=True)
        c=Catalog(config.catalog)
        try:
            store=StagingStore(c,resources.staging_for(config,control,payload['staging_id']))
            for job,archive in value['archives']:store.cleanup(job,archive)
        finally:c.close()
        return {'state':'SUCCEEDED','generations':len(value['generations']),'archives':len(value['archives'])}


def automatic(config,control):
    """Best effort after reconcile; cleanup failure must not undo verified data."""
    c=Catalog(config.catalog)
    try:
        keys=[r['id'] for r in c.db.execute("SELECT id FROM backup_generations WHERE state='VERIFIED' AND json_extract(data_json,'$.source_capture_retained')=1")]
    finally:c.close()
    for key in keys:
        try:rotation.cleanup(config,control,{'generation_id':key})
        except Exception as error:
            c=Catalog(config.catalog)
            try:c.event(key,'automatic_cleanup_deferred',level='WARNING',error=str(error))
            finally:c.close()
