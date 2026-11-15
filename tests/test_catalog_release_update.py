"""Test the user-run catalog updater on temporary paths and mocked systemctl/pip."""
import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile
from unittest import TestCase
from unittest.mock import patch
from tools import update_catalog_release as updater


class CatalogReleaseUpdate(TestCase):
    def setUp(self):
        previous_mask=os.umask(0o022);self.addCleanup(os.umask,previous_mask)
        self.temp=tempfile.TemporaryDirectory(dir=os.environ.get('OTAM_TEST_TMPDIR'));self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.venv=self.root/'venv';(self.venv/'bin').mkdir(parents=True);(self.venv/'bin/python').write_text('old installation')
        cfg=self.root/'etc/node.json';cfg.parent.mkdir()
        state=self.root/'state';state.mkdir()
        db=sqlite3.connect(state/'control.sqlite');db.execute('CREATE TABLE keep(value TEXT)');db.execute("INSERT INTO keep VALUES('account data')");db.commit();db.close()
        cfg.write_text(json.dumps({'role':'catalog','state':str(state),'host':'127.0.0.1','port':8765}))
        self.wheel=self.root/'opentape_archive_manager-0.9.0-py3-none-any.whl';self.wheel.write_bytes(b'test wheel')
        self.sha=hashlib.sha256(self.wheel.read_bytes()).hexdigest()
        def paths(value):
            maps={'/etc/otam/node.json':cfg,'/opt/otam/venv':self.venv,'/var/lib/otam/reports':self.root/'reports'}
            return maps.get(str(value),Path(value))
        for name,value in [('tools.update_catalog_release.Path',paths),('tools.update_catalog_release.os.geteuid',lambda:0)]:
            p=patch(name,value);p.start();self.addCleanup(p.stop)
        p=patch('sys.argv',['update','--wheel',str(self.wheel),'--sha256',self.sha]);p.start();self.addCleanup(p.stop)

    def test_checked_private_copy_backup_and_healthy_restart(self):
        calls=[]
        def run(*args,**kwargs):
            calls.append(args)
            if 'pip' in args:
                mask=os.umask(0o077);os.umask(mask);self.assertEqual(mask,0o022)
                release=Path(args[-1]);self.assertNotEqual(release,self.wheel);self.assertEqual(release.read_bytes(),self.wheel.read_bytes())
            return None
        with patch.object(updater,'run',side_effect=run),patch('urllib.request.urlopen',return_value=io.BytesIO(b'{"status":"ok","role":"catalog"}')):
            updater.main()
        reports=list((self.root/'reports').glob('*/report.json'));self.assertEqual(len(reports),1)
        report=json.loads(reports[0].read_text());self.assertEqual(report['state'],'VERIFIED')
        self.assertTrue((reports[0].parent/'control-before.sqlite').exists())
        self.assertEqual(calls[0],('systemctl','stop','otam-web.service'))
        self.assertIn(('systemctl','start','otam-web.service'),calls)
        self.assertTrue(any(args[:3]==('runuser','-u','otam') for args in calls))

    def test_failed_install_restores_old_venv_and_starts_service(self):
        def run(*args,**kwargs):
            if 'pip' in args:
                (self.venv/'bin/python').write_text('failed new code')
                raise subprocess.CalledProcessError(1,args)
        with patch.object(updater,'run',side_effect=run):
            with self.assertRaises(subprocess.CalledProcessError):updater.main()
        self.assertEqual((self.venv/'bin/python').read_text(),'old installation')
        report=json.loads(next((self.root/'reports').glob('*/report.json')).read_text())
        self.assertEqual(report['rollback'],'previous venv restored')

    def test_wrong_hash_never_stops_service(self):
        self.wheel.write_bytes(b'changed')
        with patch.object(updater,'run') as run:
            with self.assertRaises(SystemExit):updater.main()
            run.assert_not_called()
