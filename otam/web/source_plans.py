"""Metadata-only source plans; capacity selection precedes hashing and tape I/O."""
import hashlib
import json
import time
from pathlib import Path
from ..archive import inventory, group_entries, estimate, estimate_entries, MAX_META
from ..catalog import Catalog
from ..common import SafetyError, encode, safe_path
from ..service import ArchiveService
from ..sets import plan_set
from ..storage import io_lock
from . import maintenance, resources, physical_archive


def load(catalog, ident):
    row=catalog.db.execute("SELECT state,plan_json FROM jobs WHERE id=? AND kind='source-plan'",(ident,)).fetchone()
    if row is None:
        raise SafetyError('Quellenplan fehlt')
    value=json.loads(row['plan_json'])
    if value.get('sha256') != hashlib.sha256(encode({k:v for k,v in value.items() if k!='sha256'})).hexdigest():
        raise SafetyError('Quellenplan wurde verändert')
    return row['state'],value


def validate(config,control,kind,payload):
    if maintenance.mode(config,control)=='physical':
        physical_archive.require_mode(config,control)
    if kind=='plan-source':
        if set(payload)-{'source_id','staging_id','target','selected_paths','excluded_paths','verify_mode'}:
            raise SafetyError('Quellenplanung akzeptiert noch keine Zielmedien')
        if not isinstance(payload.get('source_id'),str) or payload['source_id'] not in {s.id for s in config.sources}:
            raise SafetyError('Quelle ist nicht freigegeben')
        if type(payload.get('target',75_000_000_000)) is not int or not 10240<=payload.get('target',75_000_000_000)<=10_000_000_000_000:
            raise SafetyError('Ungültige TAR-Zielgröße')
        if payload.get('verify_mode','archive') not in ('archive','media'):
            raise SafetyError('Ungültiger Verifikationsmodus')
        if 'selected_paths' in payload:
            paths=payload['selected_paths']
            if not isinstance(paths,list) or not 1<=len(paths)<=10000 or any(not isinstance(p,str) or len(p)>4096 for p in paths):
                raise SafetyError('Ungültige Dateiauswahl')
            for p in paths:safe_path(p)
        if 'excluded_paths' in payload:
            paths=payload['excluded_paths']
            if not isinstance(paths,list) or len(paths)>10000 or any(not isinstance(p,str) or len(p)>4096 for p in paths):
                raise SafetyError('Ungültige Ausschlüsse')
            for p in paths:safe_path(p)
        resources.staging_for(config,control,payload.get('staging_id',resources.default_staging_id(config,control)))
        return
    if set(payload)!={'job_id','source_plan_hash','media_ids'}:
        raise SafetyError('Quellenplan, unveränderter Planhash und Zielmedien erforderlich')
    import uuid
    try:uuid.UUID(payload['job_id'])
    except (ValueError,TypeError,AttributeError):raise SafetyError('Gültige Quellenplan-ID erforderlich')
    ids=payload['media_ids']
    if not isinstance(ids,list) or not 1<=len(ids)<=32 or any(not isinstance(i,str) for i in ids) or len(set(ids))!=len(ids):
        raise SafetyError('Ein bis 32 verschiedene Zielmedien erforderlich')
    for ident in ids:
        try:uuid.UUID(ident)
        except (ValueError,TypeError,AttributeError):raise SafetyError('Gültige Zielmedien-ID erforderlich')
    if len(ids)>1 and maintenance.mode(config,control)=='physical' and not config.physical_multivolume:
        raise SafetyError('Physischer Mehrbandbetrieb ist nicht freigegeben')
    c=Catalog(config.catalog)
    try:
        state,draft=load(c,payload['job_id'])
        if state!='WAITING_MEDIA' or draft['sha256']!=payload['source_plan_hash']:
            raise SafetyError('Quellenplan bereits gebunden, verändert oder nicht bereit')
        if draft['source_id'] not in {s.id for s in config.sources if str(s.path.resolve())==draft['source']}:
            raise SafetyError('Planquelle ist nicht mehr freigegeben')
        binding=control.get('job_storage:'+payload['job_id'])
        if not binding:
            raise SafetyError('Staging-Bindung des Quellenplans fehlt')
        resources.staging_for(config,control,binding['staging_id'])
        snapshots(config,control,c,ids)
    finally:c.close()


def snapshots(config,control,catalog,ids):
    result=[];serials=set()
    for ident in ids:
        if maintenance.mode(config,control)=='physical':
            snap=physical_archive.planning_snapshot(config,control,ident)
            serial=snap['header']['medium_serial']
            if serial in serials:raise SafetyError('Dieselbe physische Kassette mehrfach ausgewählt')
            serials.add(serial);record=snap['record'];used=snap['used']
        else:
            record=catalog.db.execute('SELECT * FROM media WHERE id=?',(ident,)).fetchone()
            if record is None or record['state'] not in ('READY','IN_USE'):
                raise SafetyError('Zielmedium nicht beschreibbar')
            if json.loads(record['header_json']).get('backend')!='simulator':
                raise SafetyError('Physische Medien benötigen physischen Betriebsmodus')
            used=record['used']
        result.append(record['capacity']*95//100-used)
    return result


def _prepare(config,control,kind,payload):
    with io_lock():
        c=Catalog(config.catalog)
        try:
            if kind=='plan-source':
                root=next(s.path for s in config.sources if s.id==payload['source_id']).resolve()
                if c.path.is_relative_to(root):raise SafetyError('Katalog darf nicht in der Quelle liegen')
                job=c.job('source-plan',None,'PLANNING')
                try:
                    entries=inventory(root,payload.get('selected_paths'),metadata_only=True,excluded=payload.get('excluded_paths'))
                    # Only size estimation uses a fixed-width checksum placeholder;
                    # the persisted draft contains no file hash or media identity.
                    estimated=estimate_entries(entries)
                    groups=group_entries(estimated,payload.get('target',75_000_000_000))
                    if any(len(encode(group)) > MAX_META-1024 for group in groups):
                        raise SafetyError('TAR-Metadaten zu groß; kleinere TAR-Zielgröße wählen')
                    sizes=[estimate(group)+10240 for group in groups]
                    draft={'source':str(root),'source_id':payload['source_id'],'selected_paths':payload.get('selected_paths'),
                           'excluded_paths':payload.get('excluded_paths'),'target':payload.get('target',75_000_000_000),'verify_mode':payload.get('verify_mode','archive'),
                           'source_entries':entries,'archive_sizes':sizes,'required_estimate':sum(sizes),
                           'largest_archive':max(sizes),'file_count':len(entries),'payload_bytes':sum(e['size'] for e in entries),
                           'hashes_calculated':False,'created':time.time()}
                    draft['sha256']=hashlib.sha256(encode(draft)).hexdigest()
                    with c.db:c.db.execute("UPDATE jobs SET state='WAITING_MEDIA',phase='MEDIA_SELECTION',plan_json=?,updated=? WHERE id=?",(encode(draft).decode(),time.time(),job))
                    control.set('job_storage:'+job,{'source_id':payload['source_id'],
                                'staging_id':payload.get('staging_id',resources.default_staging_id(config,control)),
                                'staging_path':str(resources.staging_for(config,control,payload.get('staging_id',resources.default_staging_id(config,control))))})
                    c.event(job,'source_plan_ready',hashes_calculated=False,required_estimate=draft['required_estimate'])
                    return {'job_id':job,'state':'WAITING_MEDIA',**{k:draft[k] for k in ('sha256','file_count','payload_bytes','required_estimate','largest_archive')}}
                except BaseException as error:
                    c.finish(job,'FAILED',str(error));raise
            state,draft=load(c,payload['job_id'])
            # Recheck after acquiring the global lock, not only at queue time.
            validate(config,control,kind,payload)
            available=snapshots(config,control,c,payload['media_ids']);remaining=available.copy();index=0
            for size in draft['archive_sizes']:
                while index<len(remaining) and remaining[index]<size:index+=1
                if index==len(remaining):
                    result={'state':'WAITING_MEDIA','job_id':payload['job_id'],'required_estimate':draft['required_estimate'],
                            'available':sum(available),'largest_archive':draft['largest_archive'],
                            'message':'Ausgewählte Medien reichen nicht für alle vollständigen TARs. Weitere Medien wählen; Quellenplan bleibt erhalten.'}
                    if draft['largest_archive'] > max(available):
                        result['message']='Ein vollständiges TAR passt auf keines der ausgewählten Medien. Größeres oder ausreichend freies Medium wählen; Einzeldateien werden nicht geteilt.'
                    with c.db:c.db.execute('UPDATE jobs SET report_json=?,updated=? WHERE id=?',(encode(result).decode(),time.time(),payload['job_id']))
                    c.event(payload['job_id'],'more_media_required',**result)
                    return result
                remaining[index]-=size
            root=Path(draft['source'])
            if inventory(root,draft['selected_paths'],metadata_only=True,excluded=draft.get('excluded_paths'))!=draft['source_entries']:
                raise SafetyError('Quelle seit Planung verändert; zuerst neuen Quellenplan erstellen')
            with c.db:
                c.db.execute("UPDATE jobs SET state='RUNNING',phase='HASHING',updated=? WHERE id=?",(time.time(),payload['job_id']))
            return {'_binding':draft}
        finally:c.close()


def execute(config,control,kind,payload):
    prepared=_prepare(config,control,kind,payload)
    if '_binding' not in prepared:
        return prepared
    draft=prepared['_binding'];root=Path(draft['source']);c=Catalog(config.catalog);plan=None
    try:
        physical=maintenance.mode(config,control)=='physical'
        if not physical:
            from .worker import mounted
        if len(payload['media_ids'])>1:
            pairs=[(m,None if physical else mounted(config,control,m)) for m in payload['media_ids']]
            plan=plan_set(c,root,pairs,draft['target'],draft['selected_paths'],draft['verify_mode'],catalogue_only=physical,expected=draft['source_entries'],excluded=draft.get('excluded_paths'))
        else:
            service=ArchiveService(c,None if physical else mounted(config,control,payload['media_ids'][0]))
            planner=service.plan_catalogued if physical else service.plan
            plan=planner(root,payload['media_ids'][0],draft['target'],draft['selected_paths'],draft['verify_mode'],expected=draft['source_entries'],excluded=draft.get('excluded_paths'))
        binding=control.get('job_storage:'+payload['job_id'])
        control.set('job_storage:'+plan['job_id'],binding)
        for child in plan.get('children',[]):control.set('job_storage:'+child['job_id'],binding)
        result={'state':'PLANNED','job_id':plan['job_id'],'source_job_id':payload['job_id'],'sha256':plan['sha256']}
        c.finish(payload['job_id'],'BOUND',report=result)
        return result
    except Exception as error:
        c.finish(payload['job_id'],'INTERRUPTED' if plan is not None else 'WAITING_MEDIA',str(error),
                 report={'job_id':plan['job_id']} if plan is not None else None)
        raise
    finally:c.close()
