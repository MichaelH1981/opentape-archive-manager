#!/usr/bin/env python3
"""Small destructive 0.9 acceptance on ONE explicitly disposable EMPTY rotation tape.

Requires installed schema 3, idle/stopped main worker and a supervising unit with
OnSuccess/OnFailure worker restart. Uses LIVE catalog and device journals, but a
private test Control. Never enables a live configuration gate or initializes an
unknown cartridge. Both complete generations and the final restore are tiny.
"""
import argparse
from dataclasses import replace
import json
import os
from pathlib import Path
import shutil
import sqlite3
import time
from otam.catalog import Catalog
from otam.common import SafetyError, encode, sync_dir
from otam import rotation as model
from otam.physical import discover_drives
from otam.web.config import WebConfig, Resource
from otam.web.control import Control
from otam.web import physical_archive, resources, rotation
from otam.web.worker import execute, worker_lock


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--config',type=Path,required=True)
    p.add_argument('--report-root',type=Path,required=True)
    p.add_argument('--media-id',required=True)
    p.add_argument('--drive-serial',required=True)
    p.add_argument('--medium-serial',required=True)
    p.add_argument('--confirm',required=True)
    a=p.parse_args()
    if a.confirm != f'ROTATION_TEST {a.drive_serial} {a.medium_serial}':
        raise SafetyError('Exact drive/MAM destructive confirmation required')
    live=WebConfig.load(a.config)
    with sqlite3.connect(live.catalog.as_uri()+'?mode=ro',uri=True) as db:
        if db.execute('PRAGMA user_version').fetchone()[0] != 3:
            raise SafetyError('Install tested 0.9 first; this harness never migrates the live catalog')
    root=a.report_root.resolve()
    for protected in (live.state,live.staging,live.media_root,live.restore_root,live.catalog.parent):
        if root==protected or protected.is_relative_to(root):
            raise SafetyError('Report root contains live data')
    if root.is_relative_to(live.staging) or root.is_relative_to(live.state):
        raise SafetyError('Report root must be separate from live staging/state')
    root.mkdir(mode=0o700,parents=True,exist_ok=False)
    report={'state':'PREPARING','started':time.time(),'drive_serial':a.drive_serial,'medium_serial':a.medium_serial,'steps':[]}
    def save():
        temporary=root/'report.tmp'
        with temporary.open('wb') as f:f.write(encode(report));f.flush();os.fsync(f.fileno())
        os.replace(temporary,root/'report.json');sync_dir(root)
    save()
    control=Control(root/'control');main_control=Control(live.state)
    catalog=Catalog(live.catalog)
    try:
        with worker_lock(live):
            def idle():
                with main_control.connect() as db:
                    if db.execute("SELECT 1 FROM commands WHERE state IN ('QUEUED','RUNNING')").fetchone():
                        raise SafetyError('Main queue must be empty')
            idle()
            media=model.row(catalog,'media',a.media_id)
            header=json.loads(media['header_json'])
            if (media['class']!='rotation' or media['state']!='READY' or header.get('backend')!='physical'
                    or header.get('medium_serial')!=a.medium_serial
                    or catalog.db.execute('SELECT 1 FROM archives WHERE media_id=?',(a.media_id,)).fetchone()
                    or catalog.db.execute('SELECT 1 FROM tape_set_members WHERE media_id=? AND removed IS NULL',(a.media_id,)).fetchone()):
                raise SafetyError('Only an empty registered unassigned READY rotation tape is eligible')
            bindings=physical_archive.bindings(main_control)
            binding=bindings.get(a.media_id)
            if not binding or binding.get('drive_serial')!=a.drive_serial or binding.get('medium_serial')!=a.medium_serial:
                raise SafetyError('Live binding does not match authorization')
            drives=discover_drives()
            if len([d for d in drives if d.get('serial')==a.drive_serial and d.get('medium_serial')==a.medium_serial])!=1:
                raise SafetyError('Authorized tape is not loaded')
            prefix=[tuple(r) for r in catalog.db.execute('SELECT id,media_id,state,sha256 FROM archives ORDER BY id')]
            source=root/'source';source.mkdir();(source/'fixture.bin').write_bytes(b'OTAM-090-rotation\n'*2048)
            cfg=replace(live,sources=(Resource('rotation-acceptance','Rotation acceptance',source),),
                        restore_root=root/'restore',physical_archiving=True,physical_initialization=True,physical_rotation=True)
            cfg.validate()
            control.set('operation_mode','physical');control.set('physical_media_bindings',bindings)
            control.set('hardware_inventory',{'time':time.time(),'drives':drives})
            sid=resources.default_staging_id(live,main_control)
            selected=main_control.get('transfer_settings:'+sid)
            if not selected:raise SafetyError('Previously qualified saved transfer settings required')
            control.set('transfer_settings:default-staging',selected)
            policy=model.policy(catalog,dict(name='Abnahme OTAM 0.9 (synthetisch)',source_id='rotation-acceptance',
                staging_id='default-staging',set_count=1,keep_during_update=0,retain_days=0,target=75000000000,excluded_paths=[]))['id']
            set_id=catalog.db.execute('SELECT id FROM tape_sets WHERE policy_id=?',(policy,)).fetchone()[0]
            model.add_member(catalog,set_id,a.media_id,'physical')
            medium=a.media_id
            for iteration in (1,2):
                idle();report.update(state='RUNNING',phase=f'GENERATION_{iteration}_PREPARE');save()
                result=execute(cfg,control,'plan-rotation',dict(policy_id=policy,set_id=set_id,consistent_source=True))
                generation=result['generation_id']
                if iteration==2:
                    grant=rotation.review(cfg,control,dict(generation_id=generation,media_id=medium))
                    report.update(phase='RECYCLE',review=grant);save();idle()
                    recycled=execute(cfg,control,'recycle-rotation',dict(approval_id=grant['id'],confirmation=grant['confirmation'],destructive_confirmed=True))
                    medium=recycled['media_id'];report['recycled']=recycled;save()
                bound=execute(cfg,control,'bind-rotation',dict(generation_id=generation))
                if bound['state']!='PLANNED':raise SafetyError('Small generation did not bind')
                report.update(phase=f'GENERATION_{iteration}_BACKUP');save();idle()
                execute(cfg,control,'backup',dict(job_id=bound['job_id'],confirm=bound['job_id'],plan_hash=bound['sha256']))
                model.reconcile(catalog)
                if model.row(catalog,'backup_generations',generation)['state']!='VERIFIED':raise SafetyError('Generation not verified')
                report['steps'].append(dict(generation_id=generation,media_id=medium,job_id=bound['job_id']));save()
            restored=execute(cfg,control,'restore-rotation',dict(generation_id=generation,target_name='repository'))
            if restored['state']!='VERIFIED' or (root/'restore/repository/fixture.bin').read_bytes()!=(source/'fixture.bin').read_bytes():
                raise SafetyError('Final physical restore mismatch')
            after=[tuple(r) for r in catalog.db.execute('SELECT id,media_id,state,sha256 FROM archives WHERE media_id NOT IN (?,?) ORDER BY id',(a.media_id,medium))]
            if after!=prefix:raise SafetyError('Unrelated archive prefix changed')
            # Publish the proven NEW identity; never modify unrelated live bindings.
            saved=physical_archive.bindings(main_control)
            saved[medium]=physical_archive.bindings(control)[medium]
            main_control.set('physical_media_bindings',saved)
            main_control.sync_event('config','UPDATED',None,'OTAM 0.9 rotation acceptance completed')
            report.update(state='VERIFIED',finished=time.time(),phase='COMPLETE',restore=restored,
                          archive_prefix_unchanged=True,live_binding_imported=True)
            save()
    except BaseException as error:
        report.update(state='FAILED',error=str(error),finished=time.time());save();raise
    finally:catalog.close()

if __name__=='__main__':main()
