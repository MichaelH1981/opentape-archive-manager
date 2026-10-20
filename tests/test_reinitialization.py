"""Explicit reinitialization preserves uncertainty and ignores simulator identities."""
import json
import os
import subprocess
import sys
import time
import uuid
from contextlib import ExitStack
from dataclasses import replace, asdict
from unittest import TestCase
from unittest.mock import patch
from otam.common import SafetyError
from otam.catalog import Catalog
from otam.tape import LinuxTape
from otam.web import initialization as init, reinitialization as reinit
from otam.web.worker import execute
from tests import test_initialization as initialization_tests
from tests.test_linux_tape_flow import FileST


class Reinitialization(TestCase):
    setUp=initialization_tests.Initialization.setUp
    inventory=initialization_tests.Initialization.inventory
    payload=initialization_tests.Initialization.payload

    def prior(self,media=None,state='SUCCEEDED',write=True):
        value={'id':str(uuid.uuid4()),'drive':self.drive,'state':state,'write_attempted':write,
               'finished':time.time(),'media_id':media or self.header['media_id']}
        self.control.set(init.PREFIX+value['id'],value)
        return value

    def grant(self):
        self.config=replace(self.config,physical_reinitialization=True)
        return init.prepare(self.config,self.control,self.data,reinitialize=True)

    def test_review_is_separate_and_seals_prior_history(self):
        self.prior()
        with self.assertRaisesRegex(SafetyError,'abgeschlossen'):init.prepare(self.config,self.control,self.data)
        with self.assertRaises(SafetyError):init.prepare(self.config,self.control,self.data,reinitialize=True)
        g=self.grant();self.assertEqual(g['confirmation'],'REINITIALIZE DRIVE MAM')
        with self.assertRaises(SafetyError):init.approval(self.config,self.control,self.payload(g))
        g['previous_initializations'][0]['media_id']=str(uuid.uuid4())
        self.control.set(reinit.PREFIX+g['id'],g)
        with self.assertRaises(SafetyError):init.approval(self.config,self.control,self.payload(g),reinitialize=True)

    def test_uncertain_intents_pending_and_registered_media_cannot_be_forced(self):
        self.prior();self.config=replace(self.config,physical_reinitialization=True)
        for state in ('CONSUMED','FAILED','INTERRUPTED'):
            value=self.prior(state=state)
            with self.assertRaises(SafetyError):self.grant()
            with self.control.connect() as db:db.execute('DELETE FROM settings WHERE key=?',(init.PREFIX+value['id'],))
        self.config.state.joinpath('physical-pending').mkdir()
        import hashlib
        p=self.config.state/'physical-pending'/(hashlib.sha256(b'MAM').hexdigest()+'.json')
        p.write_text('{}')
        with self.assertRaises(SafetyError):self.grant()
        p.unlink()
        c=Catalog(self.config.catalog)
        try:
            c.register(self.header,10240)
            for state in ('READY','ARCHIVED','RETIRED','SUSPECT'):
                with c.db:c.db.execute('UPDATE media SET state=?',(state,))
                with self.assertRaises(SafetyError):self.grant()
        finally:c.close()

    def test_simulator_serial_or_label_never_blocks_physical_initialization(self):
        c=Catalog(self.config.catalog)
        try:
            fake={**self.header,'media_id':str(uuid.uuid4()),'backend':'simulator','label':'MAM'}
            c.register(fake,10240)
            with c.db:c.db.execute("UPDATE media SET serial='MAM'")
        finally:c.close()
        g=init.prepare(self.config,self.control,self.data)
        self.assertEqual(g['state'],'PREPARED')
        with self.assertRaises(SafetyError):self.grant() # no completed real initialization exists

    def test_process_loss_after_reservation_blocks_new_force_review(self):
        self.prior();g=self.grant();path=self.root/'config.json';path.write_text(json.dumps(asdict(self.config),default=str))
        script='''
import sys,os,json
from pathlib import Path
from otam.web.config import WebConfig
from otam.web.control import Control
from otam.web.initialization import approval
c=WebConfig.load(Path(sys.argv[1]));approval(c,Control(c.state),json.loads(sys.argv[2]),reinitialize=True,consume=True);os._exit(79)
'''
        result=subprocess.run([sys.executable,'-c',script,str(path),json.dumps(self.payload(g))],capture_output=True)
        self.assertEqual(result.returncode,79,result.stderr)
        with self.assertRaises(SafetyError):self.grant()
        with self.assertRaises(SafetyError):init.prepare(self.config,self.control,self.data)

    def test_real_backend_rechecks_existing_header_and_writes_new_uuid_once(self):
        device=FileST(self.root,self.drive)
        with ExitStack() as stack:
            stack.enter_context(patch('otam.physical.LinuxMaintenance',return_value=device))
            stack.enter_context(patch('otam.physical.run',side_effect=device.move))
            stack.enter_context(patch('otam.physical.status',side_effect=device.status))
            stack.enter_context(patch.object(LinuxTape,'_driver_mode'))
            stack.enter_context(patch('otam.web.initialization.discover_drives',return_value=[self.drive]))
            tape=LinuxTape(self.drive,self.config.state)
            with tape.locked():old=tape.initialize('OLD',800000000000,'rotation','INITIALIZE MAM')
            saved=self.prior(old['media_id']);g=self.grant()
            result=execute(self.config,self.control,'reinitialize-physical',self.payload(g))
            self.assertNotEqual(result['media_id'],old['media_id']);self.assertEqual(len(device.files),1)
            self.assertEqual(self.control.get(init.PREFIX+saved['id']),saved)
            self.assertEqual(self.control.get(reinit.PREFIX+g['id'])['state'],'SUCCEEDED')
            self.assertEqual(device.reads,[0,0,0]) # original header readback, old header check, new readback

    def test_wrong_old_header_is_refused_without_writer(self):
        self.prior();g=self.grant()
        with patch('otam.web.initialization.discover_drives',return_value=[self.drive]),patch('otam.web.initialization.LinuxTape') as constructor:
            tape=constructor.return_value;tape.positions.return_value=[0];tape.header.return_value={**self.header,'media_id':str(uuid.uuid4())}
            with self.assertRaises(SafetyError):init.execute(self.config,self.control,self.payload(g),reinitialize=True)
            tape.initialize.assert_not_called()
        self.assertFalse(self.control.get(reinit.PREFIX+g['id'])['write_attempted'])

    def test_failure_after_header_publication_does_not_allow_another_force_review(self):
        self.prior();g=self.grant()
        with patch('otam.web.initialization.discover_drives',return_value=[self.drive]),patch('otam.web.initialization.LinuxTape') as constructor,patch('otam.web.initialization.Catalog.register',side_effect=OSError('publication failure')):
            tape=constructor.return_value;new={**self.header,'media_id':str(uuid.uuid4())}
            tape.header.side_effect=[self.header,new];tape.positions.return_value=[0]
            tape.initialize.return_value=new
            with self.assertRaises(OSError):init.execute(self.config,self.control,self.payload(g),reinitialize=True)
        self.assertTrue(self.control.get(reinit.PREFIX+g['id'])['write_attempted'])
        with self.assertRaises(SafetyError):self.grant()

    def test_header_only_acceptance_harness_preserves_completed_history(self):
        from pathlib import Path
        from tools import tape_reinitialization_acceptance as harness
        device=FileST(self.root,self.drive)
        with ExitStack() as stack:
            stack.enter_context(patch('otam.physical.LinuxMaintenance',return_value=device))
            stack.enter_context(patch('otam.physical.run',side_effect=device.move))
            stack.enter_context(patch('otam.physical.status',side_effect=device.status))
            stack.enter_context(patch.object(LinuxTape,'_driver_mode'))
            stack.enter_context(patch('otam.web.initialization.discover_drives',return_value=[self.drive]))
            stack.enter_context(patch.object(harness,'discover_drives',return_value=[self.drive]))
            tape=LinuxTape(self.drive,self.config.state)
            with tape.locked():old=tape.initialize('OLD',800000000000,'rotation','INITIALIZE MAM')
            saved=self.prior(old['media_id']);config=self.root/'node.json'
            config.write_text(json.dumps(asdict(self.config),default=str))
            before=config.read_bytes();root=self.root/'proof'
            stack.enter_context(patch.object(sys,'argv',['harness','--config',str(config),'--report-root',str(root),'--drive-serial','DRIVE','--medium-serial','MAM','--confirm','REINITIALIZE DRIVE MAM']))
            harness.main()
            report=json.loads((root/'report.json').read_text())
            self.assertEqual(report['state'],'VERIFIED');self.assertEqual(report['header_reads'],[0,0])
            self.assertTrue(report['archive_prefix_unchanged']);self.assertEqual(config.read_bytes(),before)
            self.assertEqual(self.control.get(init.PREFIX+saved['id']),saved)

    def test_confirmed_zero_logical_files_allows_explicit_reinitialization(self):
        device=FileST(self.root,self.drive)
        with ExitStack() as stack:
            stack.enter_context(patch('otam.physical.LinuxMaintenance',return_value=device))
            stack.enter_context(patch('otam.physical.run',side_effect=device.move))
            stack.enter_context(patch('otam.physical.status',side_effect=device.status))
            stack.enter_context(patch.object(LinuxTape,'_driver_mode'))
            stack.enter_context(patch('otam.web.initialization.discover_drives',return_value=[self.drive]))
            self.prior();g=self.grant()
            result=execute(self.config,self.control,'reinitialize-physical',self.payload(g))
            self.assertEqual(result['state'],'INITIALIZED');self.assertEqual(device.reads,[0])
            c=Catalog(self.config.catalog)
            try:
                row=c.db.execute("SELECT details_json FROM events WHERE event='initialization_confirmed'").fetchone()
                self.assertEqual(json.loads(row[0])['previous_header_state'],'confirmed_eod_zero')
            finally:c.close()
