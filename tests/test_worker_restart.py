"""Durable process-death metadata recovery; no physical tape writes are claimed."""
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import asdict
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from otam.catalog import Catalog
from otam.storage import io_lock, IOBusyError
from otam.web.config import WebConfig
from otam.web.control import Control
from otam.web.worker import run_worker


class WorkerRestart(TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(dir=os.environ.get("OTAM_TEST_TMPDIR"))
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.config = WebConfig(str(uuid.uuid4()), "restart", "archive", self.root / "state",
                                self.root / "catalog.sqlite", self.root / "staging",
                                self.root / "media", self.root / "restore",
                                "pbkdf2_sha256$600000$salt$digest")
        self.catalog = Catalog(self.config.catalog)
        self.addCleanup(self.catalog.close)
        self.control = Control(self.config.state)
        self.media = str(uuid.uuid4())
        self.catalog.register({"media_id": self.media, "label": "TEST", "class": "rotation",
                               "capacity": 10**7}, 10240)
        self.job = self.catalog.job("archive", self.media, "PLANNED")
        self.artifact = self.root / "staged.tar"
        self.artifact.write_bytes(b"owned staged test data")
        self.digest = hashlib.sha256(self.artifact.read_bytes()).hexdigest()
        self.archive = str(uuid.uuid4())
        manifest = {"archive_id": self.archive, "media_id": self.media,
                    "created": time.time(), "files": []}
        self.catalog.record_archive(manifest, self.job, 3, "WRITING", 10240, self.digest)
        with self.catalog.db:
            self.catalog.db.execute("INSERT INTO staged_archives(job_id,archive_id,root,path,phase,state,"
                                    "sha256,total_bytes,progress_bytes,updated) "
                                    "VALUES(?,?,?,?,'TAPE_WRITE','RUNNING',?,10240,512,?)",
                                    (self.job, self.archive, str(self.root), str(self.artifact),
                                     self.digest, time.time()))

    def state(self, table, ident):
        return self.catalog.db.execute("SELECT state FROM " + table + " WHERE id=?", (ident,)).fetchone()[0]

    def start_interrupted_job(self):
        with self.catalog.db:
            self.catalog.db.execute("UPDATE jobs SET state='RUNNING' WHERE id=?", (self.job,))

    def test_real_process_exit_then_empty_worker_restart_preserves_data_and_refuses_success(self):
        command = self.control.enqueue("backup", {"job_id": self.job}, "crash-fixture")
        script = """
import os,sys
from pathlib import Path
from otam.catalog import Catalog
from otam.web.control import Control
c=Catalog(Path(sys.argv[1]))
with c.db:
    c.db.execute("UPDATE jobs SET state='RUNNING' WHERE id=?", (sys.argv[3],))
assert Control(Path(sys.argv[2])).claim()['id']==sys.argv[4]
os._exit(91)
"""
        dead = subprocess.run([sys.executable, "-c", script, str(self.config.catalog),
                               str(self.config.state), self.job, command["id"]], capture_output=True)
        self.assertEqual(dead.returncode, 91, dead.stderr)
        old = self.catalog.job("archive", self.media)
        self.catalog.record_archive({"archive_id": str(uuid.uuid4()), "media_id": self.media,
                                     "created": time.time(), "files": []}, old, 1, "VERIFIED", 10240, "a" * 64)
        self.catalog.finish(old, "VERIFIED")
        marker = self.config.state / "physical-pending" / "test-only.json"
        marker.parent.mkdir()
        marker.write_bytes(b"test marker; never a physical write")
        config_file = self.root / "node.json"
        config_file.write_text(json.dumps(asdict(self.config), default=str))
        restarted = subprocess.run([sys.executable, "-m", "otam", "worker", "--config", str(config_file),
                                    "--once"], capture_output=True)
        self.assertEqual(restarted.returncode, 0, restarted.stderr)
        self.assertEqual(self.state("jobs", self.job), "INTERRUPTED")
        self.assertEqual(self.state("archives", self.archive), "INCOMPLETE")
        self.assertEqual(self.state("media", self.media), "SUSPECT")
        self.assertEqual(self.state("jobs", old), "VERIFIED")
        staged = self.catalog.db.execute("SELECT * FROM staged_archives WHERE job_id=?", (self.job,)).fetchone()
        self.assertEqual((staged["state"], staged["phase"], staged["sha256"], staged["progress_bytes"]),
                         ("INTERRUPTED", "TAPE_WRITE", self.digest, 512))
        self.assertEqual(hashlib.sha256(self.artifact.read_bytes()).hexdigest(), self.digest)
        self.assertTrue(marker.is_file())
        self.assertEqual(self.control.commands()[0]["state"], "INTERRUPTED")
        self.assertIsNone(self.control.claim())
        before = self.catalog.db.execute("SELECT count(*) FROM events").fetchone()[0]
        self.assertEqual(self.catalog.interrupt_unfinished(), 0)
        self.assertEqual(self.catalog.db.execute("SELECT count(*) FROM events").fetchone()[0], before)

    def test_all_recovery_changes_roll_back_together(self):
        self.start_interrupted_job()
        self.catalog.db.execute("CREATE TRIGGER reject_suspect BEFORE UPDATE ON media "
                                "WHEN NEW.state='SUSPECT' BEGIN SELECT RAISE(ABORT,'test failure'); END")
        with self.assertRaisesRegex(sqlite3.IntegrityError, "test failure"):
            self.catalog.interrupt_unfinished()
        self.assertEqual(self.state("jobs", self.job), "RUNNING")
        self.assertEqual(self.state("archives", self.archive), "WRITING")
        self.assertEqual(self.state("media", self.media), "READY")
        self.assertEqual(self.catalog.db.execute("SELECT count(*) FROM events WHERE event='job_interrupted'").fetchone()[0], 0)

    def test_media_scoped_recovery_leaves_unrelated_jobs_untouched(self):
        self.start_interrupted_job()
        other = self.catalog.job("verify", None)
        restore = self.catalog.job("restore", self.media)
        with self.catalog.db:
            self.catalog.db.execute("INSERT INTO restores VALUES(?,?,?,?,?)",
                                    (str(uuid.uuid4()), restore, str(self.root / "restore"), "{}", "RUNNING"))
        self.assertEqual(self.catalog.interrupt_unfinished(self.media), 2)
        self.assertEqual(self.state("jobs", other), "RUNNING")
        self.assertEqual(self.catalog.db.execute("SELECT state FROM restores").fetchone()[0], "INTERRUPTED")

    def test_busy_io_prevents_startup_reconciliation(self):
        self.start_interrupted_job()
        with io_lock(), patch("otam.web.worker.signal.signal"), \
                patch("otam.web.worker.diagnostics.scan") as scan:
            with self.assertRaises(IOBusyError):
                run_worker(self.config, once=True)
        self.assertEqual(self.state("jobs", self.job), "RUNNING")
        self.assertEqual(self.state("archives", self.archive), "WRITING")
        scan.assert_not_called()
