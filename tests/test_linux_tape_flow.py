"""Exercise the physical adapter and service together against inert OS files.

No device node or mt/mbuffer process is opened. Hardware acceptance stays separate.
"""
import io
import os
import json
import uuid
import tempfile
from contextlib import ExitStack, contextmanager
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from otam.catalog import Catalog
from otam.service import ArchiveService
from otam.tape import LinuxTape


class FileST:
    def __init__(self, root, expected):
        self.root, self.expected = root, expected
        self.device = expected["device"]
        self.files = []
        self.position = 0
        self.eod = False
        self.reads = []

    @contextmanager
    def locked(self):
        yield

    def check(self):
        pass

    def mt(self, operation, *args):
        assert operation in ("setblk", "compression")

    def move(self, args, **kwargs):
        operation = args[3]
        self.eod = operation == "eod"
        self.position = (len(self.files) if self.eod else
                         self.position + int(args[4]) if operation == "fsf" else 0)
        return b""

    def status(self, device):
        return {"file_number": self.position,
                "block_number": -1 if self.eod else 0,
                "bot": self.position == 0, "eod": self.eod,
                "write_protected": False}

    def writer(self):
        assert self.eod or self.position == 0
        self.files = self.files[:self.position]
        path = self.root / f"tape-file-{self.position}.tar"
        self.files.append(path)
        self.position += 1
        self.eod = False
        return os.open(path, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)

    def reader(self):
        self.reads.append(self.position)
        return os.open(self.files[self.position], os.O_RDONLY)


class LocalProducer:
    def __init__(self, command, **kwargs):
        fd = int(command[-1].rsplit("/", 1)[1])
        self.stdout = io.BytesIO(os.pread(fd, os.fstat(fd).st_size, 0))

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.stdout.close()

    def wait(self, **kwargs):
        return 0

    def poll(self):
        return 0


class PhysicalServiceFlow(TestCase):
    def test_explicit_initialization_acceptance_harness_is_header_only(self):
        from dataclasses import asdict
        from otam.web.config import WebConfig
        from otam.web.control import Control
        from tools.tape_initialization_acceptance import main
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            config = WebConfig(str(uuid.uuid4()), "test", "archive", root / "state", root / "catalog.sqlite",
                               root / "staging", root / "simulator", root / "restore",
                               "pbkdf2_sha256$600000$salt$digest", physical_maintenance=True)
            config_file = root / "node.json"
            config_file.write_text(json.dumps(asdict(config), default=str))
            original = config_file.read_bytes()
            Control(config.state).set("operation_mode", "physical")
            drive = {"id": "drive-id", "serial": "DRIVE", "medium_serial": "NEW", "ready": True,
                     "device": "/dev/nst0", "vendor": "IBM", "model": "ULT3580-HH4",
                     "status": {"online": True, "density_code": 0x46}}
            device = FileST(root, drive)
            with ExitStack() as stack:
                stack.enter_context(patch("otam.physical.LinuxMaintenance", return_value=device))
                stack.enter_context(patch("otam.physical.run", side_effect=device.move))
                stack.enter_context(patch("otam.physical.status", side_effect=device.status))
                stack.enter_context(patch.object(LinuxTape, "_driver_mode"))
                for name in ("tools.tape_initialization_acceptance.discover_drives", "otam.web.initialization.discover_drives"):
                    stack.enter_context(patch(name, return_value=[drive]))
                stack.enter_context(patch("sys.argv", ["acceptance", "--config", str(config_file),
                    "--report-root", str(root / "report"), "--drive-serial", "DRIVE", "--medium-serial", "NEW",
                    "--confirm", "INITIALIZE DRIVE NEW"]))
                main()
            report = json.loads((root / "report" / "report.json").read_text())
            self.assertEqual(report["state"], "VERIFIED")
            self.assertEqual(report["header_reads"], [0])
            self.assertEqual(len(device.files), 1)
            self.assertTrue(report["archive_prefix_unchanged"])
            self.assertEqual(config_file.read_bytes(), original)
            catalog = Catalog(config.catalog)
            try:
                self.assertEqual(catalog.db.execute("SELECT count(*) FROM archives").fetchone()[0], 0)
                self.assertEqual(catalog.db.execute("SELECT count(*) FROM media").fetchone()[0], 1)
            finally:
                catalog.close()

    def test_two_physical_backends_offline_plan_and_guarded_media_exchange(self):
        from otam.common import SafetyError
        from otam.web.config import WebConfig, Resource
        from otam.web.control import Control
        from otam.web.worker import execute
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            source, staging = root / "source", root / "staging"
            source.mkdir()
            staging.mkdir()
            for name in ("one", "two"):
                (source / name).write_bytes(name.encode() * 20000)
            config = WebConfig(str(uuid.uuid4()), "test", "archive", root / "state",
                               root / "catalog.sqlite", staging, root / "media", root / "restore",
                               "pbkdf2_sha256$600000$salt$hash", sources=(Resource("source", "source", source),),
                               physical_maintenance=True, physical_archiving=True, physical_multivolume=True)
            control = Control(config.state)
            control.set("operation_mode", "physical")
            drives = [{"id": "drive-id", "serial": "drive", "medium_serial": serial, "ready": True,
                       "device": "/dev/nst0", "vendor": "IBM", "model": "ULT3580-HH4",
                       "status": {"online": True, "density_code": 0x46}} for serial in ("first", "second")]
            devices = []
            for i, drive in enumerate(drives):
                path = root / str(i)
                path.mkdir()
                devices.append(FileST(path, drive))
            current = None

            def discover():
                return [] if current is None else [drives[current]]

            def device(expected, *args, **kwargs):
                if current is None or expected["medium_serial"] != drives[current]["medium_serial"]:
                    raise AssertionError("Wrong cartridge reached the device adapter")
                return devices[current]

            storage = {"free": 10**9, "mount": str(staging), "source": "/dev/test", "device": "1:2", "type": "ext4"}
            with ExitStack() as stack:
                constructor = stack.enter_context(patch("otam.physical.LinuxMaintenance", side_effect=device))
                stack.enter_context(patch("otam.physical.run", side_effect=lambda *a, **kw: devices[current].move(*a, **kw)))
                stack.enter_context(patch("otam.physical.status", side_effect=lambda *a: devices[current].status(*a)))
                detection = stack.enter_context(patch("otam.physical.discover_drives", side_effect=discover))
                stack.enter_context(patch("otam.web.physical_archive.discover_drives", side_effect=discover))
                stack.enter_context(patch.object(LinuxTape, "_driver_mode"))
                for name in ("otam.storage.require_local", "otam.staging.require_local",
                             "otam.web.resources.require_local", "otam.web.physical_archive.require_local"):
                    stack.enter_context(patch(name, return_value=storage))
                stack.enter_context(patch("otam.service.require_qualification"))
                stack.enter_context(patch("otam.benchmark.available_memory", return_value=8 * 1024**3))
                producer = stack.enter_context(patch("subprocess.Popen", side_effect=LocalProducer))
                media = []
                for current in range(2):
                    tape = LinuxTape(drives[current], config.state)
                    with tape.locked():
                        tape.initialize("TEST " + str(current), 125000, "rotation",
                                        "INITIALIZE " + drives[current]["medium_serial"])
                    media.append(execute(config, control, "register-physical", {
                        "drive_id": "drive-id", "drive_serial": "drive",
                        "medium_serial": drives[current]["medium_serial"]})["media_id"])
                control.set("transfer_settings:default-staging", {
                    "drive_id": "drive-id", "drive_serial": "drive", "profile_id": "ibm-ult3580-hh4-lto4",
                    "medium_density_code": 0x46, "write_rate_bytes_per_second": 120_000_000,
                    "buffer_bytes": 2368 * 1024**2,
                    "storage": {k: storage[k] for k in ("mount", "source", "device", "type")}})
                current = None
                before = (constructor.call_count, detection.call_count)
                plan = execute(config, control, "plan", {"media_ids": media, "source_id": "source",
                                                        "target": 70000, "verify_mode": "media"})
                self.assertEqual((constructor.call_count, detection.call_count), before)
                self.assertEqual(plan["media_ids"], media)
                catalog = Catalog(config.catalog)
                try:
                    parent = json.loads(catalog.db.execute("SELECT plan_json FROM jobs WHERE id=?", (plan["job_id"],)).fetchone()[0])
                finally:
                    catalog.close()
                staged = execute(config, control, "stage", {"job_id": parent["children"][0]["job_id"]})
                self.assertEqual(staged["state"], "STAGED")
                self.assertEqual((constructor.call_count, detection.call_count), before)
                payload = {"job_id": plan["job_id"], "confirm": plan["job_id"], "plan_hash": plan["sha256"]}
                with self.assertRaises(SafetyError):
                    execute(config, control, "backup-set", {**payload, "media_id": media[0]})
                current = 1
                with self.assertRaises(SafetyError):
                    execute(config, control, "backup-set", {**payload, "media_id": media[1]})
                self.assertEqual([len(d.files) for d in devices], [1, 1])
                current = 0
                first = execute(config, control, "backup-set", {**payload, "media_id": media[0]})
                self.assertEqual((first["state"], first["next_media_id"]), ("WAITING_MEDIA", media[1]))
                with self.assertRaises(SafetyError):
                    execute(config, control, "backup-set", {**payload, "media_id": media[1]})
                self.assertEqual([len(d.files) for d in devices], [3, 1])
                current = 1
                self.assertEqual(execute(config, control, "backup-set", {**payload, "media_id": media[1]})["state"], "VERIFIED")
                self.assertEqual([len(d.files) for d in devices], [3, 3])
                catalog = Catalog(config.catalog)
                try:
                    with catalog.db:
                        catalog.db.execute("UPDATE jobs SET state='INTERRUPTED' WHERE id=?", (plan["job_id"],))
                finally:
                    catalog.close()
                old_reads = [p for p in devices[1].reads if p % 2]
                self.assertEqual(execute(config, control, "backup-set", {**payload, "media_id": media[1]})["state"], "VERIFIED")
                self.assertEqual([p for p in devices[1].reads if p % 2], old_reads)
                self.assertEqual([len(d.files) for d in devices], [3, 3])
                for current in range(2):
                    restored = execute(config, control, "restore", {"media_id": media[current], "target_name": "restore-" + str(current)})
                    self.assertEqual(restored["state"], "VERIFIED")
                    name = ("one", "two")[current]
                    self.assertEqual((config.restore_root / ("restore-" + str(current)) / name).read_bytes(), (source / name).read_bytes())
                for call in producer.call_args_list:
                    args = call.args[0]
                    self.assertEqual(args[args.index("-R") + 1], "120000000")
                    self.assertEqual(args[args.index("-m") + 1], "2368M")

    def test_explicit_exchange_acceptance_harness_uses_live_journals_and_small_real_plans(self):
        from dataclasses import asdict
        from otam.common import SafetyError
        from tools.tape_exchange_acceptance import main
        from otam.web.config import WebConfig
        from otam.web.control import Control
        from otam.web.worker import execute
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            staging = root / 'staging'
            staging.mkdir()
            config = WebConfig(str(uuid.uuid4()), 'test', 'archive', root / 'state', root / 'catalog.sqlite',
                               staging, root / 'media', root / 'restore', 'pbkdf2_sha256$600000$salt$hash',
                               physical_maintenance=True)
            config_file = root / 'live.json'
            config_file.write_text(json.dumps(asdict(config), default=str))
            original_config = config_file.read_bytes()
            control = Control(config.state)
            control.set('operation_mode', 'physical')
            drives = [dict(id='drive-id', serial='DRIVE', medium_serial=serial, ready=True, device='/dev/nst0',
                           vendor='IBM', model='ULT3580-HH4', status={'online': True, 'density_code': 0x46})
                      for serial in ('FIRST', 'SECOND')]
            devices = []
            for i, drive in enumerate(drives):
                path = root / str(i)
                path.mkdir()
                devices.append(FileST(path, drive))
            current = 0
            storage = {'free': 10**9, 'mount': str(staging), 'source': '/dev/test', 'device': '1:2', 'type': 'ext4'}
            with ExitStack() as stack:
                stack.enter_context(patch('otam.physical.LinuxMaintenance', side_effect=lambda expected, *a, **kw: devices[current]))
                stack.enter_context(patch('otam.physical.run', side_effect=lambda *a, **kw: devices[current].move(*a, **kw)))
                stack.enter_context(patch('otam.physical.status', side_effect=lambda *a: devices[current].status(*a)))
                stack.enter_context(patch.object(LinuxTape, '_driver_mode'))
                for name in ('otam.physical.discover_drives', 'otam.web.physical_archive.discover_drives',
                             'tools.tape_exchange_acceptance.discover_drives'):
                    stack.enter_context(patch(name, side_effect=lambda: [drives[current]]))
                for name in ('otam.storage.require_local', 'otam.staging.require_local',
                             'otam.web.resources.require_local', 'otam.web.physical_archive.require_local',
                             'tools.tape_exchange_acceptance.require_local'):
                    stack.enter_context(patch(name, return_value=storage))
                stack.enter_context(patch('otam.service.require_qualification'))
                stack.enter_context(patch('otam.benchmark.available_memory', return_value=8 * 1024**3))
                stack.enter_context(patch('subprocess.Popen', side_effect=LocalProducer))
                for current in range(2):
                    tape = LinuxTape(drives[current], config.state)
                    with tape.locked():
                        tape.initialize('TEST', 800_000_000_000, 'rotation', 'INITIALIZE ' + drives[current]['medium_serial'])
                    execute(config, control, 'register-physical', {'drive_id': 'drive-id', 'drive_serial': 'DRIVE',
                                                                  'medium_serial': drives[current]['medium_serial']})
                current = 0
                report_root = root / 'exchange-report'
                base = ['acceptance', '--config', str(config_file), '--report-root', str(report_root),
                        '--drive-serial', 'DRIVE', '--first-serial', 'FIRST', '--second-serial', 'SECOND']
                with patch('sys.argv', base + ['--action', 'prepare', '--confirm', 'PREPARE DRIVE FIRST SECOND']):
                    main()
                self.assertEqual([len(d.files) for d in devices], [1, 1])
                report = json.loads((report_root / 'report.json').read_text())
                self.assertEqual(report['state'], 'READY')
                self.assertIsNone(control.get('transfer_settings:default-staging'))
                self.assertEqual(report['transfer_policy']['buffer_bytes'], 2368 * 1024**2)
                current = 1
                with patch('sys.argv', base + ['--action', 'step', '--confirm', 'APPEND DRIVE FIRST']):
                    with self.assertRaises(SafetyError):
                        main()
                self.assertEqual([len(d.files) for d in devices], [1, 1])
                self.assertEqual(json.loads((report_root / 'report.json').read_text())['state'], 'READY')
                for current in range(2):
                    with patch('sys.argv', base + ['--action', 'step', '--confirm', 'APPEND DRIVE ' + drives[current]['medium_serial']]):
                        main()
                    report = json.loads((report_root / 'report.json').read_text())
                    self.assertEqual(report['state'], 'WAITING_MEDIA' if current == 0 else 'VERIFIED')
                self.assertEqual([len(d.files) for d in devices], [3, 3])
                self.assertEqual(report['data_reads'], [{'medium_serial': serial, 'position': 1}
                                                        for serial in ('FIRST', 'FIRST', 'SECOND', 'SECOND')])
                self.assertTrue(report['archive_prefix_unchanged'])
                self.assertEqual(original_config, config_file.read_bytes())
                catalog = Catalog(config.catalog)
                try:
                    self.assertEqual(catalog.db.execute("SELECT count(*) FROM archives WHERE state='VERIFIED'").fetchone()[0], 2)
                    self.assertEqual([r[0] for r in catalog.db.execute('SELECT capacity FROM media')], [800_000_000_000] * 2)
                finally:
                    catalog.close()

    def test_regular_worker_binding_staging_transfer_and_restore(self):
        from otam.web.config import WebConfig, Resource
        from otam.web.control import Control
        from otam.web.worker import execute
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            source, staging = root / "source", root / "staging"
            source.mkdir()
            staging.mkdir()
            (source / "payload.bin").write_bytes(b"synthetic regular worker" * 1000)
            config = WebConfig(str(uuid.uuid4()), "test", "archive", root / "state",
                               root / "catalog.sqlite", staging, root / "media", root / "restore",
                               "pbkdf2_sha256$600000$salt$hash", sources=(Resource("source-1", "source", source),),
                               physical_maintenance=True, physical_archiving=True, physical_initialization=True)
            control = Control(config.state)
            control.set("operation_mode", "physical")
            drive = {"id": "test", "serial": "drive", "medium_serial": "cartridge", "ready": True,
                     "device": "/dev/nst0", "vendor": "IBM", "model": "ULT3580-HH4",
                     "status": {"online": True, "density_code": 0x46}}
            device = FileST(root, drive)
            storage = {"free": 10**9, "mount": str(staging), "source": "/dev/test",
                       "device": "1:2", "type": "ext4"}
            with ExitStack() as stack:
                stack.enter_context(patch("otam.physical.LinuxMaintenance", return_value=device))
                stack.enter_context(patch("otam.physical.run", side_effect=device.move))
                stack.enter_context(patch("otam.physical.status", side_effect=device.status))
                stack.enter_context(patch("otam.physical.discover_drives", return_value=[drive]))
                stack.enter_context(patch("otam.web.physical_archive.discover_drives", return_value=[drive]))
                stack.enter_context(patch("otam.web.initialization.discover_drives", return_value=[drive]))
                stack.enter_context(patch.object(LinuxTape, "_driver_mode"))
                for name in ("otam.storage.require_local", "otam.staging.require_local",
                             "otam.web.resources.require_local", "otam.web.physical_archive.require_local"):
                    stack.enter_context(patch(name, return_value=storage))
                stack.enter_context(patch("otam.service.require_qualification"))
                stack.enter_context(patch("otam.benchmark.available_memory", return_value=8 * 1024**3))
                producer = stack.enter_context(patch("subprocess.Popen", side_effect=LocalProducer))
                from otam.web import initialization
                import time
                control.set("hardware_inventory", {"time": time.time(), "drives": [drive]})
                grant = initialization.prepare(config, control, {
                    "drive_id": "test", "drive_serial": "drive", "medium_serial": "cartridge",
                    "label": "Reviewed physical test", "media_class": "rotation"})
                initialized = execute(config, control, "initialize-physical", {
                    "approval_id": grant["id"], "confirmation": grant["confirmation"], "destructive_confirmed": True})
                self.assertEqual(initialized["state"], "INITIALIZED")
                registered = execute(config, control, "register-physical", {
                    "drive_id": "test", "drive_serial": "drive", "medium_serial": "cartridge"})
                media = registered["media_id"]
                self.assertEqual(len(device.files), 1)
                control.set("transfer_settings:default-staging", {
                    "drive_id": "test", "drive_serial": "drive", "profile_id": "ibm-ult3580-hh4-lto4",
                    "medium_density_code": 0x46, "write_rate_bytes_per_second": 120_000_000,
                    "buffer_bytes": 2368 * 1024**2,
                    "storage": {k: storage[k] for k in ("mount", "source", "device", "type")}})
                plan = execute(config, control, "plan", {"media_id": media, "source_id": "source-1",
                                                        "staging_id": "default-staging", "verify_mode": "media"})
                stale = execute(config, control, "plan", {"media_id": media, "source_id": "source-1"})
                # Staging is local and remains possible without an inserted tape.
                control.set("hardware_inventory", {"time": 0, "drives": []})
                self.assertEqual(execute(config, control, "stage", {"job_id": plan["job_id"]})["state"], "STAGED")
                backup = execute(config, control, "backup", {"job_id": plan["job_id"],
                                 "confirm": plan["job_id"], "plan_hash": plan["sha256"]})
                self.assertEqual(backup["state"], "VERIFIED")
                from otam.common import SafetyError
                count = producer.call_count
                with self.assertRaisesRegex(SafetyError, "changed since planning"):
                    execute(config, control, "backup", {"job_id": stale["job_id"],
                            "confirm": stale["job_id"], "plan_hash": stale["sha256"]})
                self.assertEqual(producer.call_count, count)
                self.assertEqual(len(device.files), 3)
                command = producer.call_args_list[-1].args[0]
                self.assertEqual(command[command.index("-R") + 1], "120000000")
                self.assertEqual(command[command.index("-m") + 1], "2368M")
                restored = execute(config, control, "restore", {"media_id": media, "target_name": "selected"})
                self.assertEqual(restored["state"], "VERIFIED")
                self.assertEqual((config.restore_root / "selected" / "payload.bin").read_bytes(),
                                 (source / "payload.bin").read_bytes())
                catalog = Catalog(config.catalog)
                try:
                    event = catalog.db.execute("SELECT details_json FROM events WHERE event='transfer_policy_selected'").fetchone()
                    self.assertEqual(json.loads(event[0])["buffer_bytes"], 2368 * 1024**2)
                finally:
                    catalog.close()

    def test_archive_and_deferred_modes_restore_and_rebuild_after_restart(self):
        for verification in ("archive", "media"):
            with self.subTest(verification=verification), tempfile.TemporaryDirectory() as folder:
                root = Path(folder).resolve()
                source, spool = root / "source", root / "staging"
                source.mkdir()
                spool.mkdir()
                payloads = {"one.bin": b"one" * 10000, "two.bin": b"two" * 10000}
                for name, data in payloads.items():
                    (source / name).write_bytes(data)
                expected = {"id": "test", "device": "/dev/nst0",
                            "serial": "drive", "medium_serial": "cartridge"}
                device = FileST(root, expected)
                with ExitStack() as stack:
                    stack.enter_context(patch("otam.physical.LinuxMaintenance", return_value=device))
                    stack.enter_context(patch("otam.physical.run", side_effect=device.move))
                    stack.enter_context(patch("otam.physical.status", side_effect=device.status))
                    stack.enter_context(patch.object(LinuxTape, "_driver_mode"))
                    stack.enter_context(patch("otam.storage.require_local", return_value={"free": 10**9}))
                    stack.enter_context(patch("otam.staging.require_local", return_value={"free": 10**9}))
                    stack.enter_context(patch("otam.service.require_qualification"))
                    stack.enter_context(patch("otam.benchmark.available_memory", return_value=8 * 1024**3))
                    stack.enter_context(patch("subprocess.Popen", LocalProducer))
                    tape = LinuxTape(expected, root / "state")
                    with tape.locked():
                        header = tape.initialize("Test", 10**9, "rotation", "INITIALIZE cartridge")
                    catalog = Catalog(root / "catalog.sqlite")
                    stack.callback(catalog.close)
                    service = ArchiveService(catalog, tape)
                    service.register()
                    plan = service.plan(source, header["media_id"], 50000,
                                        verify_mode=verification)
                    self.assertEqual(len(plan["archives"]), 2)
                    result = service.backup(plan["job_id"], plan["job_id"], spool)
                    self.assertEqual(result["state"], "VERIFIED")
                    self.assertEqual(len(device.files), 5)
                    device.reads.clear()
                    second = service.plan(source, header["media_id"], 50000, verify_mode=verification)
                    self.assertFalse({1, 3} & set(device.reads))
                    device.reads.clear()
                    repeated = service.backup(second["job_id"], second["job_id"], spool)
                    self.assertEqual(repeated["state"], "VERIFIED")
                    self.assertFalse({1, 3} & set(device.reads))
                    self.assertEqual([p for p in device.reads if p % 2], [5, 7])
                    # A fresh adapter and a completely empty catalog must recover
                    # the format and every payload from the medium alone.
                    recovered = Catalog(root / "recovered.sqlite")
                    stack.callback(recovered.close)
                    fresh = ArchiveService(recovered, LinuxTape(expected, root / "state"))
                    rebuilt = fresh.rebuild(header["media_id"])
                    self.assertEqual(rebuilt["archives"], 4)
                    restored_count = 0
                    for archive in result["archives"]:
                        restored_count += fresh.restore(header["media_id"], root / "restored",
                                                        archive_id=archive)["files"]
                    self.assertEqual(restored_count, 2)
                    for name, data in payloads.items():
                        self.assertEqual((root / "restored" / name).read_bytes(), data)
