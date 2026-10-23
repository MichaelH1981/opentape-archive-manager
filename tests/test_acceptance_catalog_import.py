"""Importing verified hardware-acceptance metadata must remain transactional."""
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from otam.catalog import Catalog
from otam.common import SafetyError
from otam.service import ArchiveService
from otam.tape import SimulatedTape
from tools.tape_web_cli_acceptance import archive_rows, import_verified


class AcceptanceImport(TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(dir=os.environ.get("OTAM_TEST_TMPDIR"))
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name).resolve()
        source = self.root / "source"
        source.mkdir()
        (source / "original").write_bytes(b"original")
        self.live = Catalog(self.root / "live.sqlite")
        self.addCleanup(self.live.close)
        tape = SimulatedTape.create(self.root / "tape", "TEST", 10**7)
        service = ArchiveService(self.live, tape)
        self.media = service.register()["media_id"]
        first = service.plan(source, self.media)
        service.backup(first["job_id"], first["job_id"], self.root / "staging")
        self.baseline = archive_rows(self.live.db, self.media)
        self.copy = Catalog(self.root / "copy.sqlite")
        self.addCleanup(self.copy.close)
        self.live.db.backup(self.copy.db)
        second_source = self.root / "synthetic"
        second_source.mkdir()
        for name in ("one", "two"):
            (second_source / name).write_bytes(name.encode() * 100)
        service = ArchiveService(self.copy, tape)
        plan = service.plan(second_source, self.media, target=1000)
        service.backup(plan["job_id"], plan["job_id"], self.root / "staging")
        self.job = plan["job_id"]

    def perform_import(self):
        report = {}
        import_verified(SimpleNamespace(catalog=self.live.path), SimpleNamespace(catalog=self.copy.path),
                        self.media, self.baseline, self.job, self.root, report)
        return report

    def test_only_new_verified_archives_are_imported_with_provenance(self):
        report = self.perform_import()
        rows = archive_rows(self.live.db, self.media)
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[:1], self.baseline)
        self.assertEqual(len(report["live_catalog_import"]["archives"]), 2)
        self.assertEqual(self.live.db.execute("SELECT count(*) FROM events WHERE event='verified_acceptance_import'").fetchone()[0], 1)

    def test_unverified_job_cannot_modify_live_catalog(self):
        with self.copy.db:
            self.copy.db.execute("UPDATE jobs SET state='FAILED' WHERE id=?", (self.job,))
        with self.assertRaisesRegex(SafetyError, "completely verified"):
            self.perform_import()
        self.assertEqual(archive_rows(self.live.db, self.media), self.baseline)

    def test_failure_halfway_rolls_back_entire_import(self):
        original = Catalog.record_archive
        count = 0

        def fail_second(catalog, *args, **kwargs):
            nonlocal count
            count += 1
            if count == 2:
                raise OSError("injected import failure")
            return original(catalog, *args, **kwargs)

        with patch.object(Catalog, "record_archive", fail_second):
            with self.assertRaisesRegex(OSError, "import failure"):
                self.perform_import()
        self.assertEqual(archive_rows(self.live.db, self.media), self.baseline)
        self.assertEqual(self.live.db.execute("SELECT count(*) FROM jobs WHERE kind='acceptance-import'").fetchone()[0], 0)
