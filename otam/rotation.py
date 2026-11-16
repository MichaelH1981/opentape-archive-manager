"""Durable full-generation tape sets. No device access in this module.

Retention eligibility is not permission to overwrite. Historical media/archives
are retained; unavailable incarnations never establish an additive baseline.
"""
from __future__ import annotations
import hashlib
import json
import time
import uuid
from .common import SafetyError, encode
from .allocation import allocate

TERMINAL = ('VERIFIED', 'FAILED', 'INTERRUPTED', 'UNAVAILABLE', 'CANCELLED')


def ident():
    return str(uuid.uuid4())


def digest(value):
    return hashlib.sha256(encode(value)).hexdigest()


def row(c, table, key):
    if table not in ('backup_policies', 'tape_sets', 'backup_generations', 'media', 'recycle_intents'):
        raise ValueError('Invalid rotation table')
    found = c.db.execute(f'SELECT * FROM {table} WHERE id=?', (key,)).fetchone()
    if found is None:
        raise SafetyError('Sicherungsregel, Bandsatz oder Generation fehlt')
    return dict(found)


def active(c, policy):
    return c.db.execute("SELECT id FROM backup_generations WHERE policy_id=? AND state NOT IN "
                        "('VERIFIED','FAILED','INTERRUPTED','UNAVAILABLE','CANCELLED')", (policy,)).fetchone()


def require_policy(c, key):
    p = row(c, 'backup_policies', key)
    if json.loads(p['options_json']).get('deleted_at'):
        raise SafetyError('Sicherungsregel ist gelöscht; zuerst ausdrücklich wiederherstellen')
    return p


def delete_policy(c, key, confirmation, restore=False):
    """Remove a rule from use; preserve all generations, protection and media bindings."""
    if confirmation != key:
        raise SafetyError('Regel-ID zur Bestätigung erforderlich')
    with c.db:
        c.db.execute('BEGIN IMMEDIATE')
        p = row(c, 'backup_policies', key)
        options = json.loads(p['options_json'])
        if active(c, key):
            raise SafetyError('Regel während einer aktiven Generation gesperrt')
        if c.db.execute("SELECT 1 FROM recycle_intents i JOIN backup_generations g ON g.id=i.generation_id "
                        "WHERE g.policy_id=? AND i.state IN ('CONSUMED','WRITING','INTERRUPTED')", (key,)).fetchone():
            raise SafetyError('Ungeklärte Wiederverwendung sperrt das Löschen oder Wiederherstellen der Regel')
        if c.db.execute("SELECT 1 FROM jobs j JOIN backup_generations g ON j.id=g.source_job OR j.id=g.archive_job "
                        "WHERE g.policy_id=? AND j.state IN ('RUNNING','PLANNING','PLANNED','STAGED','WAITING_MEDIA')", (key,)).fetchone():
            raise SafetyError('Zugehöriger Quellen- oder Archivauftrag ist noch aktiv')
        if restore:
            options.pop('deleted_at', None)
        elif not options.get('deleted_at'):
            options['deleted_at'] = time.time()
        c.db.execute('UPDATE backup_policies SET options_json=? WHERE id=?', (encode(options).decode(), key))
        if not restore:
            c.db.execute("UPDATE recycle_intents SET state='CANCELLED' WHERE state='PREPARED' AND generation_id IN "
                         "(SELECT id FROM backup_generations WHERE policy_id=?)", (key,))
        c.db.execute('INSERT INTO events(job_id,time,level,event,details_json) VALUES(NULL,?,?,?,?)',
                     (time.time(), 'INFO', 'rotation_policy_restored' if restore else 'rotation_policy_deleted',
                      encode({'policy_id':key,'history_preserved':True,'media_bindings_preserved':True}).decode()))
    return {'id':key,'state':'ACTIVE' if restore else 'DELETED','history_preserved':True}


def policy(c, data, policy_id=None):
    allowed = {'name', 'source_id', 'staging_id', 'set_count', 'keep_during_update', 'retain_days',
               'target', 'excluded_paths'}
    if set(data) != allowed:
        raise SafetyError('Vollständige Sicherungsregel erforderlich')
    if (not isinstance(data['name'], str) or not 1 <= len(data['name'].strip()) <= 100
            or any(ord(x) < 32 for x in data['name'])
            or not all(isinstance(data[x], str) and data[x] for x in ('source_id', 'staging_id'))
            or type(data['set_count']) is not int or not 1 <= data['set_count'] <= 32
            or type(data['keep_during_update']) is not int or not 0 <= data['keep_during_update'] < data['set_count']
            or type(data['retain_days']) is not int or not 0 <= data['retain_days'] <= 36500
            or type(data['target']) is not int or not 10240 <= data['target'] <= 10**13
            or not isinstance(data['excluded_paths'], list) or len(data['excluded_paths']) > 10000):
        raise SafetyError('Ungültige Bandsatzanzahl, Schutzregel oder Quelle')
    from .common import safe_path
    for path in data['excluded_paths']:
        if not isinstance(path, str):
            raise SafetyError('Ungültiger Ausschluss')
        safe_path(path)
    options = {k: v for k, v in data.items() if k != 'name'}
    key = policy_id or ident()
    with c.db:
        c.db.execute('BEGIN IMMEDIATE')
        if policy_id:
            require_policy(c, key)
            if active(c, key):
                raise SafetyError('Regel während einer aktiven Generation gesperrt')
            count = c.db.execute('SELECT count(*) FROM tape_sets WHERE policy_id=?', (key,)).fetchone()[0]
            if count > options['set_count']:
                raise SafetyError('Bestehende Sätze werden nicht automatisch entfernt; Satzanzahl darf hier nur wachsen')
            c.db.execute('UPDATE backup_policies SET name=?,options_json=? WHERE id=?',
                         (data['name'].strip(), encode(options).decode(), key))
        else:
            c.db.execute('INSERT INTO backup_policies VALUES(?,?,?,?)',
                         (key, data['name'].strip(), encode(options).decode(), time.time()))
            count = 0
        for index in range(count, options['set_count']):
            c.db.execute('INSERT INTO tape_sets VALUES(?,?,?,?)',
                         (ident(), key, f"Satz {index+1}", time.time()))
    return {'id': key}


def members(c, set_id):
    return [dict(r) for r in c.db.execute('SELECT m.* FROM tape_set_members s JOIN media m ON m.id=s.media_id '
                                         'WHERE s.set_id=? AND s.removed IS NULL ORDER BY s.added,s.id', (set_id,))]


def add_member(c, set_id, media_id, backend):
    with c.db:
        c.db.execute('BEGIN IMMEDIATE')
        s = row(c, 'tape_sets', set_id)
        require_policy(c, s['policy_id'])
        m = row(c, 'media', media_id)
        h = json.loads(m['header_json'])
        if m['class'] != 'rotation' or m['state'] not in ('READY', 'IN_USE') or h.get('backend') != backend:
            raise SafetyError('Nur verfügbare Rotationsmedien derselben Betriebsart hinzufügen')
        if len(members(c, set_id)) >= 32:
            raise SafetyError('Ein Bandsatz unterstützt höchstens 32 Kassetten')
        if c.db.execute('SELECT 1 FROM tape_set_members WHERE media_id=? AND removed IS NULL', (media_id,)).fetchone():
            raise SafetyError('Kassette gehört bereits zu einem Bandsatz')
        if c.db.execute("SELECT 1 FROM jobs WHERE media_id=? AND state IN "
                        "('RUNNING','PLANNING','PLANNED','STAGED','WAITING_MEDIA','FAILED','INTERRUPTED')", (media_id,)).fetchone():
            raise SafetyError('Kassette hat noch aktive oder ungeklärte Aufträge')
        serial = h.get('medium_serial')
        if serial and c.db.execute("SELECT 1 FROM tape_set_members s JOIN media m ON m.id=s.media_id "
                                   "WHERE s.removed IS NULL AND json_extract(m.header_json,'$.medium_serial')=?", (serial,)).fetchone():
            raise SafetyError('Physische Kassette ist bereits in einem Bandsatz gebunden')
        running = active(c, s['policy_id'])
        if running:
            g = row(c, 'backup_generations', running[0])
            if g['archive_job'] or g['state'] not in ('WAITING_CAPACITY', 'WAITING_APPROVAL', 'WAITING_MEDIA'):
                raise SafetyError('Erweiterung nur vor dem gebundenen Schreibplan möglich')
        c.db.execute('INSERT INTO tape_set_members VALUES(?,?,?,?,NULL)',
                     (ident(), set_id, media_id, time.time()))
    return {'set_id': set_id, 'media_id': media_id}


def update_generation(c, generation, state, data=None, **fields):
    with c.db:
        c.db.execute('UPDATE backup_generations SET state=?,data_json=COALESCE(?,data_json),'
                     'source_job=COALESCE(?,source_job),archive_job=COALESCE(?,archive_job),'
                     'completed=COALESCE(?,completed) WHERE id=?',
                     (state, encode(data).decode() if data is not None else None,
                      fields.get('source_job'), fields.get('archive_job'), fields.get('completed'), generation))


def available_generations(c, policy_id):
    result = []
    for g in c.db.execute("SELECT * FROM backup_generations WHERE policy_id=? AND state='VERIFIED'", (policy_id,)):
        volumes = list(c.db.execute('SELECT m.state FROM generation_volumes v JOIN media m ON m.id=v.media_id '
                                    'WHERE v.generation_id=?', (g['id'],)))
        if volumes and all(v[0] in ('READY', 'IN_USE', 'ARCHIVED') for v in volumes):
            result.append(dict(g))
    return result


def recycle_eligibility(c, generation_id, media_id):
    g = row(c, 'backup_generations', generation_id)
    if g['state'] not in ('WAITING_APPROVAL', 'WAITING_MEDIA', 'WAITING_CAPACITY') or g['archive_job']:
        raise SafetyError('Wiederverwendung nur vor der endgültigen Medienbindung')
    p = require_policy(c, g['policy_id'])
    opts = json.loads(p['options_json'])
    m = row(c, 'media', media_id)
    if (m['class'] != 'rotation' or m['state'] not in ('READY', 'IN_USE', 'ARCHIVED')
            or media_id not in {x['id'] for x in members(c, g['set_id'])}):
        raise SafetyError('Medium gehört nicht zum verfügbaren Ziel-Bandsatz')
    if c.db.execute("SELECT 1 FROM recycle_intents WHERE media_id=? AND state IN ('CONSUMED','WRITING','INTERRUPTED')", (media_id,)).fetchone():
        raise SafetyError('Ungeklärte frühere Wiederverwendung; keine automatische Wiederholung')
    affected = [dict(x) for x in c.db.execute('SELECT g.* FROM backup_generations g JOIN generation_volumes v '
                                             'ON g.id=v.generation_id WHERE v.media_id=?', (media_id,))]
    # Unowned historical archives must never become recyclable by assigning a tape to a set.
    jobs = {x['archive_job'] for x in affected if x['archive_job']}
    allowed_jobs = set(jobs)
    for job in jobs:
        j = c.db.execute('SELECT kind,plan_json FROM jobs WHERE id=?', (job,)).fetchone()
        if j and j['kind'] == 'archive-set':
            allowed_jobs.update(x['job_id'] for x in json.loads(j['plan_json'])['children'])
    archives = list(c.db.execute('SELECT id,job_id,state FROM archives WHERE media_id=?', (media_id,)))
    if any(x['job_id'] not in allowed_jobs or x['state'] != 'VERIFIED' for x in archives):
        raise SafetyError('Vorhandene fremde oder unbestätigte Archive bleiben geschützt')
    for old in affected:
        d = json.loads(old['data_json'])
        if d.get('protected') or (old['completed'] and time.time() < old['completed'] + opts['retain_days'] * 86400):
            raise SafetyError('Generation ist durch Schutzfrist oder manuellen Schutz gesperrt')
        if old['policy_id'] != g['policy_id'] or old['state'] not in ('VERIFIED', 'UNAVAILABLE'):
            raise SafetyError('Nicht abgeschlossene Generation bleibt gesperrt; separate Recovery erforderlich')
    lost = {x['id'] for x in affected}
    survivors = [x for x in available_generations(c, g['policy_id']) if x['id'] not in lost]
    if len(survivors) < opts['keep_during_update'] and archives:
        raise SafetyError('Zu wenige vollständige Bandgenerationen bleiben erhalten')
    # Ordinary plans, restores and unfinished archive writes also retain their media.
    if c.db.execute("SELECT 1 FROM jobs WHERE media_id=? AND state IN "
                    "('RUNNING','PLANNING','PLANNED','STAGED','WAITING_MEDIA','INTERRUPTED','FAILED') LIMIT 1", (media_id,)).fetchone():
        raise SafetyError('Aktiver oder ungeklärter Auftrag reserviert diese Kassette')
    if any(c.db.execute("SELECT 1 FROM jobs WHERE kind='rotation-restore' AND state!='VERIFIED' "
                        "AND json_extract(plan_json,'$.generation_id')=?", (old['id'],)).fetchone() for old in affected):
        raise SafetyError('Satz-Restore reserviert eine betroffene Generation')
    return {'generation_id': generation_id, 'media_id': media_id,
            'header': json.loads(m['header_json']), 'policy': opts,
            'affected': sorted(lost), 'archives': [dict(x) for x in archives]}


def capacity_plan(c, generation_id, draft):
    g = row(c, 'backup_generations', generation_id)
    if g['archive_job']:
        raise SafetyError('Gebundener Plan bleibt unverändert; Erweiterung im laufenden Write noch gesperrt')
    ms = members(c, g['set_id'])
    data = json.loads(g['data_json'])
    usable = [m for m in ms if m['state'] in ('READY', 'IN_USE')
              and json.loads(m['header_json']).get('backend') == data['backend']]
    capacities = [m['capacity'] - 10240 for m in usable]
    sizes = [size + 10240 for size in draft['archive_sizes']]
    data.update(required_bytes=sum(sizes), available_bytes=sum(capacities),
                largest_archive=max(sizes, default=0), media_ids=[], recycle_media=[])
    try:
        assignment = allocate(sizes, capacities)
    except SafetyError:
        data['reason'] = ('Einzelnes TAR passt auf keine Kassette; Einzeldateien werden nicht geteilt'
                          if max(sizes, default=0) > max(capacities, default=0)
                          else 'Zusätzliche Kassette oder kleinere TAR-Zielgröße erforderlich')
        update_generation(c, generation_id, 'WAITING_CAPACITY', data)
        return data
    selected = [usable[i] for i in sorted(set(assignment))]
    data['media_ids'] = [m['id'] for m in selected]
    data['recycle_media'] = [m['id'] for m in selected if c.db.execute('SELECT 1 FROM archives WHERE media_id=?', (m['id'],)).fetchone()]
    state = 'WAITING_APPROVAL' if data['recycle_media'] else 'WAITING_MEDIA'
    data['reason'] = 'Wiederverwendung einzeln prüfen' if data['recycle_media'] else 'Bandsatz kann gebunden werden'
    update_generation(c, generation_id, state, data)
    return data


def reconcile(c):
    for g in list(c.db.execute("SELECT * FROM backup_generations WHERE archive_job IS NOT NULL AND state NOT IN ('VERIFIED','UNAVAILABLE','CANCELLED')")):
        job = c.db.execute('SELECT state FROM jobs WHERE id=?', (g['archive_job'],)).fetchone()
        if not job:
            continue
        state = job[0]
        if state == 'VERIFIED':
            volumes = list(c.db.execute('SELECT m.state FROM generation_volumes v JOIN media m ON m.id=v.media_id WHERE v.generation_id=?', (g['id'],)))
            if volumes and all(x[0] in ('READY', 'IN_USE', 'ARCHIVED') for x in volumes):
                update_generation(c, g['id'], 'VERIFIED', completed=time.time())
        elif state in ('FAILED', 'INTERRUPTED', 'WAITING_MEDIA', 'RUNNING'):
            update_generation(c, g['id'], state)


def listing(c, deleted=False):
    result = []
    for p in c.db.execute('SELECT * FROM backup_policies ORDER BY created'):
        item = dict(p); item['options'] = json.loads(item.pop('options_json'))
        item['deleted'] = bool(item['options'].get('deleted_at'))
        if item['deleted'] != deleted:
            continue
        item['sets'] = []
        for s in c.db.execute('SELECT * FROM tape_sets WHERE policy_id=? ORDER BY created', (p['id'],)):
            value = dict(s); value['members'] = members(c, s['id'])
            for m in value['members']:
                m.pop('header_json', None)
            value['capacity'] = sum(m['capacity'] for m in value['members'] if m['state'] in ('READY', 'IN_USE'))
            item['sets'].append(value)
        item['generations'] = []
        for g in c.db.execute('SELECT * FROM backup_generations WHERE policy_id=? ORDER BY created DESC', (p['id'],)):
            value = dict(g); value['data'] = json.loads(value.pop('data_json'))
            item['generations'].append(value)
        result.append(item)
    return result


def recovery_context(c, source_job):
    """Small portable descriptor repeated inside ordinary verified PAX manifests."""
    if not source_job:
        return None
    g = c.db.execute('SELECT * FROM backup_generations WHERE source_job=?', (source_job,)).fetchone()
    if not g:
        return None
    data = json.loads(g['data_json'])
    return {'format': 'otam-full-generation-v1', 'generation_id': g['id'],
            'policy_id': g['policy_id'], 'set_id': g['set_id'],
            'inventory_sha256': data['inventory_sha256'], 'file_count': data['file_count'],
            'payload_bytes': data['payload_bytes'], 'media_ids': data['media_ids'],
            'recovery': 'Extract all data/ members from all listed media into one NEW directory. '
                        'Collect path, size, sha256 from every OTAM/manifest.json; sort by path; '
                        'verify uniqueness, file_count and payload_bytes. Verify each payload SHA-256. '
                        'The inventory digest uses OTAM canonical JSON (UTF-8, sorted keys, compact separators). '
                        'Borg repository keys and application consistency checks are separate requirements.'}


def attach_recovery(c, source_job, manifests):
    context = recovery_context(c, source_job)
    if context is not None:
        if len(encode(context)) > 4096:
            raise SafetyError('Recovery descriptor exceeds the reserved metadata budget')
        for manifest in manifests:
            manifest['rotation'] = context
    return 10240 if context else 0
