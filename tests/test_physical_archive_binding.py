"""Shared web/CLI physical binding gates; no devices or subprocesses opened."""
import tempfile
import io
import json
import time
import uuid
from contextlib import redirect_stdout, redirect_stderr
from dataclasses import replace, asdict
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from otam.common import SafetyError
from otam.web.config import WebConfig
from otam.web.control import Control
from otam.web import physical_archive as physical
from otam.cli import main


class PhysicalBindings(TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        root = Path(folder.name).resolve()
        self.config = WebConfig(str(uuid.uuid4()), "test", "archive", root / "state",
                                root / "catalog.sqlite", root / "staging", root / "media",
                                root / "restore", "pbkdf2_sha256$600000$salt$digest",
                                physical_maintenance=True, physical_archiving=True)
        self.control = Control(self.config.state)
        self.control.set("operation_mode", "physical")
        self.media = str(uuid.uuid4())
        self.drive = {"id": "drive-1", "serial": "DRIVE", "medium_serial": "MAM", "ready": True,
                      "device": "/dev/nst0", "sg": "/dev/sg0", "vendor": "IBM",
                      "model": "ULT3580-HH4", "status": {"online": True, "density_code": 0x46}}
        self.inventory()
        self.control.set("physical_media_bindings", {self.media: {
            "media_id": self.media, "drive_serial": "DRIVE", "medium_serial": "MAM"}})
        self.storage = {"mount": "/staging", "source": "/dev/test", "device": "1:2", "type": "ext4"}
        self.settings = {"drive_id": "drive-1", "drive_serial": "DRIVE",
                         "medium_density_code": 0x46, "profile_id": "ibm-ult3580-hh4-lto4",
                         "write_rate_bytes_per_second": 120_000_000,
                         "buffer_bytes": 2368 * 1024**2, "storage": self.storage, "effective": False}
        self.control.set("transfer_settings:staging-1", self.settings)
        for target, value in (("otam.web.physical_archive.require_local", self.storage),
                              ("otam.web.physical_archive.resources.staging_for", self.config.staging)):
            mock = patch(target, return_value=value)
            mock.start()
            self.addCleanup(mock.stop)

    def inventory(self, **changes):
        self.control.set("hardware_inventory", {"time": time.time(), "drives": [{**self.drive, **changes}]})

    def test_disabled_gate_and_invalid_config_refuse(self):
        disabled = replace(self.config, physical_archiving=False)
        with patch("otam.web.physical_archive.LinuxTape") as tape:
            with self.assertRaises(SafetyError):
                physical.mounted(disabled, self.control, self.media)
            tape.assert_not_called()
        with self.assertRaises(SafetyError):
            replace(self.config, physical_maintenance=False).validate()

    def test_persistent_serial_binding_resolves_new_nst_name(self):
        self.inventory(device="/dev/nst3")
        tape = physical.mounted(self.config, self.control, self.media)
        self.assertEqual(tape.device.device, "/dev/nst3")
        self.assertEqual(tape.device.expected["medium_serial"], "MAM")

    def test_saved_dropdown_rate_and_buffer_are_actually_passed_to_backend(self):
        tape = physical.mounted(self.config, self.control, self.media, staging_id="staging-1")
        self.assertEqual(tape.buffer_mib, 2368)
        self.assertEqual(tape.write_rate, 120_000_000)
        self.assertFalse(self.control.get("transfer_settings:staging-1")["effective"])

    def test_write_protected_medium_can_restore_but_cannot_start_backup(self):
        self.inventory(ready=False, status={**self.drive["status"], "write_protected": True})
        physical.mounted(self.config, self.control, self.media)
        with self.assertRaisesRegex(SafetyError, "nicht schreibbereit"):
            physical.mounted(self.config, self.control, self.media, staging_id="staging-1")

    def test_wrong_medium_drive_busy_and_stale_inventory_refuse(self):
        for changes in ({"medium_serial": "OTHER"}, {"serial": "OTHER"}, {"busy": True}):
            with self.subTest(changes=changes):
                self.inventory(**changes)
                with self.assertRaises(SafetyError):
                    physical.mounted(self.config, self.control, self.media)
        self.control.set("hardware_inventory", {"time": time.time() - 121, "drives": [self.drive]})
        with self.assertRaisesRegex(SafetyError, "veraltet"):
            physical.mounted(self.config, self.control, self.media)

    def test_missing_or_changed_transfer_profile_and_storage_refuse(self):
        for changes in ({"drive_serial": "OTHER"}, {"medium_density_code": 0x44},
                        {"write_rate_bytes_per_second": 80_000_000}, {"buffer_bytes": True},
                        {"storage": {**self.storage, "device": "9:9"}}):
            with self.subTest(changes=changes):
                self.control.set("transfer_settings:staging-1", {**self.settings, **changes})
                with self.assertRaises(SafetyError):
                    physical.mounted(self.config, self.control, self.media, staging_id="staging-1")
        with self.assertRaises(SafetyError):
            physical.mounted(self.config, self.control, self.media, staging_id="unknown")

    def test_registration_is_read_only_and_preserves_existing_binding(self):
        payload = {"drive_id": "drive-1", "drive_serial": "DRIVE", "medium_serial": "MAM"}
        header = {"media_id": self.media, "backend": "physical", "medium_serial": "MAM"}
        with patch("otam.web.physical_archive.discover_drives", return_value=[self.drive]), \
                patch("otam.web.physical_archive.LinuxTape") as tape, \
                patch("otam.web.physical_archive.ArchiveService.register", return_value=header):
            result = physical.register_existing(self.config, self.control, payload)
            self.assertEqual(result["binding"]["medium_serial"], "MAM")
            tape.return_value.initialize.assert_not_called()
            tape.return_value.append.assert_not_called()
        self.control.set("physical_media_bindings", {self.media: {
            "media_id": self.media, "drive_serial": "OTHER", "medium_serial": "MAM"}})
        with patch("otam.web.physical_archive.discover_drives", return_value=[self.drive]), \
                patch("otam.web.physical_archive.LinuxTape"), \
                patch("otam.web.physical_archive.ArchiveService.register", return_value=header):
            with self.assertRaisesRegex(SafetyError, "nicht ersetzt"):
                physical.register_existing(self.config, self.control, payload)

    def test_cli_queues_registration_idempotently_without_device_access(self):
        config_path = self.config.state.parent / "node.json"
        config_path.write_text(json.dumps(asdict(self.config), default=str))
        payload = self.config.state.parent / "payload.json"
        payload.write_text(json.dumps({"drive_id": "drive-1", "drive_serial": "DRIVE", "medium_serial": "MAM"}))
        arguments = ["physical-command", "--config", str(config_path), "--kind", "register-physical",
                     "--payload-file", str(payload), "--idempotency-key", "same-review-key"]
        with patch("otam.web.physical_archive.discover_drives") as discovery, redirect_stdout(io.StringIO()):
            self.assertEqual(main(arguments), 0)
            self.assertEqual(main(arguments), 0)
            discovery.assert_not_called()
        commands = self.control.commands()
        self.assertEqual(len(commands), 1)
        self.assertEqual(commands[0]["state"], "QUEUED")
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(main(["physical-command-status", "--config", str(config_path),
                                   "--command-id", commands[0]["id"]]), 0)
        self.assertEqual(json.loads(output.getvalue())["kind"], "register-physical")

    def test_cli_disabled_archive_gate_cannot_queue_backup(self):
        config_path = self.config.state.parent / "disabled.json"
        config_path.write_text(json.dumps(asdict(replace(self.config, physical_archiving=False)), default=str))
        payload = self.config.state.parent / "payload.json"
        payload.write_text("{}")
        with redirect_stderr(io.StringIO()):
            self.assertEqual(main(["physical-command", "--config", str(config_path), "--kind", "backup",
                                   "--payload-file", str(payload)]), 1)
        self.assertEqual(self.control.commands(), [])
