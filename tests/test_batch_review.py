import json
import sqlite3
from unittest import TestCase
from tests import test_source_plans as fixtures
from otam.catalog import Catalog
from otam.common import SafetyError
from otam.web.worker import execute
from otam.web import batch


class BatchReview(TestCase):
    setUp=fixtures.SourcePlans.setUp
    medium=fixtures.SourcePlans.medium
    preview=fixtures.SourcePlans.preview
    bind=fixtures.SourcePlans.bind

    def start(self):
        self.request['verify_mode']='archive'
        ids=[self.medium('one'),self.medium('two')]
        bound=self.bind(self.preview(),ids)
        c=Catalog(self.config.catalog)
        try:plan=json.loads(c.db.execute('select plan_json from jobs where id=?',(bound['job_id'],)).fetchone()[0])
        finally:c.close()
        return bound,plan,ids

    def request_mode(self,bound):
        return {'job_id':bound['job_id'],'plan_hash':bound['sha256'],'confirm':bound['job_id'],'verify_mode':'media'}

    def test_073_waiting_medium_plan_continues_without_rewriting_first(self):
        bound,plan,ids=self.start()
        payload={'job_id':bound['job_id'],'plan_hash':bound['sha256'],'confirm':bound['job_id'],'media_id':ids[0]}
        self.assertEqual(execute(self.config,self.control,'backup-set',payload)['state'],'WAITING_MEDIA')
        c=Catalog(self.config.catalog)
        try:
            first=c.db.execute('select plan_json from jobs where id=?',(plan['children'][0]['job_id'],)).fetchone()[0]
            rows=[tuple(r) for r in c.db.execute('select id,state,sha256 from archives order by id')]
            from pathlib import Path
            copy=sqlite3.connect(self.root/'compat.sqlite');c.db.backup(copy);copy.close()
        finally:c.close()
        # Read-only offer neither hashes payload nor changes plans.
        offer=batch.offer(self.config,self.control,bound['job_id']);self.assertTrue(offer['available'])
        result=execute(self.config,self.control,'set-verification-mode',self.request_mode(bound))
        self.assertNotEqual(result['sha256'],bound['sha256'])
        c=Catalog(self.config.catalog)
        try:
            self.assertEqual(c.db.execute('select plan_json from jobs where id=?',(plan['children'][0]['job_id'],)).fetchone()[0],first)
            self.assertEqual([tuple(r) for r in c.db.execute('select id,state,sha256 from archives order by id')],rows)
        finally:c.close()
        with self.assertRaises(SafetyError):execute(self.config,self.control,'backup-set',{**payload,'media_id':ids[1]})
        self.assertEqual(execute(self.config,self.control,'backup-set',{**payload,'media_id':ids[1],'plan_hash':result['sha256']})['state'],'VERIFIED')

    def test_active_plan_invalid_confirmation_and_event_failure_leave_plan_intact(self):
        bound,plan,ids=self.start();request=self.request_mode(bound)
        with self.assertRaises(SafetyError):execute(self.config,self.control,'set-verification-mode',{**request,'confirm':'wrong'})
        c=Catalog(self.config.catalog)
        try:
            original=c.db.execute('select plan_json from jobs where id=?',(bound['job_id'],)).fetchone()[0]
            with c.db:c.db.execute("update jobs set state='RUNNING' where id=?",(bound['job_id'],))
            with self.assertRaises(SafetyError):batch.review(c,request,apply=True)
            with c.db:
                c.db.execute("update jobs set state='PLANNED' where id=?",(bound['job_id'],))
                c.db.execute("CREATE TRIGGER fail_review BEFORE INSERT ON events WHEN NEW.event='verification_mode_reviewed' BEGIN SELECT RAISE(ABORT,'test rollback'); END")
            with self.assertRaises(sqlite3.IntegrityError):batch.review(c,request,apply=True)
            self.assertEqual(c.db.execute('select plan_json from jobs where id=?',(bound['job_id'],)).fetchone()[0],original)
            for child in plan['children']:
                p=json.loads(c.db.execute('select plan_json from jobs where id=?',(child['job_id'],)).fetchone()[0]);self.assertEqual(p['verify_mode'],'media' if plan['verify_mode']=='media' else 'archive')
        finally:c.close()

    def test_full_staging_offer_uses_actual_free_space(self):
        from unittest.mock import patch
        bound,_,_=self.start()
        with patch('otam.web.resources.require_local',return_value={'free':1}):
            info=batch.offer(self.config,self.control,bound['job_id'])
        self.assertFalse(info['available']);self.assertGreater(info['required_new_bytes'],1)

    def test_physical_cli_queues_explicit_mode_review_without_changing_plan(self):
        import io
        from contextlib import redirect_stdout,redirect_stderr
        from dataclasses import asdict,replace
        from unittest.mock import patch
        from otam.cli import main
        bound,_,_=self.start()
        config=replace(self.config,physical_maintenance=True,physical_archiving=True,physical_multivolume=True)
        self.control.set('operation_mode','physical')
        config_path=self.root/'node.json';config_path.write_text(json.dumps(asdict(config),default=str))
        request=self.request_mode(bound);payload=self.root/'request.json'
        payload.write_text(json.dumps({**request,'plan_hash':'0'*64}))
        args=['physical-command','--config',str(config_path),'--kind','set-verification-mode',
              '--payload-file',str(payload),'--idempotency-key','review-test']
        with redirect_stderr(io.StringIO()):self.assertEqual(main(args),1)
        self.assertEqual(self.control.commands(),[])
        payload.write_text(json.dumps(request))
        with patch('otam.web.physical_archive.discover_drives') as discover,redirect_stdout(io.StringIO()):
            self.assertEqual(main(args),0);self.assertEqual(main(args),0)
            discover.assert_not_called()
        commands=self.control.commands();self.assertEqual(len(commands),1)
        self.assertEqual(commands[0]['state'],'QUEUED')
        c=Catalog(self.config.catalog)
        try:self.assertEqual(json.loads(c.db.execute('select plan_json from jobs where id=?',(bound['job_id'],)).fetchone()[0])['sha256'],bound['sha256'])
        finally:c.close()
