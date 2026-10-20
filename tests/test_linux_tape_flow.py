"""Exercise the physical adapter and service together against inert OS files.

No device node or mt/mbuffer process is opened. Hardware acceptance stays separate.
"""
import io
import os
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
                         int(args[4]) if operation == "fsf" else 0)
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
                    # A fresh adapter and a completely empty catalog must recover
                    # the format and every payload from the medium alone.
                    recovered = Catalog(root / "recovered.sqlite")
                    stack.callback(recovered.close)
                    fresh = ArchiveService(recovered, LinuxTape(expected, root / "state"))
                    rebuilt = fresh.rebuild(header["media_id"])
                    self.assertEqual(rebuilt["archives"], 2)
                    report = fresh.restore(header["media_id"], root / "restored")
                    self.assertEqual(report["files"], 2)
                    for name, data in payloads.items():
                        self.assertEqual((root / "restored" / name).read_bytes(), data)
