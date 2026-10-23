"""Destructive reset approvals and durable journal handoff, inert file devices."""
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
import uuid
from contextlib import ExitStack
from dataclasses import replace, asdict
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from otam.catalog import Catalog
from otam.common import SafetyError
from otam.tape import LinuxTape
from otam.web.config import WebConfig, Resource
from otam.web.control import Control
from otam.web import reset, initialization
from tests.test_linux_tape_flow import FileST, LocalProducer


class Reset(TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory(dir=os.environ.get('OTAM_TEST_TMPDIR'));self.addCleanup(temp.cleanup)
        self.root=Path(temp.name).resolve();(self.root/'source').mkdir();(self.root/'staging').mkdir()
        self.config=WebConfig(str(uuid.uuid4()),'test','archive',self.root/'state',self.root/'catalog.sqlite',
                              self.root/'staging',self.root/'media',self.root/'restore','pbkdf2_sha256$600000$salt$hash',
                              sources=(Resource('source','source',self.root/'source'),),physical_maintenance=True,
                              physical_archiving=True,physical_initialization=True,physical_reset=True)
        self.control=Control(self.config.state);self.control.set('operation_mode','physical')
        self.drive={'id':'drive','serial':'DRIVE','medium_serial':'MAM','device':'/dev/nst0','ready':True,
                    'vendor':'IBM','model':'ULT3580-HH4','status':{'online':True,'density_code':0x46,'write_protected':False}}
        self.control.set('hardware_inventory',{'time':time.time(),'drives':[self.drive]})
        self.pending=self.config.state/'physical-pending'/(hashlib.sha256(b'MAM').hexdigest()+'.json')
        self.pending.parent.mkdir();self.old_id=str(uuid.uuid4())
        self.pending.write_text(json.dumps({'medium_serial':'MAM','media_id':self.old_id,'position':3}))
        self.original=self.pending.read_bytes()
        self.data={'drive_id':'drive','drive_serial':'DRIVE','medium_serial':'MAM','label':'REUSED','media_class':'rotation'}

    def grant(self):return reset.prepare(self.config,self.control,self.data)
    def payload(self,g):return {'approval_id':g['id'],'confirmation':g['confirmation'],'destructive_confirmed':True}

    def test_review_is_read_only_and_default_gate_native_capacity_and_scope(self):
        with patch('otam.web.reset.discover_drives') as scan,patch('otam.web.reset.LinuxTape') as device:
            g=self.grant();scan.assert_not_called();device.assert_not_called()
        self.assertEqual(g['confirmation'],'RESET DRIVE MAM');self.assertEqual(g['capacity'],800_000_000_000)
        self.assertEqual(self.pending.read_bytes(),self.original)
        with self.assertRaises(SafetyError):reset.prepare(replace(self.config,physical_reset=False),self.control,self.data)
        with self.assertRaises(SafetyError):reset.prepare(self.config,self.control,{**self.data,'capacity':1})
        with self.assertRaises(SafetyError):replace(self.config,physical_initialization=False).validate()

    def test_all_registered_states_and_classes_are_protected(self):
        c=Catalog(self.config.catalog)
        try:
            c.register({'media_id':self.old_id,'medium_serial':'MAM','label':'existing','class':'permanent','capacity':10**9},10240)
            for state in ('READY','IN_USE','ARCHIVED','SUSPECT','RETIRED'):
                for kind in ('permanent','rotation'):
                    with c.db:c.db.execute('UPDATE media SET state=?,class=?',(state,kind))
                    with self.assertRaises(SafetyError):self.grant()
        finally:c.close()
        self.assertEqual(self.pending.read_bytes(),self.original)

    def test_changed_marker_metadata_and_consumed_grants_refuse_before_device(self):
        g=self.grant();other=self.grant()
        self.pending.write_text(self.original.decode()+' ')
        with self.assertRaises(SafetyError):reset.approval(self.config,self.control,self.payload(g),consume=True)
        self.pending.write_bytes(self.original)
        changed=dict(g,label='INJECTED');self.control.set(reset.PREFIX+g['id'],changed)
        with self.assertRaises(SafetyError):reset.approval(self.config,self.control,self.payload(g),consume=True)
        self.control.set(reset.PREFIX+g['id'],g)
        reset.approval(self.config,self.control,self.payload(g),consume=True)
        with self.assertRaises(SafetyError):reset.approval(self.config,self.control,self.payload(other),consume=True)

    def test_real_process_death_after_reservation_prevents_new_review(self):
        g=self.grant();p=self.root/'config.json';p.write_text(json.dumps(asdict(self.config),default=str))
        script='''
import os,json,sys
from pathlib import Path
from otam.web.config import WebConfig
from otam.web.control import Control
from otam.web.reset import approval
c=WebConfig.load(Path(sys.argv[1]));approval(c,Control(c.state),json.loads(sys.argv[2]),consume=True);os._exit(79)
'''
        result=subprocess.run([sys.executable,'-c',script,str(p),json.dumps(self.payload(g))],capture_output=True)
        self.assertEqual(result.returncode,79,result.stderr)
        with self.assertRaises(SafetyError):self.grant()
        self.assertEqual(self.pending.read_bytes(),self.original)

    def test_review_expiry_symlinks_and_fresh_medium_swap_fail_closed(self):
        g=self.grant();g['created']-=301;g['expires']-=301;g['review_hash']=reset.digest(g)
        self.control.set(reset.PREFIX+g['id'],g)
        with self.assertRaises(SafetyError):reset.approval(self.config,self.control,self.payload(g))
        g=self.grant()
        with patch('otam.web.reset.discover_drives',return_value=[{**self.drive,'medium_serial':'OTHER'}]),patch('otam.web.reset.LinuxTape') as tape:
            with self.assertRaises(SafetyError):reset.execute(self.config,self.control,self.payload(g))
            tape.assert_not_called()
        self.assertEqual(self.pending.read_bytes(),self.original)
        self.pending.unlink();target=self.root/'external';target.write_bytes(self.original);self.pending.symlink_to(target)
        with self.assertRaises(SafetyError):self.grant()

    def test_real_process_death_after_guard_handoff_retains_evidence(self):
        script = r"""
import sys,os,uuid,hashlib
from pathlib import Path
from unittest.mock import patch
from otam.tape import LinuxTape
from tests.test_linux_tape_flow import FileST
root=Path(sys.argv[1]);drive={'id':'drive','serial':'DRIVE','medium_serial':'MAM','device':'/dev/nst0','ready':True,'status':{'online':True,'density_code':70}}
dev=FileST(root,drive)
with patch('otam.physical.LinuxMaintenance',return_value=dev),patch('otam.physical.run',side_effect=dev.move),patch('otam.physical.status',side_effect=dev.status),patch.object(LinuxTape,'_driver_mode'):
    tape=LinuxTape(drive,root/'state')
    checksum=hashlib.sha256(tape._pending.read_bytes()).hexdigest()
    with tape.locked(),patch.object(tape,'_initialize_header',side_effect=lambda *a:os._exit(79)):
        tape.reset_interrupted('NEW',800000000000,'rotation',checksum,str(uuid.uuid4()),'RESET DRIVE MAM')
"""
        result=subprocess.run([sys.executable,'-c',script,str(self.root)],capture_output=True)
        self.assertEqual(result.returncode,79,result.stderr)
        self.assertFalse(self.pending.exists())
        with ExitStack() as stack:
            self.device_stack(stack);fresh=LinuxTape(self.drive,self.config.state)
            self.assertTrue(fresh._reset.is_file())
            with fresh.locked(),patch.object(fresh,'_move',side_effect=AssertionError('movement forbidden')):
                with self.assertRaises(SafetyError):fresh.append(self.root/'absent',self.old_id)
        self.assertEqual(next((self.config.state/'physical-reset-history').glob('*previous-pending.json')).read_bytes(),self.original)
        with self.assertRaises(SafetyError):self.grant()

    def device_stack(self, stack):
        self.device=FileST(self.root,self.drive)
        stack.enter_context(patch('otam.physical.LinuxMaintenance',return_value=self.device))
        stack.enter_context(patch('otam.physical.run',side_effect=self.device.move))
        stack.enter_context(patch('otam.physical.status',side_effect=self.device.status))
        stack.enter_context(patch.object(LinuxTape,'_driver_mode'))
        stack.enter_context(patch('otam.web.reset.discover_drives',return_value=[self.drive]))

    def test_real_backend_journal_handoff_failure_blocks_fresh_append_and_initializer(self):
        with ExitStack() as stack:
            self.device_stack(stack)
            tape=LinuxTape(self.drive,self.config.state);ident=str(uuid.uuid4())
            with tape.locked(),patch.object(tape,'_initialize_header',side_effect=OSError('injected header failure')):
                with self.assertRaises(OSError):tape.reset_interrupted('REUSED',800_000_000_000,'rotation',hashlib.sha256(self.original).hexdigest(),ident,'RESET DRIVE MAM')
            self.assertFalse(self.pending.exists());self.assertTrue(tape._reset.is_file())
            self.assertEqual((self.config.state/'physical-reset-history'/(ident+'-previous-pending.json')).read_bytes(),self.original)
            fresh=LinuxTape(self.drive,self.config.state)
            with fresh.locked(),patch.object(fresh,'_move',side_effect=AssertionError('movement forbidden')):
                with self.assertRaises(SafetyError):fresh.append(self.root/'absent.tar',self.old_id)
                with self.assertRaises(SafetyError):fresh.initialize('NEW',10**9,'rotation','INITIALIZE MAM')
            with self.assertRaises(SafetyError):initialization.prepare(self.config,self.control,self.data)
            with self.assertRaises(SafetyError):self.grant()

    def test_normal_worker_reset_then_full_backup_and_restore_with_retained_audit(self):
        from otam.web.worker import execute
        from otam.service import ArchiveService
        with ExitStack() as stack:
            self.device_stack(stack)
            for name in ('otam.physical.discover_drives','otam.web.physical_archive.discover_drives'):
                stack.enter_context(patch(name,return_value=[self.drive]))
            storage={'free':10**9,'mount':str(self.config.staging),'source':'/dev/test','device':'1:2','type':'ext4'}
            for name in ('otam.storage.require_local','otam.staging.require_local','otam.web.resources.require_local','otam.web.physical_archive.require_local'):
                stack.enter_context(patch(name,return_value=storage))
            stack.enter_context(patch('otam.service.require_qualification'))
            stack.enter_context(patch('otam.benchmark.available_memory',return_value=8*1024**3))
            stack.enter_context(patch('subprocess.Popen',side_effect=LocalProducer))
            grant=self.grant();result=execute(self.config,self.control,'reset-physical',self.payload(grant))
            self.assertNotEqual(result['media_id'],self.old_id);self.assertEqual(len(self.device.files),1)
            self.assertFalse(self.pending.exists());self.assertFalse(LinuxTape(self.drive,self.config.state)._reset.exists())
            history=self.config.state/'physical-reset-history'
            self.assertEqual((history/(grant['id']+'-previous-pending.json')).read_bytes(),self.original)
            self.assertTrue((history/(grant['id']+'-completed.json')).is_file())
            self.assertEqual(self.control.get(reset.PREFIX+grant['id'])['state'],'SUCCEEDED')
            with self.assertRaises(SafetyError):reset.approval(self.config,self.control,self.payload(grant),consume=True)
            source=self.root/'source';(source/'file.txt').write_bytes(b'new production data'*100)
            self.control.set('transfer_settings:default-staging',{'drive_id':'drive','drive_serial':'DRIVE','profile_id':'ibm-ult3580-hh4-lto4',
                'medium_density_code':0x46,'write_rate_bytes_per_second':120_000_000,'buffer_bytes':2368*1024**2,
                'storage':{k:storage[k] for k in ('mount','source','device','type')}})
            plan=execute(self.config,self.control,'plan',{'media_id':result['media_id'],'source_id':'source','target':10000+240})
            execute(self.config,self.control,'stage',{'job_id':plan['job_id']})
            written=execute(self.config,self.control,'backup',{'job_id':plan['job_id'],'confirm':plan['job_id'],'plan_hash':plan['sha256']})
            self.assertEqual(written['state'],'VERIFIED')
            self.assertEqual(execute(self.config,self.control,'restore',{'media_id':result['media_id'],'target_name':'restored'})['state'],'VERIFIED')
            self.assertEqual((self.config.restore_root/'restored/file.txt').read_bytes(),(source/'file.txt').read_bytes())

    def test_publication_failure_keeps_new_medium_suspect_and_guard_present(self):
        with ExitStack() as stack:
            self.device_stack(stack)
            g=self.grant()
            stack.enter_context(patch('otam.web.reset.Catalog.register',side_effect=OSError('catalog publish failed')))
            with self.assertRaises(OSError):reset.execute(self.config,self.control,self.payload(g))
            self.assertTrue(LinuxTape(self.drive,self.config.state)._reset.is_file())
            self.assertEqual(self.control.get(reset.PREFIX+g['id'])['state'],'FAILED')
            with self.assertRaises(SafetyError):self.grant()
