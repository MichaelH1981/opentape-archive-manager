import json
from unittest import TestCase
from tests import test_rotation as fixtures
from otam.catalog import Catalog
from otam.web import staging_cleanup
from otam.web.worker import run_once,execute,validate_command
from otam.common import SafetyError

class Cleanup(TestCase):
    setUp=fixtures.Rotation.setUp
    medium=fixtures.Rotation.medium
    create_policy=fixtures.Rotation.create_policy
    add=fixtures.Rotation.add
    prepare=fixtures.Rotation.prepare
    bind=fixtures.Rotation.bind
    complete=fixtures.Rotation.complete

    def test_automatic_only_after_whole_generation_and_unknown_files_preserved(self):
        self.create_policy();self.add();self.add();g=self.prepare();bound=self.bind(g)
        unknown=self.config.staging/'unknown.bin';unknown.write_bytes(b'keep')
        ready=list(self.config.staging.rglob('ready.tar'))
        c=Catalog(self.config.catalog)
        try:plan=json.loads(c.db.execute('select plan_json from jobs where id=?',(bound['job_id'],)).fetchone()[0])
        finally:c.close()
        for index,child in enumerate(plan['children']):
            self.control.enqueue('backup-set',dict(job_id=bound['job_id'],confirm=bound['job_id'],plan_hash=bound['sha256'],media_id=child['media_id']),'cleanup-test-'+str(index))
            self.assertTrue(run_once(self.config,self.control))
            if index<len(plan['children'])-1:self.assertTrue(all(p.exists() for p in ready))
        self.assertTrue(all(not p.exists() for p in ready));self.assertEqual(unknown.read_bytes(),b'keep')

    def test_manual_preview_confirmation_and_active_exclusion(self):
        self.create_policy();self.add();self.add();g=self.prepare();bound=self.bind(g)
        sid='default-staging'
        self.assertEqual(staging_cleanup.preview(self.config,self.control,sid)['generations'],[])
        self.complete(bound)
        p=staging_cleanup.preview(self.config,self.control,sid)
        self.assertEqual(p['generations'],[g])
        with self.assertRaises(SafetyError):execute(self.config,self.control,'cleanup-staging',dict(staging_id=sid,preview_hash='wrong'))
        result=execute(self.config,self.control,'cleanup-staging',dict(staging_id=sid,preview_hash=p['preview_hash']))
        self.assertEqual(result['state'],'SUCCEEDED')
        self.assertEqual(staging_cleanup.preview(self.config,self.control,sid)['generations'],[])
        with self.assertRaises(SafetyError):validate_command(self.config,self.control,'cleanup-staging',{'staging_id':sid})
