from pathlib import Path
from unittest import TestCase
from unittest.mock import patch
import os
from otam.staging import StagingStore
from otam.common import SafetyError
from tests import test_workflows as fixtures


class SinglePassValidation(TestCase):
    setUp=fixtures.Workflows.setUp
    tearDown=fixtures.Workflows.tearDown

    def test_new_archive_has_one_independent_local_pass(self):
        plan=self.service.plan(self.source,self.media)
        calls=[];original=StagingStore._inspect
        def inspect(store,path,manifest,checksum,job):
            calls.append((manifest['archive_id'],path.stat().st_size))
            return original(store,path,manifest,checksum,job)
        with patch.object(StagingStore,'_inspect',new=inspect):
            result=self.service.backup(plan['job_id'],plan['job_id'],self.spool)
        self.assertEqual(result['state'],'VERIFIED')
        self.assertEqual(len(calls),len(plan['archives']))
        self.assertEqual(sum(size for _,size in calls),sum(r[0] for r in self.catalog.db.execute('select bytes from archives')))

    def test_media_batch_has_one_pass_and_readback_progress(self):
        plan=self.service.plan(self.source,self.media,target=30000,verify_mode='media')
        calls=[];original=StagingStore._inspect
        def inspect(store,path,manifest,checksum,job):
            calls.append(manifest['archive_id'])
            return original(store,path,manifest,checksum,job)
        with patch.object(StagingStore,'_inspect',new=inspect):
            result=self.service.backup(plan['job_id'],plan['job_id'],self.spool)
        self.assertEqual(result['state'],'VERIFIED')
        self.assertEqual(len(calls),len(plan['archives']))
        import json
        events=[json.loads(r[0]) for r in self.catalog.db.execute("select details_json from events where job_id=? and event='io_progress'",(plan['job_id'],))]
        read=[e for e in events if e['phase']=='TAPE_READBACK']
        self.assertEqual({e['archive'] for e in read},{m['archive_id'] for m in plan['archives']})
        self.assertTrue(all(e['bytes']==e['total_bytes'] for e in read))

    def test_local_change_after_readback_is_not_published_as_success(self):
        plan=self.service.plan(self.source,self.media)
        original=StagingStore.assert_ready_identity
        def tamper(store,job,manifest):
            p=Path(store.row(job,manifest['archive_id'])['path'])
            p.chmod(0o600)
            with p.open('r+b') as f:f.seek(512);f.write(b'corrupt')
            p.chmod(0o400)
            return original(store,job,manifest)
        with patch.object(StagingStore,'assert_ready_identity',new=tamper):
            with self.assertRaisesRegex(SafetyError,'changed'):
                self.service.backup(plan['job_id'],plan['job_id'],self.spool)
        self.assertEqual(self.catalog.db.execute("select count(*) from archives where state='VERIFIED'").fetchone()[0],0)

    def test_batch_validates_every_tar_before_first_write(self):
        plan=self.service.plan(self.source,self.media,target=1000,verify_mode='media')
        validated=[];events=[]
        original=StagingStore._inspect;append=self.tape.append
        def validate(store,path,manifest,checksum,job):
            result=original(store,path,manifest,checksum,job)
            validated.append(manifest['archive_id']);events.append('validation')
            return result
        def write(path,media):
            self.assertEqual(set(validated),{m['archive_id'] for m in plan['archives']})
            events.append('write')
            return append(path,media)
        with patch.object(StagingStore,'_inspect',new=validate),patch.object(self.tape,'append',side_effect=write):
            self.assertEqual(self.service.backup(plan['job_id'],plan['job_id'],self.spool)['state'],'VERIFIED')
        self.assertNotIn('validation',events[events.index('write'):])

    def test_batch_late_prevalidation_failure_never_opens_writer(self):
        plan=self.service.plan(self.source,self.media,target=1000,verify_mode='media')
        original=StagingStore._inspect;last=plan['archives'][-1]['archive_id']
        def validate(store,path,manifest,checksum,job):
            if manifest['archive_id']==last:raise SafetyError('last TAR corrupt')
            return original(store,path,manifest,checksum,job)
        with patch.object(StagingStore,'_inspect',new=validate),patch.object(self.tape,'append') as append:
            with self.assertRaisesRegex(SafetyError,'last TAR corrupt'):
                self.service.backup(plan['job_id'],plan['job_id'],self.spool)
            append.assert_not_called()

    def test_batch_change_after_prevalidation_blocks_next_payload(self):
        plan=self.service.plan(self.source,self.media,target=1000,verify_mode='media')
        self.assertGreater(len(plan['archives']),1)
        original=self.tape.append;calls=[]
        def append(path,media):
            result=original(path,media);calls.append(result)
            if len(calls)==1:
                row=self.catalog.db.execute('select path from staged_archives where archive_id=?',
                                           (plan['archives'][1]['archive_id'],)).fetchone()
                p=Path(row[0]);p.chmod(0o600);p.write_bytes(b'corrupt');p.chmod(0o400)
            return result
        with patch.object(self.tape,'append',side_effect=append):
            with self.assertRaisesRegex(SafetyError,'changed'):
                self.service.backup(plan['job_id'],plan['job_id'],self.spool)
        self.assertEqual(calls,[1,2])
        self.assertEqual(self.catalog.db.execute("select count(*) from archives where state='VERIFIED'").fetchone()[0],0)
