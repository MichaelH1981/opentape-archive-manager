"""Additive backups select only attributable VERIFIED paths, without old payload reads."""
import json
import os
from dataclasses import replace
from unittest.mock import patch
from unittest import TestCase
from tests import test_source_plans
from otam.catalog import Catalog
from otam.archive import inventory
from otam.common import SafetyError
from otam.web import additive, source_plans
from otam.web.config import Resource
from otam.web.worker import execute


class Additive(TestCase):
    setUp = test_source_plans.SourcePlans.setUp
    medium = test_source_plans.SourcePlans.medium
    preview = test_source_plans.SourcePlans.preview
    bind = test_source_plans.SourcePlans.bind
    # Reuse the fixture helpers, rather than the source-plan test suite.
    def archive_initial(self, ids=None):
        if ids is None:
            ids=[execute(self.config,self.control,'create-medium',{'label':'large','capacity':10**7,'media_class':'rotation'})['media_id']]
        bound=self.bind(self.preview(),ids)
        c=Catalog(self.config.catalog)
        try:
            p=json.loads(c.db.execute('select plan_json from jobs where id=?',(bound['job_id'],)).fetchone()[0])
        finally:c.close()
        if 'children' in p:
            for child in p['children']:
                execute(self.config,self.control,'backup-set',{'job_id':bound['job_id'],'plan_hash':bound['sha256'],'media_id':child['media_id'],'confirm':bound['job_id']})
        else:
            execute(self.config,self.control,'backup',{'job_id':bound['job_id'],'plan_hash':bound['sha256'],'confirm':bound['job_id']})
        self.request['backup_mode']='additive'
        return ids,bound

    def draft(self, result):
        c=Catalog(self.config.catalog)
        try:return source_plans.load(c,result['job_id'])[1]
        finally:c.close()

    def test_additive_append_hashes_only_new_file_and_restores_it(self):
        ids,first=self.archive_initial()
        self.root.joinpath('source/new').write_bytes(b'new data')
        with patch('otam.archive.digest',side_effect=AssertionError('preview must not hash')):
            preview=self.preview()
        draft=self.draft(preview)
        self.assertEqual(draft['additive']['new_files'],1)
        self.assertEqual(draft['additive']['unchanged_files'],2)
        self.assertEqual([e['path'] for e in draft['source_entries']],['new'])
        known_inodes={self.root.joinpath('source',name).stat().st_ino for name in ('one','two')}
        new_inode=self.root.joinpath('source/new').stat().st_ino
        new_reads=[];original=os.fdopen
        class Tracked:
            def __init__(self,stream,inode):self.stream=stream;self.inode=inode
            def __enter__(self):return self
            def __exit__(self,*args):return self.stream.__exit__(*args)
            def __getattr__(self,name):return getattr(self.stream,name)
            def read(inner,*args):
                data=inner.stream.read(*args)
                if data:
                    self.assertNotIn(inner.inode,known_inodes)
                    new_reads.append(len(data))
                return data
        def opened(fd,*args,**kwargs):
            inode=os.fstat(fd).st_ino;stream=original(fd,*args,**kwargs)
            return Tracked(stream,inode) if inode in known_inodes|{new_inode} else stream
        with patch('otam.archive.os.fdopen',side_effect=opened):
            bound=self.bind(preview,ids)
        self.assertEqual(sum(new_reads),len(b'new data'))
        execute(self.config,self.control,'backup',{'job_id':bound['job_id'],'plan_hash':bound['sha256'],'confirm':bound['job_id']})
        c=Catalog(self.config.catalog)
        try:
            rows=list(c.db.execute('select * from archives where job_id=?',(bound['job_id'],)))
            self.assertTrue(all(r['state']=='VERIFIED' for r in rows))
            archive=rows[0]['id']
            self.assertEqual(c.db.execute('select count(*) from files').fetchone()[0],3)
        finally:c.close()
        restored=execute(self.config,self.control,'restore',{'media_id':ids[0],'archive_id':archive,'paths':['new'],'target_name':'additive-restore'})
        self.assertEqual(restored['state'],'VERIFIED')
        self.assertEqual((self.config.restore_root/'additive-restore/new').read_bytes(),b'new data')
        self.assertEqual(self.preview()['state'],'NO_CHANGES')

    def test_no_changes_needs_no_media_and_does_not_hash(self):
        self.archive_initial()
        with patch('otam.archive.digest',side_effect=AssertionError('old contents must not hash')):
            result=self.preview()
        self.assertEqual(result['state'],'NO_CHANGES')
        self.assertEqual(result['file_count'],0)
        self.assertEqual(self.draft(result)['archive_sizes'],[])

    def test_changed_paths_are_reported_and_explicitly_included(self):
        ids,_=self.archive_initial()
        self.root.joinpath('source/one').write_bytes(b'changed')
        result=self.preview()
        self.assertEqual(result['state'],'NO_CHANGES')
        self.assertEqual(result['changed_paths'],['one'])
        self.request['changed_policy']='include'
        result=self.preview();draft=self.draft(result)
        self.assertEqual([e['path'] for e in draft['source_entries']],['one'])
        self.assertEqual(draft['additive']['changed_files'],1)
        self.bind(result,ids)

    def test_unverified_and_suspect_archives_do_not_skip_files(self):
        self.archive_initial()
        c=Catalog(self.config.catalog)
        with c.db:c.db.execute("update archives set state='INCOMPLETE'")
        c.close()
        self.assertEqual(self.preview()['file_count'],2)
        c=Catalog(self.config.catalog)
        with c.db:
            c.db.execute("update archives set state='VERIFIED'")
            c.db.execute("update media set state='SUSPECT'")
        c.close()
        self.assertEqual(self.preview()['file_count'],2)

    def test_source_identity_and_backend_isolation(self):
        self.archive_initial()
        c=Catalog(self.config.catalog)
        try:
            self.assertEqual(additive.baseline(c,'src',self.root/'source','physical'),{})
            self.assertEqual(additive.baseline(c,'other',self.root/'source','simulator'),{})
            self.assertEqual(additive.baseline(c,'src',self.root/'other','simulator'),{})
        finally:c.close()
        self.config=replace(self.config,sources=(Resource('other','same path',self.root/'source'),))
        self.request['source_id']='other'
        self.assertEqual(self.preview()['file_count'],2)

    def test_changed_catalog_or_source_refuses_binding_before_hash(self):
        ids,_=self.archive_initial()
        self.root.joinpath('source/new').write_bytes(b'new')
        result=self.preview()
        c=Catalog(self.config.catalog)
        with c.db:c.db.execute("update archives set state='INCOMPLETE'")
        c.close()
        with patch('otam.archive.digest',side_effect=AssertionError('no content reads')):
            with self.assertRaisesRegex(SafetyError,'Katalogbasis'):self.bind(result,ids)

    def test_deleted_known_file_stays_archived_and_selection_exclusions_work(self):
        self.archive_initial()
        self.root.joinpath('source/one').unlink()
        self.root.joinpath('source/new').write_bytes(b'new')
        self.request['excluded_paths']=['new']
        self.assertEqual(self.preview()['state'],'NO_CHANGES')
        c=Catalog(self.config.catalog)
        try:self.assertEqual(c.db.execute("select count(*) from files where path='one'").fetchone()[0],1)
        finally:c.close()

    def test_multi_medium_baseline(self):
        self.archive_initial([self.medium('one'),self.medium('two')])
        self.assertEqual(self.preview()['state'],'NO_CHANGES')

    def test_invalid_modes_rejected(self):
        for field,value in [('backup_mode','guess'),('changed_policy','overwrite')]:
            with self.assertRaises(SafetyError):execute(self.config,self.control,'plan-source',{**self.request,field:value})

    def test_empty_source_after_deletions_requires_no_media(self):
        self.archive_initial()
        for path in self.root.joinpath('source').iterdir():path.unlink()
        self.assertEqual(self.preview()['state'],'NO_CHANGES')

    def test_metadata_match_does_not_claim_content_equality(self):
        self.archive_initial()
        path=self.root/'source/one';before=path.stat()
        path.write_bytes(b'x'*before.st_size)
        os.utime(path,ns=(before.st_atime_ns,before.st_mtime_ns))
        result=self.preview()
        self.assertEqual(result['state'],'NO_CHANGES')
        self.assertIn('not hashed',result['comparison'])

    def test_tampered_source_attribution_fails_closed(self):
        self.archive_initial()
        c=Catalog(self.config.catalog)
        row=c.db.execute("select id,plan_json from jobs where kind='source-plan' and state='BOUND'").fetchone()
        value=json.loads(row['plan_json']);value['target']=12345
        with c.db:c.db.execute('update jobs set plan_json=? where id=?',(json.dumps(value),row['id']))
        c.close()
        with self.assertRaisesRegex(SafetyError,'Quellenzuordnung'):self.preview()

    def test_expanded_internal_selection_above_request_limit(self):
        root=self.root/'source/many';root.mkdir()
        for i in range(10001):root.joinpath(str(i)).touch()
        expected=inventory(root,metadata_only=True)
        paths=[entry['path'] for entry in expected]
        with self.assertRaisesRegex(SafetyError,'selection'):inventory(root,paths,metadata_only=True)
        self.assertEqual(inventory(root,paths,metadata_only=True,expected=expected),expected)

    def test_api_preview_omits_private_full_inventory(self):
        self.archive_initial()
        self.root.joinpath('source/new').write_bytes(b'new')
        result=self.preview()
        from otam.web.query import CatalogView
        shown=CatalogView(self.config,self.control).job(result['job_id'])['plan']
        self.assertEqual(shown['additive']['new_files'],1)
        for field in ('source_entries','inventory_entries','capture_paths'):self.assertNotIn(field,shown)

    def test_http_queue_accepts_additive_options_and_preserves_csrf(self):
        from fastapi.testclient import TestClient
        from otam.web.app import create_app
        from otam.web.config import password_hash
        from otam.web.worker import run_once
        password='synthetic-additive-test'
        config=replace(self.config,password=password_hash(password),allowed_hosts=('testserver',))
        with TestClient(create_app(config)) as client:
            login=client.post('/api/v1/login',json={'username':'admin','password':password}).json()
            request={'kind':'plan-source','payload':{**self.request,'backup_mode':'additive','changed_policy':'include'}}
            self.assertEqual(client.post('/api/v1/commands',json=request).status_code,403)
            response=client.post('/api/v1/commands',json=request,headers={'X-CSRF-Token':login['csrf'],'Idempotency-Key':'additive-preview'})
            self.assertEqual(response.status_code,202,response.text)
            self.assertTrue(run_once(config,self.control))
            c=Catalog(config.catalog)
            try:
                job=c.db.execute("select id from jobs where kind='source-plan'").fetchone()['id']
            finally:c.close()
            shown=client.get('/api/v1/jobs/'+job).json()['plan']
            self.assertEqual(shown['backup_mode'],'additive')
            self.assertEqual(shown['additive']['new_files'],2)
            self.assertEqual(shown['additive']['changed_policy'],'include')
            self.assertNotIn('inventory_entries',shown)
