"""Worker integration for explicitly reviewed rolling full backups."""
from __future__ import annotations
import json
import time
from pathlib import Path
from .. import rotation as model, source_capture
from ..catalog import Catalog
from ..common import SafetyError, encode
from ..storage import io_lock
from ..tape import LinuxTape, SimulatedTape
from ..physical import discover_drives
from . import maintenance, resources, source_plans, physical_archive, initialization

COMMANDS = {'plan-rotation', 'bind-rotation', 'recycle-rotation', 'restore-rotation', 'cleanup-rotation'}


def capture(config, control, c, g):
    if not g['source_job']:
        raise SafetyError('Vollständige lokale Quellenaufnahme fehlt')
    _, draft = source_plans.load(c, g['source_job'])
    if (not draft.get('source_capture') or draft.get('backup_mode', 'full') != 'full'
            or json.loads(g['data_json'])['backend'] != maintenance.mode(config, control)):
        raise SafetyError('Rollierende Sicherung benötigt eine vollständige Quellenaufnahme')
    binding = control.get('job_storage:' + g['source_job'])
    staging = resources.staging_for(config, control, binding['staging_id'])
    if json.loads(g['data_json']).get('source_capture_storage') == 'packed-bound-v1':
        from ..packed_capture import validate_bound
        validate_bound(c, staging, g)
    else:
        source_capture.validate(staging, g['source_job'], draft['source_capture'])
    return draft


def validate(config, control, kind, payload):
    if config.role != 'archive':
        raise SafetyError('Archivnode erforderlich')
    if kind == 'plan-rotation':
        if set(payload) != {'policy_id', 'set_id', 'consistent_source'} or payload['consistent_source'] is not True:
            raise SafetyError('Unveränderlichen konsistenten Quellenstand ausdrücklich bestätigen')
    elif kind in ('bind-rotation', 'cleanup-rotation'):
        if set(payload) != {'generation_id'}:
            raise SafetyError('Generations-ID erforderlich')
    elif kind == 'restore-rotation':
        if set(payload) == {'restore_job'}:
            import uuid
            uuid.UUID(payload['restore_job'])
        elif set(payload) == {'generation_id', 'target_name'}:
            from ..common import safe_path
            name = payload['target_name']
            if not isinstance(name, str) or not name or len(name) > 100 or name.startswith('.') or '/' in name:
                raise SafetyError('Einfacher neuer Restorezielname erforderlich')
            safe_path(name)
        else:
            raise SafetyError('Generation und neues Ziel oder bestehender Restoreauftrag erforderlich')
    elif kind == 'recycle-rotation':
        if set(payload) != {'approval_id', 'confirmation', 'destructive_confirmed'} or payload['destructive_confirmed'] is not True:
            raise SafetyError('Ausdrückliche Wiederverwendungsfreigabe erforderlich')
        if maintenance.mode(config, control) == 'physical' and not config.physical_rotation:
            raise SafetyError('Physische Rotation benötigt separate administrative Abnahme')
    else:
        raise SafetyError('Unbekannter Rotationsauftrag')
    for key in ('policy_id', 'set_id', 'generation_id', 'approval_id'):
        if key in payload:
            import uuid
            uuid.UUID(payload[key])


def plan(config, control, payload):
    c = Catalog(config.catalog)
    key = model.ident()
    try:
        with c.db:
            c.db.execute('BEGIN IMMEDIATE')
            p = model.require_policy(c, payload['policy_id'])
            s = model.row(c, 'tape_sets', payload['set_id'])
            if s['policy_id'] != p['id'] or model.active(c, p['id']):
                raise SafetyError('Falscher Bandsatz oder bereits aktive Generation')
            # Failed generations retain their captures; uncertain recycling is never bypassed.
            if c.db.execute("SELECT 1 FROM recycle_intents i JOIN backup_generations g ON g.id=i.generation_id "
                            "WHERE g.policy_id=? AND i.state IN ('CONSUMED','WRITING','INTERRUPTED')", (p['id'],)).fetchone():
                raise SafetyError('Ungeklärte Wiederverwendung sperrt neue Generation')
            data = {'backend': maintenance.mode(config, control), 'consistent_source_confirmed': True}
            c.db.execute('INSERT INTO backup_generations VALUES(?,?,?,?,NULL,NULL,?,?,NULL)',
                         (key, p['id'], s['id'], 'PREPARING', encode(data).decode(), time.time()))
        opts = json.loads(p['options_json'])
        request = {k: opts[k] for k in ('source_id', 'staging_id', 'target', 'excluded_paths')}
        request.update(backup_mode='full', verify_mode='media', symlink_policy='error')
        result = source_plans.execute(config, control, 'plan-source', request)
        model.update_generation(c, key, 'PREPARING', source_job=result['job_id'])
        if not result.get('file_count'):
            raise SafetyError('Leere Quelle darf keinen vorhandenen Bandsatz ersetzen')
        source_plans.execute(config, control, 'stage-source',
                             {'job_id': result['job_id'], 'source_plan_hash': result['sha256']})
        g = model.row(c, 'backup_generations', key)
        draft = capture(config, control, c, g)
        entries = draft['source_capture']['entries']
        inventory = [{k: e[k] for k in ('path', 'size', 'sha256')} for e in entries]
        data.update(inventory_sha256=model.digest(inventory), file_count=len(entries),
                    payload_bytes=draft['payload_bytes'], source_capture_retained=True)
        model.update_generation(c, key, 'WAITING_CAPACITY', data)
        model.capacity_plan(c, key, draft)
        return {'generation_id': key, **model.row(c, 'backup_generations', key)}
    except BaseException as error:
        if c.db.execute('SELECT 1 FROM backup_generations WHERE id=?', (key,)).fetchone():
            g = model.row(c, 'backup_generations', key); d = json.loads(g['data_json']); d['error'] = str(error)
            model.update_generation(c, key, 'INTERRUPTED' if isinstance(error, (KeyboardInterrupt, SystemExit)) else 'FAILED', d)
        raise
    finally:
        c.close()


def bind(config, control, payload):
    c = Catalog(config.catalog)
    key = payload['generation_id']
    try:
        g = model.row(c, 'backup_generations', key)
        if g['state'] not in ('WAITING_CAPACITY', 'WAITING_APPROVAL', 'WAITING_MEDIA') or g['archive_job']:
            raise SafetyError('Generation kann nicht erneut gebunden werden')
        draft = capture(config, control, c, g)
        data = model.capacity_plan(c, key, draft)
        if not data['media_ids']:
            return {'generation_id': key, 'state': 'WAITING_CAPACITY', **data}
        if data['recycle_media']:
            return {'generation_id': key, 'state': 'WAITING_APPROVAL', **data}
        # Read-only validation above. The bind call builds all immutable TARs from the owned copy.
        model.update_generation(c, key, 'BINDING', data)
        try:
            result = source_plans.execute(config, control, 'bind-plan',
                                          {'job_id': g['source_job'], 'source_plan_hash': draft['sha256'], 'media_ids': data['media_ids']})
        except BaseException:
            model.update_generation(c, key, 'INTERRUPTED')
            raise
        if result['state'] != 'PLANNED':
            model.update_generation(c, key, 'WAITING_CAPACITY', data)
            return result
        with c.db:
            for medium in data['media_ids']:
                c.db.execute('INSERT INTO generation_volumes VALUES(?,?)', (key, medium))
        if draft['source_capture'].get('format') == 'otam-packed-source-v1':
            data['source_capture_storage'] = 'packed-bound-v1'
        model.update_generation(c, key, 'WAITING_MEDIA', data, archive_job=result['job_id'])
        return {'generation_id': key, **result}
    finally:
        c.close()


def review(config, control, payload):
    if set(payload) != {'generation_id', 'media_id'}:
        raise SafetyError('Generation und konkrete Medien-ID erforderlich')
    if maintenance.mode(config, control) == 'physical' and not config.physical_rotation:
        raise SafetyError('Physische Rotation ist bis zur Abnahme administrativ gesperrt')
    c = Catalog(config.catalog)
    try:
        g = model.row(c, 'backup_generations', payload['generation_id'])
        capture(config, control, c, g)
        value = model.recycle_eligibility(c, g['id'], payload['media_id'])
        value['drive_binding'] = None
        if value['header']['backend'] == 'physical':
            value['drive_binding'] = physical_archive.bindings(control).get(payload['media_id'])
            if not value['drive_binding']:
                raise SafetyError('Dauerhafte Drive-/MAM-Bindung fehlt')
        value.update(id=model.ident(), node_id=config.node_id, created=time.time())
        value['confirmation'] = 'RECYCLE ' + str(value['header'].get('medium_serial', payload['media_id']))
        value['sha256'] = model.digest(value)
        with c.db:
            c.db.execute('INSERT INTO recycle_intents VALUES(?,?,?,?,?,?,NULL)',
                         (value['id'], g['id'], payload['media_id'], 'PREPARED', encode(value).decode(), value['created']))
        return value
    finally:
        c.close()


def queued_device_jobs(control):
    with control.connect() as db:
        return db.execute("SELECT 1 FROM commands WHERE state='QUEUED' AND kind IN "
                          "('restore','backup','backup-set','verify','recover','rebuild','initialize-physical',"
                          "'reset-physical','reinitialize-physical','tape-maintenance') LIMIT 1").fetchone() is not None


def recycle(config, control, payload):
    c = Catalog(config.catalog); key = payload['approval_id']; consumed = False
    try:
        with io_lock():
            with c.db:
                c.db.execute('BEGIN IMMEDIATE')
                intent = model.row(c, 'recycle_intents', key)
                grant = json.loads(intent['review_json'])
                checksum = grant.pop('sha256'); grant['sha256'] = checksum
                if (intent['state'] != 'PREPARED' or grant['node_id'] != config.node_id
                        or not 0 <= time.time() - grant['created'] <= 300
                        or model.digest({k:v for k,v in grant.items() if k != 'sha256'}) != checksum
                        or payload['confirmation'] != grant['confirmation']):
                    raise SafetyError('Freigabe verbraucht, verändert oder abgelaufen')
                expected = model.recycle_eligibility(c, intent['generation_id'], intent['media_id'])
                if any(expected[k] != grant[k] for k in expected):
                    raise SafetyError('Katalog oder Schutzregeln seit Review verändert')
                if (grant['header']['backend'] == 'physical'
                        and physical_archive.bindings(control).get(intent['media_id']) != grant.get('drive_binding')):
                    raise SafetyError('Drive-/MAM-Bindung seit Review verändert')
                g = model.row(c, 'backup_generations', intent['generation_id'])
                capture(config, control, c, g)
                if queued_device_jobs(control):
                    raise SafetyError('Eingereihter Geräteauftrag sperrt Wiederverwendung')
                c.db.execute("UPDATE recycle_intents SET state='CONSUMED' WHERE id=?", (key,))
                consumed = True
            old = model.row(c, 'media', intent['media_id'])
            if grant['header']['backend'] != maintenance.mode(config, control):
                raise SafetyError('Betriebsart geändert')
            physical = grant['header']['backend'] == 'physical'
            if physical:
                physical_archive.require_mode(config, control)
                binding = physical_archive.bindings(control).get(old['id'])
                if not binding:
                    raise SafetyError('Dauerhafte physische Medienbindung fehlt')
                matches = [d for d in discover_drives() if d.get('serial') == binding['drive_serial']
                           and d.get('medium_serial') == binding['medium_serial']]
                if len(matches) != 1:
                    raise SafetyError('Freigegebene Kassette nicht im gebundenen Laufwerk')
                drive = matches[0]
                profile = initialization._profile({'time': time.time(), 'drives': matches}, drive)
                if profile['native_capacity_bytes'] != old['capacity']:
                    raise SafetyError('Frisches Medienprofil passt nicht zur bestätigten Kapazität')
                tape = LinuxTape(drive, config.state)
            else:
                from .worker import mounted
                tape = mounted(config, control, old['id'])
            with tape.locked():
                if physical and (tape._pending.exists() or tape._pending.is_symlink()
                                 or tape._reset.exists() or tape._reset.is_symlink()):
                    raise SafetyError('Offenes physisches Sicherheitsjournal sperrt Wiederverwendung')
                if tape.has_partial() or tape.header() != grant['header']:
                    raise SafetyError('Pending oder abweichender Header; kein Überschreiben')
                if physical:
                    reset_path = tape._reset
                    if reset_path.exists() or reset_path.is_symlink():
                        raise SafetyError('Offenes Resetjournal sperrt Wiederverwendung')
                    from ..service import inspect_catalogued_media
                    inspect_catalogued_media(c, tape, old['id'])
                # Retire BEFORE any possible write. Failure stays unavailable and requires inspection.
                with c.db:
                    c.db.execute("UPDATE media SET state='RETIRED' WHERE id=?", (old['id'],))
                    c.db.execute("UPDATE recycle_intents SET state='WRITING' WHERE id=?", (key,))
                    for affected in grant['affected']:
                        c.db.execute("UPDATE backup_generations SET state='UNAVAILABLE' WHERE id=?", (affected,))
                if physical:
                    header = tape.initialize(old['label'], old['capacity'], 'rotation', 'INITIALIZE ' + drive['medium_serial'])
                    used = tape.used()
                else:
                    new_path = config.media_root / model.ident()
                    new_tape = SimulatedTape.create(new_path, old['label'], old['capacity'], 'rotation')
                    with new_tape.locked():
                        header = new_tape.header(); used = new_tape.used()
                    with control.connect() as db:
                        db.execute('INSERT INTO resources VALUES(?,?)', (header['media_id'], str(new_path)))
                if header['media_id'] == old['id']:
                    raise SafetyError('Neue Medien-Inkarnation fehlt')
                c.register(header, used)
                if physical:
                    saved = physical_archive.bindings(control)
                    saved[header['media_id']] = {**binding, 'media_id': header['media_id'], 'registered': time.time()}
                    control.set('physical_media_bindings', saved)
                with c.db:
                    now = time.time()
                    c.db.execute('UPDATE tape_set_members SET removed=? WHERE media_id=? AND removed IS NULL', (now, old['id']))
                    c.db.execute('INSERT INTO tape_set_members VALUES(?,?,?,?,NULL)', (model.ident(), g['set_id'], header['media_id'], now))
                    c.db.execute("UPDATE recycle_intents SET state='SUCCEEDED',new_media_id=? WHERE id=?", (header['media_id'], key))
                    c.db.execute('UPDATE media SET serial=? WHERE id=?', (header.get('medium_serial'), header['media_id']))
                c.event(g['source_job'], 'rotation_recycled', approval_id=key, old_media_id=old['id'], new_media_id=header['media_id'])
                return {'state': 'SUCCEEDED', 'media_id': header['media_id'], 'old_media_id': old['id']}
    except BaseException:
        if consumed:
            with c.db:
                c.db.execute("UPDATE recycle_intents SET state=CASE WHEN state='CONSUMED' THEN 'FAILED' ELSE 'INTERRUPTED' END "
                             "WHERE id=? AND state!='SUCCEEDED'", (key,))
        raise
    finally:
        c.close()


def execute(config, control, kind, payload):
    validate(config, control, kind, payload)
    config = resources.effective(config, control)
    return {'plan-rotation': plan, 'bind-rotation': bind, 'recycle-rotation': recycle,
            'restore-rotation': restore, 'cleanup-rotation': cleanup}[kind](config, control, payload)


def restore(config, control, payload):
    """Restore one volume per explicit queue action into a private complete-set root."""
    import os
    from ..service import ArchiveService
    from ..archive import inventory
    from .worker import mounted
    c = Catalog(config.catalog)
    job_id = payload.get('restore_job')
    started = False
    owned = False
    try:
        with io_lock():
            if job_id:
                j = c.db.execute("SELECT * FROM jobs WHERE id=? AND kind='rotation-restore'", (job_id,)).fetchone()
                if not j or j['state'] != 'WAITING_MEDIA':
                    raise SafetyError('Restore ist nicht am sicheren Medienwechselpunkt')
                owned = True
                plan = json.loads(j['plan_json'])
                g = model.row(c, 'backup_generations', plan['generation_id'])
            else:
                g = model.row(c, 'backup_generations', payload['generation_id'])
                if g['state'] != 'VERIFIED' or g['id'] not in {x['id'] for x in model.available_generations(c, g['policy_id'])}:
                    raise SafetyError('Nur vollständig verfügbare Generation wiederherstellbar')
                config.restore_root.mkdir(parents=True, exist_ok=True, mode=0o700)
                target = config.restore_root / payload['target_name']
                if target.exists() or target.is_symlink():
                    raise SafetyError('Neues Restoreziel erforderlich')
                plan = {'generation_id': g['id'], 'target_name': payload['target_name'], 'done': [],
                        'media_ids': json.loads(g['data_json'])['media_ids']}
                job_id = c.job('rotation-restore', None, 'WAITING_MEDIA', plan=plan)
                owned = True
                (config.restore_root / ('.otam-generation-' + job_id)).mkdir(mode=0o700, exist_ok=False)
            remaining = [m for m in plan['media_ids'] if m not in plan['done']]
            if not remaining:
                raise SafetyError('Restore bereits abgeschlossen')
            medium = remaining[0]
            # Validate reservation and availability atomically relative to worker-owned recycling.
            if g['state'] != 'VERIFIED':
                raise SafetyError('Generation nicht mehr vollständig verfügbar')
        # ArchiveService acquires the shared I/O/device locks itself.
        tape = mounted(config, control, medium)
        temporary = config.restore_root / ('.otam-generation-' + job_id)
        if temporary.is_symlink() or not temporary.is_dir():
            raise SafetyError('Privates Restoreziel fehlt oder ist unsicher')
        with c.db:
            c.db.execute("UPDATE jobs SET state='RUNNING',updated=? WHERE id=?", (time.time(), job_id))
        started = True
        ArchiveService(c, tape).restore(medium, temporary)
        plan['done'].append(medium)
        state = 'WAITING_MEDIA'
        if len(plan['done']) == len(plan['media_ids']):
            entries = inventory(temporary)
            hashes = [{k:e[k] for k in ('path', 'size', 'sha256')} for e in entries]
            data = json.loads(g['data_json'])
            if (model.digest(hashes) != data['inventory_sha256'] or len(entries) != data['file_count']
                    or sum(e['size'] for e in entries) != data['payload_bytes']):
                raise SafetyError('Gesamtbestand des Restores stimmt nicht mit der Generation überein')
            target = config.restore_root / plan['target_name']
            if target.exists() or target.is_symlink():
                raise SafetyError('Restoreziel wurde inzwischen angelegt')
            # A hard-link publication below an exclusively created directory cannot replace user files.
            target.mkdir(mode=0o700, exist_ok=False)
            for e in entries:
                source = temporary / e['path']; dest = target / e['path']
                dest.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                os.link(source, dest)
            state = 'VERIFIED'
        with c.db:
            c.db.execute('UPDATE jobs SET plan_json=? WHERE id=?', (encode(plan).decode(), job_id))
        result = {'restore_job': job_id, 'state': state, 'target_name': plan['target_name'],
                  'next_media_id': next((m for m in plan['media_ids'] if m not in plan['done']), None)}
        c.finish(job_id, state, report=result)
        return result
    except BaseException as error:
        if job_id and owned:
            state = 'FAILED' if started else 'WAITING_MEDIA'
            result = {'restore_job':job_id, 'state':state, 'next_media_id':locals().get('medium'), 'error':str(error)}
            c.finish(job_id, state, str(error), report=result)
            if not started and isinstance(error, SafetyError):
                return result
        raise
    finally:
        c.close()


def cleanup(config, control, payload):
    c = Catalog(config.catalog)
    try:
        with io_lock():
            g = model.row(c, 'backup_generations', payload['generation_id'])
            if g['state'] != 'VERIFIED' or g['id'] not in {x['id'] for x in model.available_generations(c, g['policy_id'])}:
                raise SafetyError('Quellenaufnahme nur nach vollständig verfügbarem Bandabschluss bereinigen')
            data = json.loads(g['data_json'])
            if not data.get('source_capture_retained'):
                return {'state': 'UNCHANGED'}
            if data.get('source_capture_storage') == 'packed-bound-v1':
                from ..staging import StagingStore
                binding = control.get('job_storage:' + g['source_job'])
                staging = resources.staging_for(config, control, binding['staging_id'])
                store = StagingStore(c, staging)
                for job in c.db.execute("SELECT id,plan_json FROM jobs WHERE json_extract(plan_json,'$.packed_source_job')=?", (g['source_job'],)).fetchall():
                    for manifest in json.loads(job['plan_json'])['archives']:
                        if store.row(job['id'], manifest['archive_id'])['phase'] == 'STAGING_CLEANUP':
                            continue
                        store.assert_ready_identity(job['id'], manifest)
                        store.cleanup(job['id'], manifest['archive_id'], release_generation=True)
                data['source_capture_retained'] = False
                model.update_generation(c, g['id'], g['state'], data)
                c.event(g['source_job'], 'rotation_source_cleaned', generation_id=g['id'], storage='packed TARs')
                return {'state': 'SUCCEEDED'}
            draft = capture(config, control, c, g)
            binding = control.get('job_storage:' + g['source_job'])
            staging = resources.staging_for(config, control, binding['staging_id'])
            source_capture.cleanup(staging, g['source_job'], draft['source_capture'])
            data['source_capture_retained'] = False
            model.update_generation(c, g['id'], g['state'], data)
            c.event(g['source_job'], 'rotation_source_cleaned', generation_id=g['id'])
            return {'state': 'SUCCEEDED'}
    finally:
        c.close()
