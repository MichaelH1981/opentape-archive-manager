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
                               physical_maintenance=True, physical_archiving=True)
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
                stack.enter_context(patch.object(LinuxTape, "_driver_mode"))
                for name in ("otam.storage.require_local", "otam.staging.require_local",
                             "otam.web.resources.require_local", "otam.web.physical_archive.require_local"):
                    stack.enter_context(patch(name, return_value=storage))
                stack.enter_context(patch("otam.service.require_qualification"))
                stack.enter_context(patch("otam.benchmark.available_memory", return_value=8 * 1024**3))
                producer = stack.enter_context(patch("subprocess.Popen", side_effect=LocalProducer))
                tape = LinuxTape(drive, config.state)
                with tape.locked():
                    tape.initialize("Existing test tape", 10**9, "rotation", "INITIALIZE cartridge")
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
