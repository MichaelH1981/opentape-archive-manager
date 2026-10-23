import json
import os
import shutil
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch
from otam.archive import inventory, create_archive, plan_archives, estimate_entries, verify_archive
from otam.common import SafetyError, sha256
from otam.staging import StagingStore
from otam.web.progress import job_progress
from tests import test_workflows as fixtures


class CombinedCapture(TestCase):
    setUp=fixtures.Workflows.setUp
    tearDown=fixtures.Workflows.tearDown

    def test_one_source_payload_pass_ready_tar_and_backup_without_source(self):
        expected={p.relative_to(self.source).as_posix():sha256(p) for p in self.source.rglob('*') if p.is_file()}
        identities={(p.stat().st_dev,p.stat().st_ino) for p in self.source.rglob('*') if p.is_file()}
        bytes_read=[];original=os.fdopen
        class Tracked:
            def __init__(self,f):self.f=f
            def __enter__(self):return self
            def __exit__(self,*args):return self.f.__exit__(*args)
            def __getattr__(self,key):return getattr(self.f,key)
            def read(self,*args):
                data=self.f.read(*args);bytes_read.append(len(data));return data
        def opened(fd,*args,**kwargs):
            info=os.fstat(fd);f=original(fd,*args,**kwargs)
            return Tracked(f) if (info.st_dev,info.st_ino) in identities else f
        with patch('otam.archive.os.fdopen',side_effect=opened):
            plan=self.service.plan(self.source,self.media,verify_mode='media',staging=self.spool)
        self.assertEqual(sum(bytes_read),plan['payload_bytes'])
        for m in plan['archives']:
            for e in m['files']:self.assertEqual(e['sha256'],expected[e['path']])
            row=self.catalog.db.execute('select * from staged_archives where archive_id=?',(m['archive_id'],)).fetchone()
            self.assertEqual(verify_archive(Path(row['path']),m),m)
            self.assertEqual(Path(row['path']).stat().st_mode & 0o222,0)
        shutil.rmtree(self.source)
        with patch.object(StagingStore,'_inspect',side_effect=AssertionError('no second full pass for sealed combined READY')):
            result=self.service.backup(plan['job_id'],plan['job_id'],self.spool)
        self.assertEqual(result['state'],'VERIFIED')
        target=self.base/'restore-combined'
        self.service.restore(self.media,target)
        for name,checksum in expected.items():self.assertEqual(sha256(target/name),checksum)

    def test_change_while_copying_keeps_private_partial_and_no_ready_plan(self):
        entries=inventory(self.source,metadata_only=True)
        m=plan_archives(estimate_entries(entries),self.media,75000000000)[0]
        changed=False
        def mutate(_):
            nonlocal changed
            if not changed:
                changed=True
                p=self.source/next(e['path'] for e in m['files'] if e['size']);p.write_bytes(b'x'*p.stat().st_size)
        with self.assertRaisesRegex(SafetyError,'changed'):
            create_archive(self.base/'private.partial',self.source,m,progress=mutate,single_pass=True,expected=entries)
        self.assertEqual(self.catalog.db.execute('select count(*) from archives').fetchone()[0],0)

    def test_space_failure_before_any_content_hash_or_ready_publication(self):
        with patch.object(StagingStore,'require_space',side_effect=SafetyError('Insufficient local staging space')):
            with self.assertRaisesRegex(SafetyError,'Insufficient'):
                self.service.plan(self.source,self.media,staging=self.spool)
        self.assertEqual(self.catalog.db.execute("select count(*) from staged_archives where phase='READY'").fetchone()[0],0)
        self.assertEqual(self.catalog.db.execute("select count(*) from jobs where state='PLANNED'").fetchone()[0],0)

    def test_finished_metadata_progress_and_unknown_total(self):
        events=[];inventory(self.source,metadata_only=True,progress=events.append)
        self.assertTrue(events[-1]['complete']);self.assertEqual(events[-1]['files'],3)
        self.assertIsNone(events[-1]['total_bytes'])
        job=self.catalog.job('source-plan',None,'PLANNING')
        self.catalog.event(job,'planning_progress',**events[-1])
        progress=job_progress(self.catalog.db,job,None,'PLANNING')
        self.assertIsNone(progress['percent']);self.assertEqual(progress['files'],3)
        self.assertIsNone(job_progress(self.catalog.db,job,None,'BOUND'))

    def test_legacy_or_explicit_validation_still_reads_in_a_new_process(self):
        plan=self.service.plan(self.source,self.media,staging=self.spool)
        m=plan['archives'][0];fresh=StagingStore(self.catalog,self.spool)
        with patch.object(fresh,'_inspect',wraps=fresh._inspect) as inspected:
            fresh.prepare(plan['job_id'],self.source,m)
            fresh.validate_for_write(plan['job_id'],m)
            self.assertEqual(inspected.call_count,1)
        again=StagingStore(self.catalog,self.spool)
        with patch.object(again,'_inspect',wraps=again._inspect) as inspected:
            again.validate_for_write(plan['job_id'],m)
            self.assertEqual(inspected.call_count,1)

    def test_failed_inspection_never_publishes_final_plan_or_ready_tar(self):
        with patch.object(StagingStore,'_inspect',side_effect=SafetyError('injected validation failure')):
            with self.assertRaisesRegex(SafetyError,'injected'):
                self.service.plan(self.source,self.media,staging=self.spool)
        row=self.catalog.db.execute("select state,plan_json from jobs where kind='archive' order by created desc limit 1").fetchone()
        self.assertEqual(row['state'],'FAILED');self.assertIsNone(row['plan_json'])
        self.assertFalse(list(self.spool.rglob('ready.tar')))
        self.assertTrue(list(self.spool.rglob('*.partial')))

    def test_staging_inside_source_is_refused(self):
        with self.assertRaisesRegex(SafetyError,'separate'):
            self.service.plan(self.source,self.media,staging=self.source/'forbidden')
        self.assertFalse((self.source/'forbidden').exists())
