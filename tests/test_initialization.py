"""Single-use initialization approvals; no real hardware is accessed."""
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import asdict, replace
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from otam.catalog import Catalog
from otam.common import FORMAT, SafetyError
from otam.web.config import WebConfig
from otam.web.control import Control
from otam.web import initialization as init


class Initialization(TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(dir=os.environ.get("OTAM_TEST_TMPDIR"))
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name).resolve()
        self.config = WebConfig(str(uuid.uuid4()), "test", "archive", self.root / "state",
                                self.root / "catalog.sqlite", self.root / "staging", self.root / "simulator",
                                self.root / "restore", "pbkdf2_sha256$600000$salt$digest",
                                physical_maintenance=True, physical_archiving=True, physical_initialization=True)
        self.control = Control(self.config.state)
        self.control.set("operation_mode", "physical")
        self.drive = {"id": "drive-id", "serial": "DRIVE", "medium_serial": "MAM", "ready": True,
                      "device": "/dev/nst0", "sg": "/dev/sg0", "vendor": "IBM", "model": "ULT3580-HH4",
                      "status": {"online": True, "density_code": 0x46, "write_protected": False}}
        self.inventory(self.drive)
        self.data = {"drive_id": "drive-id", "drive_serial": "DRIVE", "medium_serial": "MAM",
                     "label": "REVIEWED", "media_class": "rotation"}
        self.header = {"format": FORMAT, "media_id": str(uuid.uuid4()), "backend": "physical",
                       "medium_serial": "MAM", "label": "REVIEWED", "class": "rotation",
                       "capacity": 800_000_000_000, "created": time.time()}

    def inventory(self, drive):
        self.control.set("hardware_inventory", {"time": time.time(), "drives": [drive]})

    def prepare(self):
        return init.prepare(self.config, self.control, self.data)

    def payload(self, grant):
        return {"approval_id": grant["id"], "confirmation": grant["confirmation"], "destructive_confirmed": True}

    def configure_tape(self, constructor):
        tape = constructor.return_value
        tape.initialize.return_value = self.header
        tape.header.return_value = self.header
        tape.positions.return_value = [0]
        tape.used.return_value = 10240
        return tape

    def test_default_gate_profile_readiness_and_parameters_fail_closed(self):
        with self.assertRaises(SafetyError):
            init.prepare(replace(self.config, physical_initialization=False), self.control, self.data)
        with self.assertRaises(SafetyError):
            replace(self.config, physical_archiving=False).validate()
        for changes in ({"model": "UNKNOWN"}, {"ready": False},
                        {"status": {**self.drive["status"], "write_protected": True}}):
            self.inventory({**self.drive, **changes})
            with self.assertRaises(SafetyError):
                self.prepare()
        self.inventory(self.drive)
        with self.assertRaises(SafetyError):
            init.prepare(self.config, self.control, {**self.data, "capacity": 1_600_000_000_000})
        self.control.set("hardware_inventory", {"time": 0, "drives": [self.drive]})
        with self.assertRaises(SafetyError):
            self.prepare()

    def test_prepare_is_read_only_and_native_capacity_is_not_a_user_claim(self):
        with patch("otam.web.initialization.discover_drives") as discovery, patch("otam.web.initialization.LinuxTape") as tape:
            grant = self.prepare()
            discovery.assert_not_called()
            tape.assert_not_called()
        self.assertEqual(grant["capacity"], 800_000_000_000)
        self.assertEqual(grant["confirmation"], "INITIALIZE DRIVE MAM")

    def test_all_known_catalogue_classes_and_states_protect_existing_data(self):
        catalog = Catalog(self.config.catalog)
        try:
            catalog.register(self.header, 10240)
            for state in ("READY", "IN_USE", "ARCHIVED", "SUSPECT", "RETIRED"):
                with self.subTest(state=state), catalog.db:
                    catalog.db.execute("UPDATE media SET state=?", (state,))
                with self.assertRaisesRegex(SafetyError, "bekannte Kassette"):
                    self.prepare()
        finally:
            catalog.close()

    def test_pending_and_consumed_intent_block_new_initialization(self):
        marker = self.config.state / "physical-pending" / (hashlib.sha256(b"MAM").hexdigest() + ".json")
        marker.parent.mkdir()
        marker.symlink_to(self.root / "absent")
        with self.assertRaisesRegex(SafetyError, "Ungeklärter"):
            self.prepare()
        marker.unlink()
        first, second = self.prepare(), self.prepare()
        init.approval(self.config, self.control, self.payload(first), consume=True)
        with self.assertRaisesRegex(SafetyError, "verbraucht"):
            init.approval(self.config, self.control, self.payload(first), consume=True)
        with self.assertRaisesRegex(SafetyError, "Frühere"):
            init.approval(self.config, self.control, self.payload(second), consume=True)
        with self.assertRaisesRegex(SafetyError, "Frühere"):
            self.prepare()

    def test_confirmation_expiry_node_and_metadata_are_sealed(self):
        grant = self.prepare()
        for payload in ({**self.payload(grant), "destructive_confirmed": False},
                        {**self.payload(grant), "confirmation": "INITIALIZE OTHER"},
                        {**self.payload(grant), "label": "CHANGED"}):
            with self.assertRaises(SafetyError):
                init.approval(self.config, self.control, payload)
        with patch("otam.web.initialization.time.time", return_value=grant["expires"] + 1):
            with self.assertRaises(SafetyError):
                init.approval(self.config, self.control, self.payload(grant))
        with self.assertRaises(SafetyError):
            init.approval(replace(self.config, node_id=str(uuid.uuid4())), self.control, self.payload(grant))
        grant["label"] = "ALTERED"
        self.control.set(init.PREFIX + grant["id"], grant)
        with self.assertRaises(SafetyError):
            init.approval(self.config, self.control, self.payload(grant))

    def test_media_swap_fails_before_adapter_and_requires_a_new_approval(self):
        grant = self.prepare()
        with patch("otam.web.initialization.discover_drives", return_value=[{**self.drive, "medium_serial": "OTHER"}]), \
                patch("otam.web.initialization.LinuxTape") as tape:
            with self.assertRaises(SafetyError):
                init.execute(self.config, self.control, self.payload(grant))
            tape.assert_not_called()
        with self.assertRaises(SafetyError):
            init.approval(self.config, self.control, self.payload(grant))
        self.assertNotEqual(self.prepare()["id"], grant["id"])

    def test_verified_header_registration_is_separate_from_archive_success(self):
        grant = self.prepare()
        with patch("otam.web.initialization.discover_drives", return_value=[self.drive]), \
                patch("otam.web.initialization.LinuxTape") as constructor:
            tape = self.configure_tape(constructor)
            result = init.execute(self.config, self.control, self.payload(grant))
            tape.initialize.assert_called_once_with("REVIEWED", 800_000_000_000, "rotation", "INITIALIZE MAM")
        self.assertEqual(result["state"], "INITIALIZED")
        catalog = Catalog(self.config.catalog)
        try:
            self.assertEqual(catalog.db.execute("SELECT count(*) FROM archives").fetchone()[0], 0)
            self.assertEqual(catalog.db.execute("SELECT state FROM media").fetchone()[0], "READY")
            self.assertEqual(catalog.db.execute("SELECT serial FROM media").fetchone()[0], "MAM")
            self.assertEqual(catalog.db.execute("SELECT state FROM jobs").fetchone()[0], "SUCCEEDED")
        finally:
            catalog.close()
        with self.assertRaises(SafetyError):
            self.prepare()

    def test_write_or_catalogue_failure_reserves_the_cartridge_for_read_only_inspection(self):
        grant = self.prepare()
        with patch("otam.web.initialization.discover_drives", return_value=[self.drive]), \
                patch("otam.web.initialization.LinuxTape") as constructor, \
                patch.object(Catalog, "register", side_effect=OSError("catalog publish failed")):
            self.configure_tape(constructor)
            with self.assertRaisesRegex(OSError, "catalog publish failed"):
                init.execute(self.config, self.control, self.payload(grant))
        saved = self.control.get(init.PREFIX + grant["id"])
        self.assertTrue(saved["write_attempted"])
        self.assertEqual(saved["state"], "FAILED")
        with self.assertRaisesRegex(SafetyError, "Frühere"):
            self.prepare()

    def test_header_mismatch_or_failed_write_is_not_reported_as_initialized(self):
        grant = self.prepare()
        with patch("otam.web.initialization.discover_drives", return_value=[self.drive]), \
                patch("otam.web.initialization.LinuxTape") as constructor:
            tape = self.configure_tape(constructor)
            wrong = {**self.header, "capacity": 1_600_000_000_000}
            tape.initialize.return_value = wrong
            tape.header.return_value = wrong
            with self.assertRaisesRegex(SafetyError, "Header"):
                init.execute(self.config, self.control, self.payload(grant))
        catalog = Catalog(self.config.catalog)
        try:
            self.assertEqual(catalog.db.execute("SELECT count(*) FROM media").fetchone()[0], 0)
            self.assertEqual(catalog.db.execute("SELECT state FROM jobs").fetchone()[0], "FAILED")
        finally:
            catalog.close()
        self.assertTrue(self.control.get(init.PREFIX + grant["id"])["write_attempted"])

    def test_abrupt_process_end_preserves_consumed_reservation(self):
        grant = self.prepare()
        config = self.root / "node.json"
        config.write_text(json.dumps(asdict(self.config), default=str))
        script = """
import json,os,sys
from pathlib import Path
from otam.web.config import WebConfig
from otam.web.control import Control
from otam.web.initialization import approval
c=WebConfig.load(Path(sys.argv[1]))
approval(c,Control(c.state),json.loads(sys.argv[2]),consume=True)
os._exit(91)
"""
        ended = subprocess.run([sys.executable, "-c", script, str(config), json.dumps(self.payload(grant))], capture_output=True)
        self.assertEqual(ended.returncode, 91, ended.stderr)
        self.assertEqual(self.control.get(init.PREFIX + grant["id"])["state"], "CONSUMED")
        with self.assertRaisesRegex(SafetyError, "Frühere"):
            self.prepare()
