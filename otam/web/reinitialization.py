"""Explicit replacement of a completed physical initialization absent from catalog.

No unconditional force flag: registered media, pending writes, reset guards and
uncertain intents remain protected. Simulator resources never act as MAM history.
"""
import hashlib
import json
import uuid
from ..catalog import Catalog
from ..common import SafetyError, encode
from . import initialization, physical_archive

PREFIX = 'reinitialization_approval:'


def eligible(config, control, serial, db, *, own=''):
    if any(b.get('medium_serial') == serial for b in physical_archive.bindings(control).values()):
        raise SafetyError('Registrierte Kassette geschützt; zuerst lesend prüfen, keine erzwungene Initialisierung')
    c = Catalog(config.catalog)
    try:
        for row in c.db.execute('SELECT serial,header_json FROM media'):
            header=json.loads(row['header_json'])
            if header.get('backend') == 'simulator':
                continue
            if row['serial'] == serial or header.get('medium_serial') == serial:
                raise SafetyError('Physischer Katalogeintrag vorhanden; Neuinitialisierung gesperrt')
    finally:
        c.close()
    name=hashlib.sha256(serial.encode()).hexdigest()+'.json'
    for folder in ('physical-pending','physical-reset'):
        marker=config.state/folder/name
        if marker.exists() or marker.is_symlink():
            raise SafetyError('Ungeklärter physischer Schreibvorgang; kein Erzwingen erlaubt')
    prior=[]
    for prefix in (initialization.PREFIX,PREFIX,'reset_approval:'):
        for row in db.execute('SELECT value FROM settings WHERE key LIKE ?',(prefix+'%',)):
            value=json.loads(row[0])
            if value.get('id') == own or value.get('drive',{}).get('medium_serial') != serial:
                continue
            if value.get('state') in ('CONSUMED','INTERRUPTED') or (value.get('write_attempted') and value.get('state') != 'SUCCEEDED'):
                raise SafetyError('Frühere physische Freigabe ungeklärt; kein Erzwingen erlaubt')
            if value.get('state') == 'SUCCEEDED':
                uuid.UUID(value['media_id'])
                prior.append({'approval_id':value['id'],'media_id':value['media_id'],
                              'finished':value['finished'],'sha256':hashlib.sha256(encode(value)).hexdigest()})
    if not prior:
        raise SafetyError('Keine abgeschlossene physische Initialisierung; normalen Initialisierungsworkflow verwenden')
    return sorted(prior,key=lambda x:(x['finished'],x['approval_id']))


def availability(config,control,drive):
    try:
        initialization._workflow(config,control,True)
        physical_archive.validate_registration(config,control,{'drive_id':drive.get('id'),
            'drive_serial':drive.get('serial'),'medium_serial':drive.get('medium_serial')})
        initialization._profile(control.get('hardware_inventory'),drive)
        with control.connect() as db:
            prior=eligible(config,control,drive['medium_serial'],db)
        return {'enabled':True,'reason':'Abgeschlossene Initialisierung vorhanden, aber kein physischer Medienkatalogeintrag.',
                'previous_media_id':prior[-1]['media_id'],'finished':prior[-1]['finished']}
    except (SafetyError,ValueError,KeyError) as error:
        return {'enabled':False,'reason':str(error)}
