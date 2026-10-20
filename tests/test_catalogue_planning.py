"""Physical planning must work offline without weakening write-time preflight."""
import hashlib
import json
import os
import tempfile
import time
import uuid
from dataclasses import replace
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from otam.catalog import Catalog
from otam.common import FORMAT, SafetyError
from otam.planning import catalogue_snapshot
from otam.web.config import WebConfig, Resource
from otam.web.control import Control
from otam.web.physical_archive import planning_snapshot
from otam.web.worker import execute


class CataloguePlanning(TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(dir=os.environ.get("OTAM_TEST_TMPDIR"))
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name).resolve()
        self.source = self.root / "source"
        self.source.mkdir()
        for name in ("one", "two"):
            (self.source / name).write_bytes(name.encode() * 20000)
        self.config = WebConfig(str(uuid.uuid4()), "offline", "archive", self.root / "state",
                                self.root / "catalog.sqlite", self.root / "staging",
                                self.root / "simulator", self.root / "restore",
                                "pbkdf2_sha256$600000$salt$digest",
                                sources=(Resource("source", "Source", self.source),),
                                physical_maintenance=True, physical_archiving=True,
                                physical_multivolume=True)
        self.catalog = Catalog(self.config.catalog)
        self.addCleanup(self.catalog.close)
        self.control = Control(self.config.state)
        self.control.set("operation_mode", "physical")
        self.control.set("hardware_inventory", {"time": 0, "drives": []})
        self.media = [str(uuid.uuid4()), str(uuid.uuid4())]
        bindings = {}
        for i, media in enumerate(self.media):
            self.catalog.register({"format": FORMAT, "media_id": media, "backend": "physical",
                                   "medium_serial": f"MAM-{i}", "label": f"TEST-{i}",
                                   "class": "rotation", "capacity": 125000}, 10240)
            bindings[media] = {"media_id": media, "drive_serial": "DRIVE", "medium_serial": f"MAM-{i}"}
        self.control.set("physical_media_bindings", bindings)

    def test_single_and_multi_planning_never_discover_or_open_device(self):
        with patch("otam.physical.discover_drives", side_effect=AssertionError("Device discovery forbidden")), \
                patch("otam.web.physical_archive.LinuxTape", side_effect=AssertionError("Device access forbidden")):
            single = execute(self.config, self.control, "plan", {
                "media_id": self.media[0], "source_id": "source", "selected_paths": ["one"]})
            multi = execute(self.config, self.control, "plan", {
                "media_ids": self.media, "source_id": "source", "target": 70000, "verify_mode": "media"})
        self.assertEqual(single["file_count"], 1)
        self.assertEqual(multi["media_ids"], self.media)
        parent = json.loads(self.catalog.db.execute("SELECT plan_json FROM jobs WHERE id=?", (multi["job_id"],)).fetchone()[0])
        self.assertEqual([c["files"] for c in parent["children"]], [1, 1])
        for child in parent["children"]:
            plan = json.loads(self.catalog.db.execute("SELECT plan_json FROM jobs WHERE id=?", (child["job_id"],)).fetchone()[0])
            self.assertEqual(plan["expected_tape_files"], 1)
            self.assertIn("physical preflight required", plan["planning_basis"])

    def test_multivolume_is_separately_disabled_by_default(self):
        disabled = replace(self.config, physical_multivolume=False)
        with self.assertRaisesRegex(SafetyError, "Mehrbandbetrieb"):
            execute(disabled, self.control, "plan", {"media_ids": self.media, "source_id": "source"})
        with self.assertRaises(SafetyError):
            replace(self.config, physical_archiving=False).validate()

    def test_changed_binding_or_known_pending_blocks_offline_plan(self):
        media = self.media[0]
        marker = self.config.state / "physical-pending" / (hashlib.sha256(b"MAM-0").hexdigest() + ".json")
        marker.parent.mkdir()
        marker.write_text("unresolved intent")
        with self.assertRaisesRegex(SafetyError, "Schreibvorgang"):
            planning_snapshot(self.config, self.control, media)
        marker.unlink()
        saved = self.control.get("physical_media_bindings")
        saved[media]["medium_serial"] = "OTHER"
        self.control.set("physical_media_bindings", saved)
        with self.assertRaisesRegex(SafetyError, "Katalogbindung"):
            planning_snapshot(self.config, self.control, media)

    def test_unverified_or_noncontiguous_catalogue_and_understated_usage_refuse(self):
        media = self.media[0]
        job = self.catalog.job("archive", media, "VERIFIED")
        archive = str(uuid.uuid4())
        manifest = {"archive_id": archive, "media_id": media, "created": time.time(), "files": []}
        self.catalog.record_archive(manifest, job, 1, "VERIFIED", 10240, "a" * 64)
        for column, value in (("state", "WRITING"), ("tape_file", 3), ("sha256", "wrong")):
            with self.subTest(column=column):
                with self.catalog.db:
                    self.catalog.db.execute("UPDATE media SET used=30720 WHERE id=?", (media,))
                    self.catalog.db.execute("UPDATE archives SET state='VERIFIED',tape_file=1,sha256=? WHERE id=?", ("a" * 64, archive))
                    self.catalog.db.execute("UPDATE archives SET " + column + "=? WHERE id=?", (value, archive))
                with self.assertRaises(SafetyError):
                    catalogue_snapshot(self.catalog, media)
        with self.catalog.db:
            self.catalog.db.execute("UPDATE archives SET sha256=? WHERE id=?", ("a" * 64, archive))
            self.catalog.db.execute("UPDATE media SET used=10240 WHERE id=?", (media,))
        with self.assertRaisesRegex(SafetyError, "capacity"):
            catalogue_snapshot(self.catalog, media)
