"""One payload allocation, late media binding, and fail-closed adoption."""
import json
import os
import shutil
import tarfile
from unittest import TestCase
from unittest.mock import patch
from tests import test_source_plans as fixtures
from otam import source_capture, packed_capture
from otam.catalog import Catalog
from otam.common import SafetyError, encode
from otam.staging import StagingStore
from otam.web import source_plans
from otam.web.worker import execute


class PackedCapture(TestCase):
    setUp = fixtures.SourcePlans.setUp
    preview = fixtures.SourcePlans.preview
    bind = fixtures.SourcePlans.bind
    medium = fixtures.SourcePlans.medium

    def capture(self, draft):
        return execute(self.config,self.control,'stage-source',dict(job_id=draft['job_id'],source_plan_hash=draft['sha256']))

    def draft(self, job):
        c=Catalog(self.config.catalog)
        try:return source_plans.load(c,job)[1]
        finally:c.close()

    def test_single_payload_pass_and_same_inodes_after_late_binding_with_only_metadata_space(self):
        for name in ('one','two'):(self.root/'source'/name).write_bytes(b'a'*(2*1024**2))
        self.request['target']=3*1024**2
        draft=self.preview();required=draft['required_estimate']
        identities={(p.stat().st_dev,p.stat().st_ino) for p in (self.root/'source').iterdir()}
        counts=[];opened=os.fdopen
        class Tracked:
            def __init__(self,f):self.f=f
            def __enter__(self):return self
            def __exit__(self,*a):return self.f.__exit__(*a)
            def __getattr__(self,k):return getattr(self.f,k)
            def read(self,*a):
                data=self.f.read(*a);counts.append(len(data));return data
        def track(fd,*a,**kw):
            info=os.fstat(fd);f=opened(fd,*a,**kw)
            return Tracked(f) if (info.st_dev,info.st_ino) in identities else f
        with patch('otam.packed_capture.require_local',return_value={'free':required}),patch('otam.archive.os.fdopen',side_effect=track):
            captured=self.capture(draft)
        self.assertEqual(sum(counts),4*1024**2)
        source=source_capture.location(self.config.staging,draft['job_id'])
        before={p.stat().st_ino for p in source.glob('*.tar')}
        self.assertEqual(len(before),2);self.assertFalse((source/'data').exists())
        self.assertLess(sum(p.stat().st_size for p in source.glob('*.tar')),required)
        shutil.rmtree(self.root/'source')
        medium=execute(self.config,self.control,'create-medium',dict(label='large',capacity=20*1024**2,media_class='rotation'))['media_id']
        self.assertGreater(required,1024**2)
        with patch('otam.storage.require_local',return_value={'free':1024**2}),patch('otam.staging.require_local',return_value={'free':1024**2}):
            bound=self.bind(captured,[medium])
        ready=list(self.config.staging.rglob('ready.tar'))
        self.assertEqual({p.stat().st_ino for p in ready},before)
        self.assertFalse(list(source.glob('*.tar')))
        for path in ready:
            with tarfile.open(path) as tar:
                manifest=json.load(tar.extractfile('OTAM/manifest.json'))
                self.assertEqual(manifest['media_id'],medium)
                self.assertNotIn('capture_only',manifest)
        result=execute(self.config,self.control,'backup',dict(job_id=bound['job_id'],confirm=bound['job_id'],plan_hash=bound['sha256']))
        self.assertEqual(result['state'],'VERIFIED')

    def test_legacy_raw_captures_remain_bindable(self):
        draft=self.preview()
        with patch('otam.packed_capture.prepare',side_effect=source_capture.prepare):
            captured=self.capture(draft)
        self.assertEqual(self.draft(draft['job_id'])['source_capture']['format'],'otam-source-capture-v1')
        shutil.rmtree(self.root/'source')
        self.assertEqual(self.bind(captured,[self.medium('one'),self.medium('two')])['state'],'PLANNED')

    def test_job_view_does_not_send_embedded_file_manifests(self):
        from otam.web.query import CatalogView
        captured=self.capture(self.preview())
        view=CatalogView(self.config,self.control).job(captured['job_id'])
        self.assertEqual(view['plan']['source_capture']['format'],packed_capture.FORMAT)
        self.assertNotIn('entries',view['plan']['source_capture'])
        self.assertNotIn('archives',view['plan']['source_capture'])

    def test_intent_blocks_reuse_even_before_first_payload_move(self):
        captured=self.capture(self.preview());draft=self.draft(captured['job_id'])
        parent=source_capture.location(self.config.staging,captured['job_id'])
        path=packed_capture.path_for(parent,draft['source_capture']['archives'][0])
        path.with_suffix('.binding.json').write_text('{}')
        with self.assertRaisesRegex(SafetyError,'already attempted'):
            self.bind(captured,[self.medium('one'),self.medium('two')])
        self.assertTrue(path.exists())

    def test_interrupted_binding_keeps_intent_and_partial_without_plan_or_retry(self):
        captured=self.capture(self.preview());media=[self.medium('one'),self.medium('two')]
        with patch.object(StagingStore,'_inspect',side_effect=SafetyError('injected verification failure')):
            with self.assertRaisesRegex(SafetyError,'injected'):self.bind(captured,media)
        self.assertTrue(list(self.config.staging.rglob('*.binding.json')))
        self.assertTrue(list(self.config.staging.rglob('*.partial')))
        self.assertFalse(list(self.config.staging.rglob('ready.tar')))
        c=Catalog(self.config.catalog)
        try:
            self.assertEqual(source_plans.load(c,captured['job_id'])[0],'INTERRUPTED')
            self.assertEqual(c.db.execute("select count(*) from jobs where kind in ('archive','archive-set') and state='PLANNED'").fetchone()[0],0)
            self.assertEqual(c.db.execute('select count(*) from archives').fetchone()[0],0)
        finally:c.close()
        with self.assertRaises(SafetyError):self.bind(captured,media)

    def test_source_mutation_during_capture_never_publishes_capture(self):
        draft=self.preview();original=packed_capture.create_archive
        def mutate(*a,**kw):
            progress=kw.pop('progress',None)
            # progress was supplied as fourth positional argument by prepare.
            args=list(a)
            def change(done):
                (self.root/'source/one').write_bytes(b'x'*30000)
                if progress:progress(done)
            args[3]=change
            return original(*args,**kw)
        with patch('otam.packed_capture.create_archive',side_effect=mutate):
            with self.assertRaisesRegex(SafetyError,'changed'):self.capture(draft)
        self.assertNotIn('source_capture',self.draft(draft['job_id']))

    def test_nonzero_reserved_padding_does_not_hide_payload_corruption(self):
        captured=self.capture(self.preview());draft=self.draft(captured['job_id'])
        item=draft['source_capture']['archives'][0]
        path=packed_capture.path_for(source_capture.location(self.config.staging,captured['job_id']),item)
        path.chmod(0o600)
        with tarfile.open(path) as tar:offset=next(m.offset_data for m in tar if m.name.startswith('data/'))
        with path.open('r+b') as f:f.seek(offset);f.write(b'BAD')
        path.chmod(0o400)
        # Model a changed payload even if a metadata fingerprint was recaptured.
        # Independent final byte verification must still fail against saved SHA.
        from otam.staging import fingerprint
        item['fingerprint']=fingerprint(path)
        import hashlib
        draft['sha256']=hashlib.sha256(encode({k:v for k,v in draft.items() if k!='sha256'})).hexdigest()
        c=Catalog(self.config.catalog)
        try:
            with c.db:c.db.execute('update jobs set plan_json=? where id=?',(encode(draft).decode(),captured['job_id']))
        finally:c.close()
        captured['sha256']=draft['sha256']
        with self.assertRaisesRegex(SafetyError,'SHA-256|checksum'):
            self.bind(captured,[self.medium('one'),self.medium('two')])
