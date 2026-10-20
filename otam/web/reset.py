"""Explicit destructive reset of an uncatalogued cartridge with a pending write.

Registered media of every class/state remain protected. This is neither a
general recycling policy nor automatic recovery of an interrupted archive.
"""
from __future__ import annotations

import hashlib
import json
import time
import uuid
from typing import Any

from ..catalog import Catalog
from ..common import FORMAT, SafetyError, encode, sha256
from ..physical import discover_drives
from ..storage import io_lock
from ..tape import LinuxTape
from . import initialization, physical_archive
from .config import WebConfig
from .control import Control

PREFIX = 'reset_approval:'
FIELDS = (*initialization.REVIEW_FIELDS, 'pending_sha256', 'previous_media_id')


def availability(config: WebConfig, control: Control, drive: dict) -> dict:
    try:
        require_enabled(config,control)
        physical_archive.validate_registration(config,control,{'drive_id':drive.get('id'),
            'drive_serial':drive.get('serial'),'medium_serial':drive.get('medium_serial')})
        initialization._profile(control.get('hardware_inventory'),drive)
        with control.connect() as db:
            eligible(config,control,drive['medium_serial'],db)
        return {'enabled':True,'reason':''}
    except (SafetyError, ValueError, KeyError) as error:
        return {'enabled':False,'reason':str(error)}


def require_enabled(config: WebConfig, control: Control) -> None:
    initialization.require_enabled(config, control)
    if not config.physical_reset:
        raise SafetyError('Physisches Zurücksetzen ist administrativ nicht freigegeben')


def digest(grant: dict) -> str:
    return hashlib.sha256(encode({key: grant[key] for key in FIELDS})).hexdigest()


def eligible(config: WebConfig, control: Control, serial: str, db, own: str = '') -> tuple[str, dict]:
    if any(b.get('medium_serial') == serial for b in physical_archive.bindings(control).values()):
        raise SafetyError('Registrierte Kassette geschützt; keine automatische Ausmusterung')
    catalog = Catalog(config.catalog)
    try:
        for row in catalog.db.execute('SELECT serial,header_json FROM media'):
            if row['serial'] == serial or json.loads(row['header_json']).get('medium_serial') == serial:
                raise SafetyError('Katalogisierte Kassette geschützt; keine automatische Ausmusterung')
    finally:
        catalog.close()
    name = hashlib.sha256(serial.encode()).hexdigest() + '.json'
    guard = config.state / 'physical-reset' / name
    if guard.exists() or guard.is_symlink():
        raise SafetyError('Früheres Zurücksetzen ungeklärt; kein erneuter Schreibversuch')
    pending = config.state / 'physical-pending' / name
    if (not pending.is_file() or pending.is_symlink() or pending.stat().st_size > 65536
            or pending.stat().st_nlink != 1):
        raise SafetyError('Kein sicher lesbares Pending-Journal für diese Kassette')
    value = json.loads(pending.read_bytes())
    if value.get('medium_serial') != serial:
        raise SafetyError('Pending-Journal gehört zu einer anderen Kassette')
    uuid.UUID(value['media_id'])
    for row in db.execute('SELECT value FROM settings WHERE key LIKE ?', (PREFIX + '%',)):
        other = json.loads(row[0])
        if (other.get('id') != own and other.get('drive', {}).get('medium_serial') == serial
                and (other.get('state') == 'CONSUMED' or
                     (other.get('state') != 'SUCCEEDED' and other.get('write_attempted')))):
            raise SafetyError('Frühere Reset-Freigabe ungeklärt; lesende Prüfung erforderlich')
    return sha256(pending), value


def prepare(config: WebConfig, control: Control, data: dict[str, Any]) -> dict:
    require_enabled(config, control)
    if (set(data) != {'drive_id','drive_serial','medium_serial','label','media_class'}
            or not isinstance(data.get('label'), str) or not 1 <= len(data['label'].strip()) <= 100
            or any(ord(c) < 32 for c in data['label']) or data.get('media_class') not in ('permanent','rotation')):
        raise SafetyError('Eindeutige Medienidentität, Bezeichnung und Medienklasse erforderlich')
    identity = {k:data[k] for k in ('drive_id','drive_serial','medium_serial')}
    drive = physical_archive.validate_registration(config, control, identity)
    profile = initialization._profile(control.get('hardware_inventory'), drive)
    with control.connect() as db:
        pending_hash, pending = eligible(config, control, data['medium_serial'], db)
    now = time.time()
    grant = {'id':str(uuid.uuid4()),'node_id':config.node_id,'drive':drive,'profile_id':profile['profile_id'],
             'capacity':profile['native_capacity_bytes'],'label':data['label'].strip(),'media_class':data['media_class'],
             'created':now,'expires':now+300,'confirmation':f"RESET {drive['serial']} {drive['medium_serial']}",
             'pending_sha256':pending_hash,'previous_media_id':pending['media_id'],'state':'PREPARED','write_attempted':False}
    grant['review_hash'] = digest(grant)
    control.set(PREFIX + grant['id'], grant)
    return grant


def approval(config: WebConfig, control: Control, payload: dict, *, consume: bool = False) -> dict:
    require_enabled(config, control)
    if (set(payload) != {'approval_id','confirmation','destructive_confirmed'}
            or payload['destructive_confirmed'] is not True or not isinstance(payload['approval_id'],str)):
        raise SafetyError('Ausdrückliche Freigabe des destruktiven Zurücksetzens erforderlich')
    uuid.UUID(payload['approval_id'])
    with control.connect() as db:
        if consume:
            db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT value FROM settings WHERE key=?',(PREFIX+payload['approval_id'],)).fetchone()
        grant = json.loads(row[0]) if row else None
        now = time.time()
        if (not grant or not set(FIELDS) <= grant.keys() or grant.get('state') != 'PREPARED'
                or grant.get('node_id') != config.node_id or type(grant.get('created')) not in (int,float)
                or not 0 <= now-grant['created'] <= 300 or grant.get('expires') != grant['created']+300
                or payload['confirmation'] != grant.get('confirmation') or grant.get('review_hash') != digest(grant)):
            raise SafetyError('Reset-Freigabe fehlt, ist verändert, abgelaufen oder verbraucht')
        checksum, _ = eligible(config, control, grant['drive']['medium_serial'], db, own=grant['id'])
        if checksum != grant['pending_sha256']:
            raise SafetyError('Pending-Journal hat sich seit dem Review geändert')
        if consume:
            grant.update(state='CONSUMED',consumed=now)
            db.execute('UPDATE settings SET value=? WHERE key=?',(json.dumps(grant),PREFIX+grant['id']))
    return grant


def execute(config: WebConfig, control: Control, payload: dict) -> dict:
    grant = approval(config, control, payload, consume=True)
    catalog = Catalog(config.catalog)
    job, header = None, None
    def progress(state, phase, **details):
        control.set('maintenance_progress:'+grant['id'], {'state':state,'phase':phase,'time':time.time(),
                    'operation':'reset','drive':grant['drive'],'approval_id':grant['id'],**details})
    try:
        progress('RUNNING','PRECHECK')
        with io_lock():
            drives = [d for d in discover_drives() if all(d.get(k)==grant['drive'][k] for k in ('id','serial','medium_serial'))]
            if len(drives) != 1:
                raise SafetyError('Drive/MAM-Identität hat sich geändert')
            drive = drives[0]
            profile = initialization._profile({'time':time.time(),'drives':[drive]},drive)
            if profile['profile_id'] != grant['profile_id'] or profile['native_capacity_bytes'] != grant['capacity']:
                raise SafetyError('Laufwerksprofil oder native Kapazität hat sich geändert')
            tape = LinuxTape(drive,config.state)
            with tape.locked():
                with control.connect() as db:
                    checksum, _ = eligible(config,control,drive['medium_serial'],db,own=grant['id'])
                    if checksum != grant['pending_sha256']:
                        raise SafetyError('Pending-Journal hat sich geändert')
                job = catalog.job('reset',None)
                catalog.event(job,'physical_reset_confirmed',approval_id=grant['id'],review_hash=grant['review_hash'],
                              pending_sha256=checksum,previous_media_id=grant['previous_media_id'],
                              drive_serial=drive['serial'],medium_serial=drive['medium_serial'])
                grant['write_attempted']=True
                control.set(PREFIX+grant['id'],grant)
                progress('RUNNING','HEADER_WRITE')
                header = tape.reset_interrupted(grant['label'],grant['capacity'],grant['media_class'],
                                                checksum,grant['id'],grant['confirmation'])
                if (header != tape.header() or tape.positions()!=[0] or header.get('format')!=FORMAT
                        or header.get('backend')!='physical' or header.get('medium_serial')!=drive['medium_serial']
                        or header.get('label')!=grant['label'] or header.get('capacity')!=grant['capacity']
                        or header.get('class')!=grant['media_class'] or header.get('media_id')==grant['previous_media_id']):
                    raise SafetyError('Neuer Header nach Reset nicht bestätigt')
                uuid.UUID(header['media_id'])
                catalog.register(header,tape.used())
                with catalog.db:
                    catalog.db.execute("UPDATE media SET serial=?,state='SUSPECT' WHERE id=?",(drive['medium_serial'],header['media_id']))
                    catalog.db.execute('UPDATE jobs SET media_id=? WHERE id=?',(header['media_id'],job))
                saved=physical_archive.bindings(control)
                saved[header['media_id']]={'media_id':header['media_id'],'drive_serial':drive['serial'],
                                         'medium_serial':drive['medium_serial'],'registered':time.time()}
                control.set('physical_media_bindings',saved)
                tape.complete_reset(grant['id'],header['media_id'])
                result={'state':'INITIALIZED','job_id':job,'media_id':header['media_id'],'header':header,
                        'scope':'new logical tape and verified header; not secure erasure or new full qualification'}
                with catalog.db:
                    catalog.db.execute("UPDATE media SET state='READY' WHERE id=?",(header['media_id'],))
                catalog.finish(job,'SUCCEEDED',report=result)
                grant.update(state='SUCCEEDED',finished=time.time(),media_id=header['media_id'])
                control.set(PREFIX+grant['id'],grant)
                progress('SUCCEEDED','INITIALIZED',result=result)
                control.sync_event('config','UPDATED',None,'Unterbrochenes Medium ausdrücklich zurückgesetzt: '+header['media_id'])
                return result
    except BaseException as error:
        grant.update(state='FAILED',finished=time.time(),error=str(error))
        control.set(PREFIX+grant['id'],grant)
        progress('FAILED','INCOMPLETE' if grant['write_attempted'] else 'NOT_STARTED',error=str(error))
        if header is not None:
            with catalog.db:
                catalog.db.execute("UPDATE media SET state='SUSPECT' WHERE id=?",(header['media_id'],))
        if job is not None:
            catalog.finish(job,'FAILED',str(error))
        raise
    finally:
        catalog.close()
