"""The synchronous hardware harness must retain real inventory freshness gates."""
import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from otam.web.control import Control
from tools.tape_web_cli_acceptance import refresh_inventory


class AcceptanceInventory(TestCase):
    def test_long_command_requires_real_discovery_without_forging_timestamp(self):
        with tempfile.TemporaryDirectory() as root:
            control = Control(Path(root))
            stale = {"time": 100, "drives": [{"serial": "OLD"}]}
            control.set("hardware_inventory", stale)
            with patch("tools.tape_web_cli_acceptance.time.time", return_value=221), \
                    patch("otam.web.diagnostics.scan") as scan:
                refresh_inventory(control)
                scan.assert_called_once_with(control)
            # No fake refresh when discovery did not publish a new observation.
            self.assertEqual(control.get("hardware_inventory"), stale)

    def test_current_inventory_does_not_trigger_extra_device_probes(self):
        with tempfile.TemporaryDirectory() as root:
            control = Control(Path(root))
            control.set("hardware_inventory", {"time": 100, "drives": []})
            with patch("tools.tape_web_cli_acceptance.time.time", return_value=219), \
                    patch("otam.web.diagnostics.scan") as scan:
                refresh_inventory(control)
                scan.assert_not_called()
