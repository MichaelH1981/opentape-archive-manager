"""Read-only tape speed profile selection; no hardware access."""

import unittest

from otam.transfer import drive_speed_profiles, selected_speed_profile


class DriveSpeedProfiles(unittest.TestCase):
    def setUp(self):
        self.drive = {
            "id": "drive-1", "vendor": "IBM", "model": "ULT3580-HH4",
            "serial": "SERIAL-1", "medium_serial": "TAPE-1",
            "status": {"online": True, "density_code": 0x46},
        }
        self.inventory = {"time": 1000, "drives": [self.drive]}

    def test_ibm_hh4_with_lto4_has_documented_steps(self):
        profile = selected_speed_profile(self.inventory, "drive-1", now=1050)
        self.assertEqual(profile["speed_steps_bytes_per_second"],
                         [rate * 1_000_000 for rate in (30, 48, 66, 84, 103, 120)])
        self.assertEqual(profile["medium_density_code"], 0x46)

    def test_unknown_media_drive_or_stale_inventory_has_no_claimed_steps(self):
        self.assertEqual(drive_speed_profiles(self.inventory, now=1121), [])
        self.drive["status"]["density_code"] = 0x44
        self.assertEqual(drive_speed_profiles(self.inventory, now=1050), [])
        self.drive["status"]["density_code"] = 0x46
        self.drive["model"] = "OTHER-LTO4"
        self.assertEqual(drive_speed_profiles(self.inventory, now=1050), [])
        self.drive["model"] = "ULT3580-HH4"
        self.drive["status"] = None
        self.assertEqual(drive_speed_profiles(self.inventory, now=1050), [])


if __name__ == "__main__":
    unittest.main()
