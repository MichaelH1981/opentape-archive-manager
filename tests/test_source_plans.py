"""Source-first planning never hashes payloads before sufficient media exist."""
import hashlib
import json
import os
import tempfile
import uuid
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch
from otam.archive import digest
from otam.catalog import Catalog
from otam.common import SafetyError
from otam.web.config import WebConfig, Resource
from otam.web.control import Control
from otam.web.worker import execute, validate_command
from otam.web import source_plans


class SourcePlans(TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory(dir=os.environ.get('OTAM_TEST_TMPDIR'));self.addCleanup(temp.cleanup)
        self.root=Path(temp.name).resolve()
        for p in ('source','staging','restore'):self.root.joinpath(p).mkdir()
        self.config=WebConfig(str(uuid.uuid4()),'test','archive',self.root/'state',self.root/'catalog.sqlite',self.root/'staging',self.root/'media',self.root/'restore','pbkdf2_sha256$600000$salt$hash',sources=(Resource('src','source',self.root/'source'),))
        self.control=Control(self.config.state)
        self.storage=patch('otam.web.resources.require_local',return_value={'free':10**9,'mount':str(self.root),'source':'/dev/test','device':'1:2','type':'ext4'})
        self.storage.start();self.addCleanup(self.storage.stop)
        for n in ('one','two'):self.root.joinpath('source',n).write_bytes((n*10000).encode())
        self.request={'source_id':'src','target':60000,'verify_mode':'media'}

    def medium(self,label):
        return execute(self.config,self.control,'create-medium',{'label':label,'capacity':110000,'media_class':'rotation'})['media_id']

    def preview(self):return execute(self.config,self.control,'plan-source',self.request)
    def bind(self,draft,ids):return execute(self.config,self.control,'bind-plan',{'job_id':draft['job_id'],'source_plan_hash':draft['sha256'],'media_ids':ids})

    def test_metadata_only_preview_has_no_media_or_content_hash(self):
        with patch('otam.archive.digest',side_effect=AssertionError('payload read forbidden')):
            draft=self.preview()
        self.assertEqual(draft['state'],'WAITING_MEDIA')
        c=Catalog(self.config.catalog)
        try:
            _,p=source_plans.load(c,draft['job_id']);self.assertFalse(p['hashes_calculated'])
            self.assertNotIn('media_id',p);self.assertTrue(all('sha256' not in e for e in p['source_entries']))
            self.assertEqual(c.db.execute('select count(*) from archives').fetchone()[0],0)
        finally:c.close()
        with self.assertRaises(SafetyError):validate_command(self.config,self.control,'stage',{'job_id':draft['job_id']})

    def test_shortage_preserves_draft_and_second_medium_binds_without_reinventory_hash_waste(self):
        one=self.medium('one');two=self.medium('two');draft=self.preview()
        with patch('otam.archive.digest',side_effect=AssertionError('insufficient media must not hash')):
            short=self.bind(draft,[one])
        self.assertEqual(short['state'],'WAITING_MEDIA')
        with patch('otam.archive.digest',wraps=digest) as hashed:
            bound=self.bind(draft,[one,two])
            self.assertEqual(hashed.call_count,2)
        self.assertEqual(bound['state'],'PLANNED')
        c=Catalog(self.config.catalog)
        try:
            state,p=source_plans.load(c,draft['job_id']);self.assertEqual(state,'BOUND')
            children=json.loads(c.db.execute('select plan_json from jobs where id=?',(bound['job_id'],)).fetchone()[0])['children']
            self.assertEqual(len(children),2)
            for child in children:self.assertIsNotNone(self.control.get('job_storage:'+child['job_id']))
        finally:c.close()
        with self.assertRaises(SafetyError):self.bind(draft,[one,two])

    def test_native_capacity_above_old_percentage_binds_and_stages(self):
        draft=self.preview()
        capacity=draft['required_estimate']+10240+1
        medium=execute(self.config,self.control,'create-medium',{'label':'near-native','capacity':capacity,'media_class':'rotation'})['media_id']
        self.assertGreater(draft['required_estimate']+10240,capacity*95//100)
        bound=self.bind(draft,[medium])
        self.assertEqual(bound['state'],'PLANNED')
        execute(self.config,self.control,'stage',{'job_id':bound['job_id']})

    def test_changed_source_and_tampered_draft_refuse_before_hashing(self):
        one=self.medium('one');two=self.medium('two');draft=self.preview()
        p=self.root/'source/one';before=p.stat();p.write_bytes(b'x'*before.st_size);os.utime(p,ns=(before.st_atime_ns,before.st_mtime_ns))
        with patch('otam.archive.digest',side_effect=AssertionError('changed source must not hash')):
            with self.assertRaisesRegex(SafetyError,'verändert'):self.bind(draft,[one,two])
        c=Catalog(self.config.catalog)
        try:
            _,value=source_plans.load(c,draft['job_id']);value['required_estimate']=1
            with c.db:c.db.execute('update jobs set plan_json=? where id=?',(json.dumps(value),draft['job_id']))
        finally:c.close()
        with self.assertRaises(SafetyError):self.bind(draft,[one,two])

    def test_single_large_file_cannot_be_split_across_media(self):
        self.root.joinpath('source/huge').write_bytes(b'a'*150000)
        ids=[self.medium('one'),self.medium('two'),self.medium('three'),self.medium('four')];draft=self.preview()
        with patch('otam.archive.digest',side_effect=AssertionError('oversized TAR must not hash')):
            result=self.bind(draft,ids)
        self.assertEqual(result['state'],'WAITING_MEDIA')
        self.assertGreater(result['available'],result['required_estimate'])
        self.assertGreater(result['largest_archive'],100000)

    def test_preview_rejects_targets_paths_and_symlinks(self):
        with self.assertRaises(SafetyError):execute(self.config,self.control,'plan-source',{**self.request,'media_id':str(uuid.uuid4())})
        with self.assertRaises(SafetyError):execute(self.config,self.control,'plan-source',{**self.request,'selected_paths':['../escape']})
        self.root.joinpath('source/link').symlink_to(self.root/'source/one')
        with self.assertRaises((SafetyError,OSError)):self.preview()

    def test_legacy_single_media_plan_checks_capacity_before_hashing(self):
        one=self.medium('one')
        with patch('otam.archive.digest',side_effect=AssertionError('legacy plan must preflight capacity')):
            with self.assertRaisesRegex(SafetyError,'capacity'):
                execute(self.config,self.control,'plan',{**self.request,'media_id':one})

    def test_explicit_exclusion_is_sealed_and_survives_binding_and_staging(self):
        base=self.root/'source/LP Archiv';base.mkdir();(base/'video.bin').write_bytes(b'v'*30000)
        cache=base/'.@__thumb';cache.mkdir();(cache/'external').symlink_to('/outside-the-source/thumbnail')
        self.request.update(selected_paths=['LP Archiv'],excluded_paths=['LP Archiv/.@__thumb'])
        with patch('otam.archive.digest',side_effect=AssertionError('metadata only')):draft=self.preview()
        self.assertEqual(draft['file_count'],1)
        bound=self.bind(draft,[self.medium('one')])
        c=Catalog(self.config.catalog)
        try:
            value=json.loads(c.db.execute('select plan_json from jobs where id=?',(bound['job_id'],)).fetchone()[0])
            self.assertEqual(value['excluded_paths'],['LP Archiv/.@__thumb'])
            self.assertEqual([e['path'] for a in value['archives'] for e in a['files']],['LP Archiv/video.bin'])
        finally:c.close()
        execute(self.config,self.control,'stage',{'job_id':bound['job_id']})

    def test_exclusion_cannot_escape_source_or_change_during_binding(self):
        with self.assertRaises(SafetyError):execute(self.config,self.control,'plan-source',{**self.request,'excluded_paths':['../outside']})
        draft=self.preview()
        with self.assertRaises(SafetyError):execute(self.config,self.control,'bind-plan',{'job_id':draft['job_id'],'source_plan_hash':draft['sha256'],'media_ids':[self.medium('one')],'excluded_paths':['one']})

    def test_grouping_exact_boundaries_and_linear_encoding_work(self):
        from otam.archive import group_entries, estimate, estimate_entries
        from otam.common import encode
        entries=estimate_entries([{'path':f'folder/ä-{i}.txt','size':511+i%3,'mtime_ns':123456789,'type':'.txt'} for i in range(2000)])
        target=estimate(entries[:2])
        with patch('otam.archive.encode',wraps=encode) as serialized:
            groups=group_entries(entries,target)
        self.assertLessEqual(serialized.call_count,len(entries)*2)
        self.assertEqual(groups[0],entries[:2])
        self.assertEqual([e for group in groups for e in group],entries)
        self.assertTrue(all(len(group)==1 or estimate(group)<=target for group in groups))
        self.assertEqual(group_entries(entries[:2],target-1),[[entries[0]],[entries[1]]])
