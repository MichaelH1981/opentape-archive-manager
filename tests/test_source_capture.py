"""Optional source capture does not change the default media-first TAR path."""
import json
import os
import shutil
from unittest import TestCase
from unittest.mock import patch
from tests import test_source_plans
from otam.catalog import Catalog
from otam.common import SafetyError
from otam.web import source_plans
from otam import source_capture
from otam.web.worker import execute


class SourceCapture(TestCase):
    setUp=test_source_plans.SourcePlans.setUp
    preview=test_source_plans.SourcePlans.preview
    bind=test_source_plans.SourcePlans.bind
    medium=test_source_plans.SourcePlans.medium

    def capture(self,draft):
        return execute(self.config,self.control,'stage-source',{'job_id':draft['job_id'],'source_plan_hash':draft['sha256']})

    def test_default_path_does_not_copy_before_media_selection(self):
        preview=self.preview()
        self.assertFalse(list(self.config.staging.glob('otam-source-*')))
        self.bind(preview,[self.medium('first'),self.medium('second')])
        self.assertFalse(list(self.config.staging.glob('otam-source-*')))

    def test_capture_without_any_medium_and_bind_without_source(self):
        preview=self.preview()
        result=self.capture(preview)
        self.assertTrue(result['source_captured'])
        self.assertNotEqual(preview['sha256'],result['sha256'])
        c=Catalog(self.config.catalog)
        try:
            self.assertEqual(c.db.execute('select count(*) from media').fetchone()[0],0)
            _,draft=source_plans.load(c,preview['job_id'])
            self.assertEqual(len(draft['source_capture']['entries']),2)
            root,_=source_capture.validate(self.config.staging,preview['job_id'],draft['source_capture'])
            self.assertEqual((root/'one').read_bytes(),b'one'*10000)
        finally:c.close()
        shutil.rmtree(self.root/'source')
        first=self.medium('first');second=self.medium('second')
        bound=self.bind(result,[first,second])
        self.assertFalse(source_capture.location(self.config.staging,preview['job_id']).exists())
        execute(self.config,self.control,'backup-set',{'job_id':bound['job_id'],'plan_hash':bound['sha256'],'confirm':bound['job_id'],'media_id':first})
        finished=execute(self.config,self.control,'backup-set',{'job_id':bound['job_id'],'plan_hash':bound['sha256'],'confirm':bound['job_id'],'media_id':second})
        self.assertEqual(finished['state'],'VERIFIED')

    def test_space_failure_has_no_source_copy_or_media_requirement(self):
        preview=self.preview()
        with patch('otam.source_capture.require_local',return_value={'free':1}):
            with self.assertRaisesRegex(SafetyError,'Platz'):self.capture(preview)
        self.assertFalse(list(self.config.staging.glob('otam-source-*')))
        self.bind(preview,[self.medium('first'),self.medium('second')])

    def test_no_overwrite_and_cached_identity_changes_refused(self):
        preview=self.preview();result=self.capture(preview)
        self.assertTrue(self.capture(result)['source_captured'])
        path=self.config.staging/('otam-source-'+preview['job_id'])/'data/one'
        path.chmod(0o600);path.write_bytes(b'corrupted')
        with self.assertRaises(SafetyError):self.capture(result)

    def test_captured_hash_is_checked_during_tar_creation(self):
        from otam.archive import create_archive,plan_archives,estimate_entries,inventory
        source=self.root/'source';entries=inventory(source)
        metadata=inventory(source,metadata_only=True)
        expected=[{**m,'sha256':'0'*64} for m in metadata]
        manifest=plan_archives(estimate_entries(entries),'00000000-0000-0000-0000-000000000000',75000000000)[0]
        with self.assertRaisesRegex(SafetyError,'checksum'):
            create_archive(self.root/'bad.tar',source,manifest,single_pass=True,expected=expected)

    def test_source_change_before_copy_is_rejected(self):
        preview=self.preview();(self.root/'source/one').write_bytes(b'changed')
        with self.assertRaises(SafetyError):self.capture(preview)

    def test_capture_parameters_cannot_bind_media_or_change_selection(self):
        preview=self.preview()
        with self.assertRaises(SafetyError):
            execute(self.config,self.control,'stage-source',{'job_id':preview['job_id'],'source_plan_hash':preview['sha256'],'media_ids':[]})

    def test_long_source_filename_can_be_copied(self):
        name='x'*240
        (self.root/'source'/name).write_bytes(b'long name')
        result=self.capture(self.preview())
        self.assertTrue(result['source_captured'])
