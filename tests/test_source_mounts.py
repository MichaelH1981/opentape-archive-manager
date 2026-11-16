"""Mount commands are constrained, read-only and never contain SMB passwords."""
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch
import json,os,stat,tempfile,uuid
from otam.common import SafetyError
from otam.web import source_mounts as m


class SourceMounts(TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory(dir=os.environ.get('OTAM_TEST_TMPDIR'));self.addCleanup(t.cleanup)
        self.root=Path(t.name);self.targets=self.root/'mounts';self.targets.mkdir()
        self.owner=SimpleNamespace(pw_uid=os.getuid(),pw_gid=os.getgid())
        self.key=str(uuid.uuid4())
        self.p=patch.object(m,'TARGETS',self.targets);self.p.start();self.addCleanup(self.p.stop)
        self.p=patch.object(m,'policy',return_value={'allowed_networks':['192.168.1.0/24']});self.p.start();self.addCleanup(self.p.stop)
        original=Path.lstat
        def lstat(path,*a,**kw):
            value=original(path,*a,**kw)
            if path==self.targets:return SimpleNamespace(st_mode=stat.S_IFDIR|0o755,st_uid=0)
            return value
        p=patch.object(Path,'lstat',lstat);p.start();self.addCleanup(p.stop)
        self.networks=['192.168.1.0/24']
        self.nfs=dict(kind='nfs',server='192.168.1.120',export='/backup')

    def test_network_and_path_constraints(self):
        m.validate(self.nfs,self.networks)
        for server in ('127.0.0.1','8.8.8.8','nas.example.org','::1','192.168.2.3'):
            with self.assertRaises(SafetyError):m.validate({**self.nfs,'server':server},self.networks)
        for export in ('relative','/../etc','/backup,exec','/a\nsecret'):
            with self.assertRaises(SafetyError):m.validate({**self.nfs,'export':export},self.networks)
        with self.assertRaises(SafetyError):m.validate({**self.nfs,'options':'rw'},self.networks)

    def observed(self,**changes):
        return json.dumps({'filesystems':[{'target':str(self.targets/self.key),'source':'192.168.1.120:/backup','fstype':'nfs4','options':'ro,nosuid,nodev,noexec',**changes}]})

    def test_nfs_exact_readonly_command_and_verified_result(self):
        calls=[]
        def command(args,*a):
            calls.append(args)
            return self.observed() if 'findmnt' in args[0] else ''
        with patch.object(m,'command',side_effect=command):r=m.execute_mount(None,self.nfs,self.key,self.owner)
        self.assertTrue(r['read_only']);self.assertEqual(r['state'],'MOUNTED')
        self.assertEqual(calls[0],['/usr/bin/mount','-t','nfs','-o','ro,nosuid,nodev,noexec,vers=4.1','--','192.168.1.120:/backup',str(self.targets/self.key)])

    def test_rw_or_wrong_mount_result_is_never_published_as_success(self):
        with patch.object(m,'command',side_effect=['',self.observed(options='rw,nosuid,nodev,noexec'),'']):
            with self.assertRaises(SafetyError):m.execute_mount(None,self.nfs,self.key,self.owner)

    def test_usb_excludes_mounted_system_disks_sata_and_duplicate_uuids(self):
        disks=[{'path':'/dev/sda','tran':'sata','mountpoints':[],'children':[{'path':'/dev/sda1','type':'part','uuid':'system','fstype':'ext4','mountpoints':['/']}]},
               {'path':'/dev/sdb','tran':'usb','mountpoints':[],'children':[{'path':'/dev/sdb1','type':'part','uuid':'stage','fstype':'ext4','mountpoints':['/srv/otam/staging-hdd']}]},
               {'path':'/dev/sdc','tran':'usb','mountpoints':[],'children':[{'path':'/dev/sdc1','type':'part','uuid':'safe-1234','fstype':'ext4','mountpoints':[]}]}]
        with patch.object(m,'command',return_value=json.dumps({'blockdevices':disks})):
            self.assertEqual([x['uuid'] for x in m.usb_devices()],['safe-1234'])
        disks.append({'path':'/dev/sdd','tran':'usb','mountpoints':[],'type':'disk','fstype':'ext4','uuid':'safe-1234'})
        with patch.object(m,'command',return_value=json.dumps({'blockdevices':disks})):
            self.assertEqual(m.usb_devices(),[])

    def test_usb_filesystem_uuid_and_no_journal_replay(self):
        rawstat=os.stat
        def osstat(path,*args,**kw):
            if str(path)=='/dev/sdz1':return SimpleNamespace(st_mode=stat.S_IFBLK)
            return rawstat(path,*args,**kw)
        with patch.object(m,'usb_devices',return_value=[dict(path='/dev/sdz1',uuid='safe-1234',fstype='ext4')]),patch.object(m.os,'stat',side_effect=osstat),patch.object(m,'command',side_effect=['',self.observed(fstype='ext4',uuid='safe-1234')]) as c:
            m.execute_mount(None,dict(kind='usb',uuid='safe-1234'),self.key,self.owner)
        self.assertIn('ro,nosuid,nodev,noexec,noload',c.call_args_list[0].args[0])

    def test_smb_secret_is_transient_and_not_a_process_argument(self):
        with tempfile.TemporaryDirectory(dir=self.root) as folder:
            secretroot=Path(folder)
            original=Path.lstat
            def lstat(path,*args,**kw):
                if path==secretroot:return SimpleNamespace(st_mode=stat.S_IFDIR|0o700,st_uid=0)
                return original(path,*args,**kw)
            password="secret $() ; quoted' password"
            data=dict(kind='smb',server='192.168.1.120',share='backup',username='reader',password=password,domain='',version='3.1.1')
            m.validate(data,self.networks)
            with patch.object(m,'SECRETS',secretroot),patch.object(Path,'lstat',lstat):
                def command(args,*a):
                    if 'mount'==Path(args[0]).name:
                        self.assertNotIn(password,' '.join(args));self.assertNotIn('reader',' '.join(args))
                        files=list(secretroot.iterdir());self.assertEqual(len(files),1)
                        self.assertIn('password='+password,files[0].read_text());self.assertEqual(files[0].stat().st_mode&0o777,0o600)
                        return ''
                    return self.observed(fstype='cifs')
                with patch.object(m,'command',side_effect=command):m.execute_mount(None,data,self.key,self.owner)
            self.assertEqual(list(secretroot.iterdir()),[])
            with self.assertRaises(SafetyError):m.validate({**data,'password':'a\nusername=root'},self.networks)
            with self.assertRaises(SafetyError):m.validate({**data,'version':'1.0'},self.networks)

    def test_failed_smb_mount_also_removes_secret(self):
        data=dict(kind='smb',server='192.168.1.120',share='backup',username='reader',password='SECRET',domain='',version='3.0')
        secretroot=self.root/'secrets';secretroot.mkdir(mode=0o700)
        original=Path.lstat
        def lstat(path,*a,**kw):
            if path==secretroot:return SimpleNamespace(st_mode=stat.S_IFDIR|0o700,st_uid=0)
            return original(path,*a,**kw)
        with patch.object(m,'SECRETS',secretroot),patch.object(Path,'lstat',lstat),patch.object(m,'command',side_effect=SafetyError('denied')):
            with self.assertRaises(SafetyError):m.execute_mount(None,data,self.key,self.owner)
        self.assertEqual(list(secretroot.iterdir()),[])


class MountBridge(TestCase):
    def setUp(self):
        from tests.test_source_plans import SourcePlans
        SourcePlans.setUp(self)
        from dataclasses import replace
        self.config=replace(self.config,source_mounting=True)
        self.owner=SimpleNamespace(pw_uid=os.getuid(),pw_gid=os.getgid())
        self.registry=self.root/'registry';self.registry.mkdir()
        self.user=str(uuid.uuid4())
        with self.control.connect() as db:
            db.execute("INSERT INTO users VALUES(?,?,?,?,?,?,?,?,?)",(self.user,'admin','hash','admin',1,'de','disabled',0,0))
        self.data=dict(kind='smb',server='192.168.1.120',share='backup',username='reader',password='SECRET-NOT-LOGGED',domain='',version='3.0')
        for name,value in [('unit_active',lambda:True),('policy',lambda:{'allowed_networks':['192.168.1.0/24']}),('REGISTRY',self.registry)]:
            p=patch.object(m,name,value);p.start();self.addCleanup(p.stop)

    def process(self,execute):
        @contextmanager
        def unlocked(*args):yield
        with patch.object(m.os,'geteuid',return_value=0),patch.object(m.pwd,'getpwnam',return_value=self.owner),patch.object(m,'_shared_io_lock',unlocked),patch.object(m,'execute_mount',execute),patch.object(m,'publish') as publish:
            m.process(self.config)
        return publish

    def test_transient_secret_is_not_in_control_and_is_consumed(self):
        r=m.request(self.config,self.control,self.data,self.user)
        f=self.config.state/'source-mount-requests'/(r['id']+'.json')
        self.assertEqual(f.stat().st_mode&0o777,0o600)
        with self.control.connect() as db:
            self.assertEqual(db.execute('select count(*) from commands').fetchone()[0],0)
            self.assertNotIn('SECRET-NOT-LOGGED',str(db.execute('select * from settings').fetchall()))
        pub=self.process(lambda *a:{'id':r['id'],'state':'MOUNTED','target':'/mnt/otam-sources/'+r['id']})
        self.assertFalse(f.exists());self.assertNotIn('SECRET-NOT-LOGGED',str(pub.call_args_list))

    def test_expired_or_nonadmin_request_never_mounts(self):
        from unittest.mock import Mock
        r=m.request(self.config,self.control,self.data,self.user)
        with self.control.connect() as db:db.execute("UPDATE users SET role='viewer'")
        execute=Mock();pub=self.process(execute);execute.assert_not_called()
        self.assertEqual(pub.call_args.args[1]['state'],'FAILED')

    def test_root_result_prevents_replay(self):
        from unittest.mock import Mock
        r=m.request(self.config,self.control,self.data,self.user)
        (self.registry/(r['id']+'.json')).write_text('{"state":"FAILED"}')
        execute=Mock();self.process(execute);execute.assert_not_called()

    def test_queued_job_blocks_mount_request(self):
        self.control.enqueue('sync',{},'mount-test-queued-sync')
        with self.assertRaises(SafetyError):m.request(self.config,self.control,self.data,self.user)


class SourcePermissionContext(TestCase):
    def test_permission_error_identifies_full_source_path(self):
        from otam.archive import source_fd
        with tempfile.TemporaryDirectory(dir=os.environ.get('OTAM_TEST_TMPDIR')) as d:
            root=Path(d);real=os.open
            def opening(path,*args,**kwargs):
                if path=='hints.1679':raise PermissionError(13,'Permission denied',path)
                return real(path,*args,**kwargs)
            with patch('otam.archive.os.open',side_effect=opening):
                with self.assertRaises(PermissionError) as result:source_fd(root,'hints.1679')
            self.assertEqual(result.exception.filename,str(root/'hints.1679'))
            self.assertIn('OTAM-Dienstkonto',str(result.exception))
