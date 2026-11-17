"""Rolling generations are independent; retention never authorizes a blind write."""
import json
import sqlite3
from unittest import TestCase
from unittest.mock import patch
from tests import test_source_plans
from otam.catalog import Catalog
from otam.common import SafetyError
from otam import rotation as model, source_capture
from otam.web import rotation
from otam.web.worker import execute, run_once


class Rotation(TestCase):
    setUp = test_source_plans.SourcePlans.setUp
    medium = test_source_plans.SourcePlans.medium

    def create_policy(self, count=1, keep=0):
        c = Catalog(self.config.catalog)
        try:
            opts = dict(name='Borg', source_id='src', staging_id='default-staging', set_count=count,
                        keep_during_update=keep, retain_days=0, target=60000, excluded_paths=[])
            self.options = opts
            self.policy = model.policy(c, opts)['id']
            self.sets = [r[0] for r in c.db.execute('SELECT id FROM tape_sets WHERE policy_id=? ORDER BY created', (self.policy,))]
            return self.policy
        finally:c.close()

    def add(self, index=0):
        m = self.medium('medium')
        c = Catalog(self.config.catalog)
        try:model.add_member(c, self.sets[index], m, 'simulator')
        finally:c.close()
        return m

    def prepare(self, index=0):
        result = execute(self.config, self.control, 'plan-rotation',
                         dict(policy_id=self.policy, set_id=self.sets[index], consistent_source=True))
        return result['generation_id']

    def bind(self, g):
        return execute(self.config, self.control, 'bind-rotation', dict(generation_id=g))

    def complete(self, result):
        c=Catalog(self.config.catalog)
        try:
            j=c.db.execute('SELECT kind,plan_json FROM jobs WHERE id=?',(result['job_id'],)).fetchone()
            plan=json.loads(j['plan_json'])
        finally:c.close()
        if j['kind']=='archive-set':
            for child in plan['children']:
                execute(self.config,self.control,'backup-set',dict(job_id=result['job_id'],confirm=result['job_id'],plan_hash=result['sha256'],media_id=child['media_id']))
        else:
            execute(self.config,self.control,'backup',dict(job_id=result['job_id'],confirm=result['job_id'],plan_hash=result['sha256']))
        c=Catalog(self.config.catalog)
        try:model.reconcile(c)
        finally:c.close()

    def recycled(self, g, m):
        grant=rotation.review(self.config,self.control,dict(generation_id=g,media_id=m))
        return execute(self.config,self.control,'recycle-rotation',dict(approval_id=grant['id'],confirmation=grant['confirmation'],destructive_confirmed=True))

    def test_deleted_policy_preserves_verified_data_bindings_and_restore(self):
        self.create_policy();self.add();self.add()
        g=self.prepare();self.complete(self.bind(g))
        c=Catalog(self.config.catalog)
        try:
            before={t:[tuple(r) for r in c.db.execute('SELECT * FROM '+t)] for t in ('archives','files','media','tape_set_members','backup_generations','generation_volumes')}
            model.delete_policy(c,self.policy,self.policy)
            self.assertEqual(model.listing(c),[])
            self.assertEqual(model.listing(c,deleted=True)[0]['generations'][0]['state'],'VERIFIED')
            for t,rows in before.items():self.assertEqual([tuple(r) for r in c.db.execute('SELECT * FROM '+t)],rows)
            with self.assertRaises(SafetyError):model.policy(c,self.options,self.policy)
            with self.assertRaises(SafetyError):model.add_member(c,self.sets[0],self.medium('extra'),'simulator')
        finally:c.close()
        with self.assertRaises(SafetyError):self.prepare()
        first=execute(self.config,self.control,'restore-rotation',dict(generation_id=g,target_name='deleted-policy-restore'))
        last=execute(self.config,self.control,'restore-rotation',dict(restore_job=first['restore_job']))
        self.assertEqual(last['state'],'VERIFIED')
        self.assertEqual((self.config.restore_root/'deleted-policy-restore/one').read_bytes(),(self.root/'source/one').read_bytes())
        c=Catalog(self.config.catalog)
        try:
            model.delete_policy(c,self.policy,self.policy,restore=True)
            self.assertEqual(len(model.listing(c)),1)
            self.assertNotIn('deleted_at',model.listing(c)[0]['options'])
        finally:c.close()

    def test_policy_delete_guards_active_generation_and_uncertain_recycle(self):
        self.create_policy();m=self.add()
        c=Catalog(self.config.catalog)
        try:
            with self.assertRaises(SafetyError):model.delete_policy(c,self.policy,'wrong')
            g=model.ident()
            with c.db:c.db.execute('INSERT INTO backup_generations VALUES(?,?,?,?,NULL,NULL,?,?,NULL)',(g,self.policy,self.sets[0],'PREPARING','{}',1))
            with self.assertRaises(SafetyError):model.delete_policy(c,self.policy,self.policy)
            model.update_generation(c,g,'FAILED')
            for state in ('CONSUMED','WRITING','INTERRUPTED'):
                with c.db:
                    c.db.execute('DELETE FROM recycle_intents')
                    c.db.execute('INSERT INTO recycle_intents VALUES(?,?,?,?,?,?,NULL)',(model.ident(),g,m,state,'{}',1))
                with self.assertRaises(SafetyError):model.delete_policy(c,self.policy,self.policy)
            self.assertNotIn('deleted_at',json.loads(model.row(c,'backup_policies',self.policy)['options_json']))
        finally:c.close()

    def test_policy_delete_is_atomic_and_idempotent(self):
        self.create_policy();c=Catalog(self.config.catalog)
        try:
            with c.db:c.db.execute("CREATE TRIGGER reject_policy_event BEFORE INSERT ON events WHEN NEW.event='rotation_policy_deleted' BEGIN SELECT RAISE(ABORT,'test rollback'); END")
            with self.assertRaises(sqlite3.IntegrityError):model.delete_policy(c,self.policy,self.policy)
            self.assertNotIn('deleted_at',json.loads(model.row(c,'backup_policies',self.policy)['options_json']))
            with c.db:c.db.execute('DROP TRIGGER reject_policy_event')
            model.delete_policy(c,self.policy,self.policy);options=model.row(c,'backup_policies',self.policy)['options_json']
            model.delete_policy(c,self.policy,self.policy)
            self.assertEqual(model.row(c,'backup_policies',self.policy)['options_json'],options)
        finally:c.close()

    def test_capacity_then_extend_restore_whole_set_and_keep_capture(self):
        self.create_policy(); self.add()
        g=self.prepare()
        self.assertEqual(self.bind(g)['state'],'WAITING_CAPACITY')
        self.add()
        bound=self.bind(g);self.assertEqual(bound['state'],'PLANNED');self.complete(bound)
        c=Catalog(self.config.catalog)
        try:
            generation=model.row(c,'backup_generations',g)
            self.assertEqual(generation['state'],'VERIFIED')
            self.assertTrue(source_capture.location(self.config.staging,generation['source_job']).exists())
            for a in c.db.execute('SELECT manifest_json FROM archives'):
                self.assertEqual(json.loads(a[0])['rotation']['generation_id'],g)
        finally:c.close()
        first=execute(self.config,self.control,'restore-rotation',dict(generation_id=g,target_name='repository'))
        self.assertEqual(first['state'],'WAITING_MEDIA');self.assertFalse((self.config.restore_root/'repository').exists())
        last=execute(self.config,self.control,'restore-rotation',dict(restore_job=first['restore_job']))
        self.assertEqual(last['state'],'VERIFIED')
        for name in ('one','two'):
            self.assertEqual((self.config.restore_root/'repository'/name).read_bytes(),(self.root/'source'/name).read_bytes())

    def test_one_set_recycle_new_identity_and_preserve_history(self):
        self.create_policy();one=self.add();two=self.add();g=self.prepare();self.complete(self.bind(g))
        (self.root/'source/one').write_bytes(b'changed'*4000)
        next_g=self.prepare();result=self.bind(next_g);self.assertEqual(result['state'],'WAITING_APPROVAL')
        out=self.recycled(next_g,one);self.assertNotEqual(out['media_id'],one)
        with self.assertRaises(SafetyError):self.recycled(next_g,one)
        self.recycled(next_g,two)
        new=self.bind(next_g);self.complete(new)
        c=Catalog(self.config.catalog)
        try:
            self.assertEqual(model.row(c,'backup_generations',g)['state'],'UNAVAILABLE')
            self.assertEqual(model.row(c,'backup_generations',next_g)['state'],'VERIFIED')
            self.assertEqual(model.row(c,'media',one)['state'],'RETIRED')
            self.assertEqual(c.db.execute('SELECT count(*) FROM archives WHERE media_id=?',(one,)).fetchone()[0],1)
        finally:c.close()

    def test_foreign_archives_cannot_be_recycled_by_membership(self):
        self.create_policy();one=self.add();self.add();g=self.prepare();self.complete(self.bind(g));ng=self.prepare();self.bind(ng)
        c=Catalog(self.config.catalog)
        try:
            with c.db:c.db.execute('UPDATE archives SET job_id=NULL WHERE media_id=?',(one,))
            with self.assertRaisesRegex(SafetyError,'fremde'):model.recycle_eligibility(c,ng,one)
        finally:c.close()

    def test_expansion_one_to_three_does_not_change_old_generations(self):
        self.create_policy();self.add();self.add();g=self.prepare();self.complete(self.bind(g))
        c=Catalog(self.config.catalog)
        try:
            old=[tuple(x) for x in c.db.execute('SELECT * FROM generation_volumes')]
            model.policy(c,{**self.options,'set_count':3,'keep_during_update':1},self.policy)
            self.assertEqual(c.db.execute('SELECT count(*) FROM tape_sets').fetchone()[0],3)
            self.assertEqual([tuple(x) for x in c.db.execute('SELECT * FROM generation_volumes')],old)
            with self.assertRaises(SafetyError):model.policy(c,{**self.options,'set_count':1},self.policy)
        finally:c.close()

    def test_retention_and_minimum_survivors(self):
        self.create_policy(count=2,keep=1);a=self.add();self.add();g=self.prepare();self.complete(self.bind(g))
        ng=self.prepare();self.bind(ng)
        with self.assertRaisesRegex(SafetyError,'Zu wenige'):self.recycled(ng,a)
        c=Catalog(self.config.catalog)
        try:
            with c.db:
                opts={k:v for k,v in self.options.items() if k!='name'};opts.update(keep_during_update=0,retain_days=30)
                c.db.execute('UPDATE backup_policies SET options_json=?',(json.dumps(opts),))
            with self.assertRaisesRegex(SafetyError,'Schutzfrist'):model.recycle_eligibility(c,ng,a)
        finally:c.close()

    def test_no_duplicate_member_or_active_generation(self):
        self.create_policy(count=2);one=self.add()
        c=Catalog(self.config.catalog)
        try:
            with self.assertRaises(SafetyError):model.add_member(c,self.sets[1],one,'simulator')
        finally:c.close()
        self.prepare()
        with self.assertRaises(SafetyError):self.prepare(1)

    def test_consistent_source_confirmation_and_full_mode_required(self):
        self.create_policy()
        with self.assertRaises(SafetyError):execute(self.config,self.control,'plan-rotation',dict(policy_id=self.policy,set_id=self.sets[0],consistent_source=False))
        g=self.prepare();c=Catalog(self.config.catalog)
        try:
            generation=model.row(c,'backup_generations',g)
            _,draft=rotation.source_plans.load(c,generation['source_job'])
            self.assertIsNotNone(draft.get('source_capture'))
            self.assertNotEqual(draft.get('backup_mode'),'additive')
        finally:c.close()

    def test_legacy_generation_plan_and_hash_survive_new_code(self):
        self.create_policy();self.add();self.add()
        with patch('otam.packed_capture.prepare',side_effect=source_capture.prepare):
            g=self.prepare()
        bound=self.bind(g)
        c=Catalog(self.config.catalog)
        try:before=c.db.execute('select plan_json from jobs where id=?',(bound['job_id'],)).fetchone()[0]
        finally:c.close()
        self.complete(bound)
        c=Catalog(self.config.catalog)
        try:
            self.assertEqual(c.db.execute('select plan_json from jobs where id=?',(bound['job_id'],)).fetchone()[0],before)
            self.assertEqual(model.row(c,'backup_generations',g)['state'],'VERIFIED')
        finally:c.close()

    def test_packed_generation_retains_all_tars_until_explicit_verified_cleanup(self):
        self.create_policy();self.add();self.add();g=self.prepare();bound=self.bind(g)
        before=list(self.config.staging.rglob('ready.tar'));self.assertTrue(before)
        with self.assertRaises(SafetyError):
            execute(self.config,self.control,'cleanup-rotation',dict(generation_id=g))
        self.complete(bound)
        self.assertTrue(all(p.exists() for p in before))
        self.assertEqual(execute(self.config,self.control,'cleanup-rotation',dict(generation_id=g))['state'],'SUCCEEDED')
        self.assertTrue(all(not p.exists() for p in before))
        self.assertEqual(execute(self.config,self.control,'cleanup-rotation',dict(generation_id=g))['state'],'UNCHANGED')

    def test_capture_changed_blocks_destructive_review(self):
        self.create_policy();one=self.add();self.add();g=self.prepare();self.complete(self.bind(g));ng=self.prepare();self.bind(ng)
        c=Catalog(self.config.catalog)
        try:
            generation=model.row(c,'backup_generations',ng)
            path=next(source_capture.location(self.config.staging,generation['source_job']).glob('*.tar'))
            path.chmod(0o600);path.write_bytes(b'invalid')
            with self.assertRaises(SafetyError):self.recycled(ng,one)
        finally:c.close()

    def test_crash_during_header_write_stays_unavailable_and_blocked(self):
        self.create_policy();one=self.add();self.add();g=self.prepare();self.complete(self.bind(g));ng=self.prepare();self.bind(ng)
        grant=rotation.review(self.config,self.control,dict(generation_id=ng,media_id=one))
        payload=dict(approval_id=grant['id'],confirmation=grant['confirmation'],destructive_confirmed=True)
        with patch('otam.web.rotation.SimulatedTape.create',side_effect=SystemExit('killed')):
            with self.assertRaises(SystemExit):execute(self.config,self.control,'recycle-rotation',payload)
        c=Catalog(self.config.catalog)
        try:
            self.assertEqual(model.row(c,'recycle_intents',grant['id'])['state'],'INTERRUPTED')
            self.assertEqual(model.row(c,'media',one)['state'],'RETIRED')
            self.assertEqual(model.row(c,'backup_generations',g)['state'],'UNAVAILABLE')
        finally:c.close()
        with self.assertRaises(SafetyError):execute(self.config,self.control,'recycle-rotation',payload)

    def test_snapshot_schema_migration_preserves_original_jobs(self):
        from otam.web.replication import validate_snapshot
        c=Catalog(self.config.catalog)
        try:
            self.assertEqual(c.db.execute('PRAGMA user_version').fetchone()[0],3)
            target=self.root/'snapshot.sqlite'
            db=sqlite3.connect(target);c.db.backup(db);db.close()
            validate_snapshot(target)
        finally:c.close()

    def test_independent_sets_never_use_global_additive_baseline(self):
        self.create_policy(count=2);self.add();self.add();self.add(1);self.add(1)
        a=self.prepare();self.complete(self.bind(a));b=self.prepare(1);self.complete(self.bind(b))
        c=Catalog(self.config.catalog)
        try:
            for key in (a,b):
                g=model.row(c,'backup_generations',key)
                volumes=[r[0] for r in c.db.execute('SELECT media_id FROM generation_volumes WHERE generation_id=?',(key,))]
                rows=[r for m in volumes for r in c.db.execute('SELECT f.path FROM files f JOIN archives a ON a.id=f.archive_id WHERE a.media_id=?',(m,))]
                self.assertEqual(sorted(r[0] for r in rows),['one','two'])
        finally:c.close()

    def test_standalone_recovery_without_catalog_and_missing_tar_refused(self):
        import importlib.util
        spec=importlib.util.spec_from_file_location('standalone',__import__('pathlib').Path(__file__).parents[1]/'tools/restore_rotation.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        self.create_policy();self.add();self.add();g=self.prepare();self.complete(self.bind(g))
        c=Catalog(self.config.catalog)
        try:
            files=[self.control.resource(r['media_id'])/f"{r['tape_file']:08d}.tar" for r in c.db.execute('SELECT * FROM archives')]
        finally:c.close()
        with self.assertRaises(ValueError):module.recover(files[:1],self.root/'incomplete')
        self.assertFalse((self.root/'incomplete').exists())
        module.recover(files,self.root/'independent')
        self.assertEqual((self.root/'independent/one').read_bytes(),(self.root/'source/one').read_bytes())
        with self.assertRaises(ValueError):module.recover(files+files[:1],self.root/'duplicate')

    def test_completed_restore_protects_only_until_finish(self):
        self.create_policy();one=self.add();self.add();g=self.prepare();self.complete(self.bind(g))
        r=execute(self.config,self.control,'restore-rotation',dict(generation_id=g,target_name='repo'))
        ng=self.prepare();self.bind(ng)
        with self.assertRaisesRegex(SafetyError,'Restore'):self.recycled(ng,one)
        execute(self.config,self.control,'restore-rotation',dict(restore_job=r['restore_job']))
        self.recycled(ng,one)

    def test_review_expires_is_one_shot_and_policy_changes_invalidate(self):
        self.create_policy();one=self.add();self.add();g=self.prepare();self.complete(self.bind(g));ng=self.prepare();self.bind(ng)
        grant=rotation.review(self.config,self.control,dict(generation_id=ng,media_id=one))
        payload=dict(approval_id=grant['id'],confirmation=grant['confirmation'],destructive_confirmed=True)
        with patch('otam.web.rotation.time.time',return_value=grant['created']+301):
            with self.assertRaises(SafetyError):execute(self.config,self.control,'recycle-rotation',payload)
        changed={**payload,'confirmation':'RECYCLE WRONG'}
        with self.assertRaises(SafetyError):execute(self.config,self.control,'recycle-rotation',changed)
        execute(self.config,self.control,'recycle-rotation',payload)
        with self.assertRaises(SafetyError):execute(self.config,self.control,'recycle-rotation',payload)

    def test_permanent_media_and_backend_mixing_refused(self):
        self.create_policy();m=execute(self.config,self.control,'create-medium',dict(label='archive',capacity=110000,media_class='permanent'))['media_id']
        c=Catalog(self.config.catalog)
        try:
            with self.assertRaises(SafetyError):model.add_member(c,self.sets[0],m,'simulator')
            other=self.medium('sim')
            with self.assertRaises(SafetyError):model.add_member(c,self.sets[0],other,'physical')
        finally:c.close()

    def test_physical_recycle_handler_with_real_linux_adapter_on_inert_files(self):
        from contextlib import ExitStack
        from dataclasses import replace
        from tests.test_linux_tape_flow import FileST, LocalProducer
        from otam.tape import LinuxTape
        self.config=replace(self.config,physical_maintenance=True,physical_archiving=True,
                            physical_initialization=True,physical_rotation=True)
        self.control.set('operation_mode','physical')
        drive={'id':'drive-id','serial':'drive','medium_serial':'TEST-MAM','ready':True,
               'device':'/dev/nst0','vendor':'IBM','model':'ULT3580-HH4',
               'status':{'online':True,'density_code':0x46}}
        self.root.joinpath('tape-files').mkdir()
        device=FileST(self.root/'tape-files',drive)
        storage={'free':10**9,'mount':str(self.root),'source':'/dev/test','device':'1:2','type':'ext4'}
        with ExitStack() as stack:
            stack.enter_context(patch('otam.physical.LinuxMaintenance',return_value=device))
            stack.enter_context(patch('otam.physical.run',side_effect=device.move))
            stack.enter_context(patch('otam.physical.status',side_effect=device.status))
            stack.enter_context(patch.object(LinuxTape,'_driver_mode'))
            for name in ('otam.physical.discover_drives','otam.web.physical_archive.discover_drives','otam.web.rotation.discover_drives'):
                stack.enter_context(patch(name,return_value=[drive]))
            for name in ('otam.storage.require_local','otam.staging.require_local','otam.source_capture.require_local','otam.packed_capture.require_local',
                         'otam.web.resources.require_local','otam.web.physical_archive.require_local'):
                stack.enter_context(patch(name,return_value=storage))
            stack.enter_context(patch('otam.service.require_qualification'))
            stack.enter_context(patch('otam.benchmark.available_memory',return_value=8*1024**3))
            stack.enter_context(patch('subprocess.Popen',side_effect=LocalProducer))
            tape=LinuxTape(drive,self.config.state)
            with tape.locked():tape.initialize('TEST',800000000000,'rotation','INITIALIZE TEST-MAM')
            medium=execute(self.config,self.control,'register-physical',dict(drive_id='drive-id',drive_serial='drive',medium_serial='TEST-MAM'))['media_id']
            self.control.set('transfer_settings:default-staging',dict(drive_id='drive-id',drive_serial='drive',
                profile_id='ibm-ult3580-hh4-lto4',medium_density_code=0x46,
                write_rate_bytes_per_second=120000000,buffer_bytes=2368*1024**2,
                storage={k:storage[k] for k in ('mount','source','device','type')}))
            from dataclasses import asdict
            from tools.tape_rotation_acceptance import main
            config_file=self.root/'node.json'
            config_file.write_text(json.dumps(asdict(self.config),default=str))
            stack.enter_context(patch('tools.tape_rotation_acceptance.discover_drives',return_value=[drive]))
            stack.enter_context(patch('sys.argv',['acceptance','--config',str(config_file),
                '--report-root',str(self.root/'hardware-report'),'--media-id',medium,
                '--drive-serial','drive','--medium-serial','TEST-MAM',
                '--confirm','ROTATION_TEST drive TEST-MAM']))
            main()
            report=json.loads((self.root/'hardware-report/report.json').read_text())
            self.assertEqual(report['state'],'VERIFIED')
            self.assertTrue(report['archive_prefix_unchanged'])
            self.assertEqual(len(report['steps']),2)
            c=Catalog(self.config.catalog)
            try:
                first=report['steps'][0]['generation_id'];second=report['steps'][1]['generation_id']
                self.assertEqual(model.row(c,'backup_generations',first)['state'],'UNAVAILABLE')
                self.assertEqual(model.row(c,'backup_generations',second)['state'],'VERIFIED')
            finally:c.close()

    def test_retired_copies_not_available_for_restore_or_default_search(self):
        from otam.web.query import CatalogView
        self.create_policy();one=self.add();self.add();g=self.prepare();self.complete(self.bind(g));ng=self.prepare();self.bind(ng)
        self.recycled(ng,one)
        for kind in ('verify','rebuild','recover'):
            with self.assertRaises(SafetyError):execute(self.config,self.control,kind,dict(media_id=one))
        c=Catalog(self.config.catalog)
        try:
            rows=[x for x in c.search() if x['media_id']==one]
            self.assertTrue(rows);self.assertEqual(rows[0]['state'],'UNAVAILABLE')
        finally:c.close()
        files=CatalogView(self.config,self.control).files()['items']
        self.assertFalse(any(x['media_id']==one for x in files))
        archives=CatalogView(self.config,self.control).archives()['items']
        self.assertTrue(any(x['media_id']==one and x['state']=='UNAVAILABLE' for x in archives))

    def test_restore_wrong_medium_is_waiting_and_verified_job_cannot_be_reopened(self):
        self.create_policy();self.add();self.add();g=self.prepare();self.complete(self.bind(g))
        with patch('otam.web.worker.mounted',side_effect=SafetyError('Wrong medium')):
            result=execute(self.config,self.control,'restore-rotation',dict(generation_id=g,target_name='waiting-repo'))
        self.assertEqual(result['state'],'WAITING_MEDIA')
        second=execute(self.config,self.control,'restore-rotation',dict(restore_job=result['restore_job']))
        self.assertEqual(second['state'],'WAITING_MEDIA')
        complete=execute(self.config,self.control,'restore-rotation',dict(restore_job=result['restore_job']))
        self.assertEqual(complete['state'],'VERIFIED')
        with self.assertRaises(SafetyError):execute(self.config,self.control,'restore-rotation',dict(restore_job=result['restore_job']))
        c=Catalog(self.config.catalog)
        try:self.assertEqual(c.db.execute('SELECT state FROM jobs WHERE id=?',(result['restore_job'],)).fetchone()[0],'VERIFIED')
        finally:c.close()

    def test_capture_cleanup_only_after_verified_generation_and_preserves_original(self):
        self.create_policy();self.add();self.add();g=self.prepare();bound=self.bind(g)
        with self.assertRaises(SafetyError):execute(self.config,self.control,'cleanup-rotation',dict(generation_id=g))
        self.complete(bound)
        self.assertEqual(execute(self.config,self.control,'cleanup-rotation',dict(generation_id=g))['state'],'SUCCEEDED')
        self.assertTrue((self.root/'source/one').exists())
        self.assertEqual(execute(self.config,self.control,'cleanup-rotation',dict(generation_id=g))['state'],'UNCHANGED')

    def test_normal_bind_and_legacy_plan_cannot_bypass_set_ownership(self):
        self.create_policy();one=self.add();self.add();g=self.prepare()
        c=Catalog(self.config.catalog)
        try:
            gen=model.row(c,'backup_generations',g)
            _,draft=rotation.source_plans.load(c,gen['source_job'])
        finally:c.close()
        with self.assertRaisesRegex(SafetyError,'Rotationsquellenplan'):
            execute(self.config,self.control,'bind-plan',dict(job_id=gen['source_job'],source_plan_hash=draft['sha256'],media_ids=[one]))
        with self.assertRaisesRegex(SafetyError,'Bandsatzmedien'):
            execute(self.config,self.control,'plan',dict(media_id=one,source_id='src'))
        ordinary=execute(self.config,self.control,'plan-source',dict(source_id='src'))
        with self.assertRaisesRegex(SafetyError,'Bandsatzmedien'):
            execute(self.config,self.control,'bind-plan',dict(job_id=ordinary['job_id'],source_plan_hash=ordinary['sha256'],media_ids=[one]))
