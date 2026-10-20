import json
import sqlite3
import tempfile
from pathlib import Path
from unittest import TestCase

from otam.catalog import Catalog
from otam.common import SafetyError
from tools.catalog_acceptance_cleanup import preview, apply


class AcceptanceCleanup(TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.catalog = Catalog(Path(temp.name) / 'catalog.sqlite')
        self.addCleanup(self.catalog.close)
        self.catalog.register({'media_id':'test','label':'test','class':'rotation','capacity':10**9},10240)
        self.catalog.register({'media_id':'keep','label':'real','class':'permanent','capacity':10**9},10240)
        self.job = self.catalog.job('archive','test')
        self.catalog.record_archive({'archive_id':'archive','media_id':'test','created':1,'files':[]},self.job,1,'VERIFIED',10240,'a'*64)
        self.catalog.finish(self.job,'VERIFIED')

    def test_removes_only_reviewed_rows_and_preserves_real_medium(self):
        p = preview(self.catalog,['test'],[self.job])
        result = apply(self.catalog,p,'REMOVE TEST CATALOG '+p['sha256'])
        self.assertEqual(result['removed_archives'],1)
        self.assertEqual([r[0] for r in self.catalog.db.execute('SELECT id FROM media')],['keep'])
        self.assertFalse(self.catalog.db.execute('PRAGMA foreign_key_check').fetchall())

    def test_concurrent_catalog_change_or_wrong_confirmation_refuses_without_delete(self):
        p=preview(self.catalog,['test'],[self.job])
        with self.assertRaises(SafetyError):apply(self.catalog,p,'wrong')
        with self.catalog.db:self.catalog.db.execute("UPDATE media SET label='changed' WHERE id='keep'")
        with self.assertRaises(SafetyError):apply(self.catalog,p,'REMOVE TEST CATALOG '+p['sha256'])
        self.assertEqual(self.catalog.db.execute('SELECT count(*) FROM archives').fetchone()[0],1)

    def test_failure_rolls_back_all_deletions(self):
        self.catalog.db.execute("CREATE TRIGGER no_delete BEFORE DELETE ON media BEGIN SELECT RAISE(ABORT,'test failure'); END")
        p=preview(self.catalog,['test'],[self.job])
        with self.assertRaises(sqlite3.IntegrityError):apply(self.catalog,p,'REMOVE TEST CATALOG '+p['sha256'])
        self.assertEqual(self.catalog.db.execute('SELECT count(*) FROM archives').fetchone()[0],1)
        self.assertIsNotNone(self.catalog.db.execute('SELECT id FROM jobs WHERE id=?',(self.job,)).fetchone())

    def test_cross_boundary_and_active_job_are_not_silently_deleted(self):
        with self.catalog.db:self.catalog.db.execute("UPDATE jobs SET media_id='keep' WHERE id=?",(self.job,))
        with self.assertRaises(SafetyError):preview(self.catalog,['test'],[self.job])
        with self.catalog.db:self.catalog.db.execute("UPDATE jobs SET media_id='test',state='RUNNING' WHERE id=?",(self.job,))
        with self.assertRaises(SafetyError):preview(self.catalog,['test'],[self.job])
