import json,os,tempfile
from pathlib import Path
from unittest import TestCase
from concurrent.futures import ThreadPoolExecutor
from fastapi.testclient import TestClient
from otam.web.config import initialize,WebConfig
from otam.web.app import create_app
from otam.web.control import Control
from otam.web.first_start import enroll
from fastapi import HTTPException

class FirstStart(TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=os.environ.get('OTAM_TEST_TMPDIR'));self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name).resolve();self.path=self.root/'node.json'
        initialize(self.path,self.root/'data','archive',None)
        self.config=WebConfig.load(self.path);self.token=self.config.setup_token_file.read_text().strip()
        self.client=TestClient(create_app(self.config),base_url='http://localhost');self.addCleanup(self.client.close)
        self.payload={'username':'admin','password':'test-only-long-password','confirmation':'test-only-long-password','token':self.token}
    def test_no_default_login_and_enrollment_once_survives_restart(self):
        self.assertTrue(self.client.get('/api/v1/setup').json()['required'])
        self.assertEqual(self.client.get('/api/v1/jobs').status_code,401)
        self.assertEqual(self.client.post('/api/v1/login',json={'username':'admin','password':'admin'}).status_code,401)
        self.assertEqual(self.client.post('/api/v1/setup',json=self.payload).status_code,200)
        self.assertFalse(self.client.get('/api/v1/setup').json()['required'])
        self.assertFalse(self.config.setup_token_file.exists())
        self.assertEqual(self.client.post('/api/v1/setup',json=self.payload).status_code,409)
        self.assertEqual(self.client.post('/api/v1/login',json={'username':'admin','password':self.payload['password']}).status_code,200)
        with TestClient(create_app(self.config),base_url='http://localhost') as restarted:
            self.assertFalse(restarted.get('/api/v1/setup').json()['required'])
        c=Control(self.config.state)
        with c.connect() as db:
            row=db.execute('select * from users').fetchone();self.assertNotEqual(row['password_hash'],self.payload['password']);self.assertEqual(row['role'],'admin')
            db.execute('delete from sessions');db.execute('delete from users')
        self.assertFalse(self.client.get('/api/v1/setup').json()['required'])
    def test_bad_token_confirmation_origin_and_unknown_fields(self):
        for payload,status in [({**self.payload,'token':'x'*64},403),({**self.payload,'confirmation':'different-test-password'},400),({**self.payload,'role':'admin'},422)]:
            self.assertEqual(self.client.post('/api/v1/setup',json=payload).status_code,status)
        self.assertEqual(self.client.post('/api/v1/setup',json=self.payload,headers={'origin':'https://evil.invalid'}).status_code,403)
        self.assertTrue(self.client.get('/api/v1/setup').json()['required'])
    def test_rate_limit_and_private_token_file(self):
        for _ in range(10):self.assertEqual(self.client.post('/api/v1/setup',json={**self.payload,'token':'x'*64}).status_code,403)
        self.assertEqual(self.client.post('/api/v1/setup',json=self.payload).status_code,429)
    def test_permissive_token_file_rejected(self):
        self.config.setup_token_file.chmod(0o644)
        self.assertEqual(self.client.post('/api/v1/setup',json=self.payload).status_code,409)
    def test_concurrent_enrollment_only_one_admin(self):
        def run(_):
            try:enroll(self.config,Control(self.config.state),'admin',self.payload['password'],self.payload['password'],self.token,'local');return True
            except (HTTPException,OSError):return False
        with ThreadPoolExecutor(max_workers=2) as pool:self.assertEqual(sum(pool.map(run,range(2))),1)
        with Control(self.config.state).connect() as db:self.assertEqual(db.execute('select count(*) from users').fetchone()[0],1)
    def test_existing_installation_keeps_accounts(self):
        from dataclasses import replace
        config=replace(self.config,setup_token_file=None)
        with TestClient(create_app(config),base_url='http://localhost') as client:
            self.assertFalse(client.get('/api/v1/setup').json()['required'])
