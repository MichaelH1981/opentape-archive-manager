"""SCSI fixtures only: never access devices or hardware log pages."""

import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from otam.common import SafetyError
from otam.diagnostics import decode, parameters, collect
from otam.web.control import Control
from otam.web.diagnostics import overview, save_sample, scan, detail


def page(code, values):
    payload = b"".join(
        ident.to_bytes(2, "big") + b"\0" + bytes([len(value)]) + value
        for ident, value in values
    )
    return bytes([code, 0]) + len(payload).to_bytes(2, "big") + payload


def drive():
    return dict(
        id="a" * 32,
        device="/dev/nst0",
        serial="DRIVE",
        medium_serial="TAPE",
        sg="/dev/sg1",
        ready=True,
        status={"online": True, "write_protected": False},
    )


class Diagnostics(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.control = Control(Path(self.temp.name))

    def tearDown(self):
        self.temp.cleanup()

    def test_log_page_validation_and_exact_large_counter_values(self):
        raw = page(2, [(6, (2**64 - 1).to_bytes(8, "big")), (5, b"\0")])
        self.assertEqual(decode(raw, 2)["counters"][0]["value"], str(2**64 - 1))
        for invalid in (
            raw[:-1],
            raw + b"\0",
            page(3, [(0, b"\0")]),
            page(2, [(0, b"\0"), (0, b"\1")]),
            b"",
        ):
            with self.assertRaises(SafetyError):
                parameters(invalid, 2)
        with self.assertRaises(SafetyError):
            decode(page(2, [(6, b"")]), 2)
        with self.assertRaises(SafetyError):
            decode(page(0x2E, []), 0x2E)
        with self.assertRaises(SafetyError):
            decode(page(0x2E, [(3, b"\x02")]), 0x2E)

    def test_temperature_unknown_and_zero_are_not_confused(self):
        unknown = decode(page(0xD, [(0, b"\0\xff")]), 0xD)
        self.assertIsNone(unknown["current_celsius"])
        self.assertIsNone(unknown["reference_celsius"])
        self.assertEqual(decode(page(0xD, [(0, b"\0\0")]), 0xD)["current_celsius"], 0)
        self.assertEqual(
            decode(page(0xD, [(0, b"\0\x23"), (1, b"\0\x46")]), 0xD)[
                "reference_celsius"
            ],
            70,
        )

    def test_alert_is_durable_after_raw_capture_even_without_second_callback(self):
        sample = {
            "drive_id": "a" * 32,
            "drive_serial": "DRIVE",
            "medium_serial": "TAPE",
            "started": 10,
            "kernel_stats": {},
            "page_sample": {
                "page": 0x2E,
                "time": 11,
                "state": "CAPTURED",
                "raw_hex": page(0x2E, [(3, b"\1")]).hex(),
            },
        }
        save_sample(self.control, sample)
        restarted = Control(Path(self.temp.name))
        self.assertEqual(detail(restarted, "a" * 32)["warning_history"][0]["code"], 3)
        clean = {
            **sample,
            "started": 20,
            "page_sample": {
                **sample["page_sample"],
                "time": 21,
                "raw_hex": page(0x2E, [(3, b"\0")]).hex(),
            },
        }
        save_sample(restarted, clean)
        self.assertEqual(
            detail(restarted, "a" * 32)["warning_history"][0]["last_seen"], 11
        )
        self.assertEqual(
            detail(restarted, "a" * 32)["sample"]["pages"]["2e"]["time"], 21
        )

    def test_collect_only_uses_bounded_read_only_log_sense_and_persists_before_next_read(
        self,
    ):
        events = []

        def command(args, timeout):
            self.assertIn("--readonly", args)
            self.assertEqual(args.count("--raw"), 2)
            self.assertIn("--maxlen=4096", args)
            self.assertNotIn("--reset", args)
            self.assertNotIn("--select", args)
            code = int(
                next(v for v in args if v.startswith("--page=")).split("=")[1], 16
            )
            events.append(("read", code))
            if code == 0xD:
                raise SafetyError("unsupported")
            return (
                page(code, [(3, b"\1")]) if code == 0x2E else page(code, [(6, b"\0")])
            )

        def sink(value):
            save_sample(self.control, value)
            events.append(("persist", value["page_sample"]["page"]))

        with (
            patch("otam.diagnostics.run", side_effect=command),
            patch("otam.diagnostics.kernel_stats", return_value={}),
        ):
            result = collect(drive(), sink)
        self.assertEqual(
            events[:4], [("read", 46), ("persist", 46), ("persist", 46), ("read", 2)]
        )
        self.assertEqual(result["pages"]["0d"]["state"], "UNAVAILABLE")
        self.assertEqual(
            detail(self.control, "a" * 32)["warning_history"][0]["code"], 3
        )
        with (
            patch("otam.diagnostics.run", return_value=page(46, [(3, b"\1")])) as read,
            patch("otam.diagnostics.kernel_stats", return_value={}),
        ):
            with self.assertRaises(OSError):
                collect(
                    drive(),
                    lambda value: (_ for _ in ()).throw(OSError("storage unavailable")),
                )
            read.assert_called_once()

    def test_medium_change_invalidates_alerts_but_preserves_history(self):
        now=time.time();d=drive()
        self.control.set("worker_heartbeat",now)
        self.control.set("hardware_inventory",{"time":now,"drives":[d]})
        observation={"drive_id":d["id"],"drive_serial":"DRIVE","medium_serial":"TAPE","started":now,
                     "page_sample":{"page":46,"time":now,"state":"AVAILABLE","raw_hex":page(46,[(3,b"\1")]).hex(),"decoded":{"active_flags":[3]}}}
        save_sample(self.control,observation)
        self.assertEqual(overview(self.control)["drives"][0]["diagnostics"]["current_alerts"],[3])
        self.control.set("hardware_inventory",{"time":now,"drives":[{**d,"medium_serial":"OTHER"}]})
        diag=overview(self.control)["drives"][0]["diagnostics"]
        self.assertTrue(diag["stale"]);self.assertIsNone(diag["current_alerts"])
        observation.update(medium_serial="OTHER",started=now+1)
        observation["page_sample"]={"page":46,"time":now+1,"state":"AVAILABLE","raw_hex":page(46,[(3,b"\0")]).hex(),"decoded":{"active_flags":[]}}
        save_sample(self.control,observation)
        diag=overview(self.control)["drives"][0]["diagnostics"]
        self.assertEqual(diag["current_alerts"],[]);self.assertEqual(len(diag["warning_history"]),1)

    def test_offline_and_stale_status_never_claim_current_medium(self):
        now = time.time()
        d = drive()
        self.control.set("worker_heartbeat", now)
        self.control.set("hardware_inventory", {"time": now, "drives": [d]})
        self.control.set("hardware_last_seen", {d["id"]: {**d, "last_seen": now}})
        self.assertEqual(
            overview(self.control)["drives"][0]["contact_state"], "CURRENT"
        )
        self.control.set("hardware_inventory", {"time": now, "drives": []})
        offline = overview(self.control)["drives"][0]
        self.assertEqual(offline["contact_state"], "OFFLINE")
        self.assertFalse(offline["observed_present"])
        self.control.set("hardware_inventory", {"time": now - 60, "drives": [d]})
        self.assertEqual(overview(self.control)["drives"][0]["contact_state"], "STALE")
        self.control.set("worker_heartbeat", 0)
        self.assertFalse(overview(self.control)["worker_online"])

    def test_resolved_identity_hides_anonymous_duplicate_but_preserves_history(self):
        now = time.time()
        d = {**drive(), "sysfs": "/sys/tape/device"}
        old = {**d, "id": "b" * 32, "serial": None, "last_seen": now - 10}
        other = {**d, "id": "c" * 32, "serial": "OTHER", "last_seen": now - 20}
        self.control.set("worker_heartbeat", now)
        self.control.set("hardware_inventory", {"time": now, "drives": [d]})
        self.control.set("hardware_last_seen", {old["id"]: old, other["id"]: other})
        self.assertEqual(
            {v["id"] for v in overview(self.control)["drives"]}, {d["id"], other["id"]}
        )
        self.control.set(
            "drive_alerts:" + old["id"], {"3": {"code": 3, "last_seen": now}}
        )
        self.assertIn(old["id"], {v["id"] for v in overview(self.control)["drives"]})
        self.assertEqual(
            detail(self.control, old["id"])["warning_history"][0]["code"], 3
        )

    def test_running_maintenance_shows_persistent_progress_without_hardware_queries(
        self,
    ):
        now = time.time()
        d = drive()
        self.control.set("worker_heartbeat", now)
        self.control.set("hardware_inventory", {"time": now - 90, "drives": [d]})
        command = self.control.enqueue(
            "tape-maintenance", {"approval_id": "approval"}, "test-maintenance"
        )
        self.control.claim()
        self.control.set(
            "maintenance_progress:approval",
            {
                "state": "RUNNING",
                "phase": "TAPE_WRITE",
                "time": now,
                "bytes": 123,
                "drive": d,
                "seed": "private",
            },
        )
        with patch(
            "otam.web.diagnostics.discover_drives",
            side_effect=AssertionError("must remain cached"),
        ):
            value = overview(self.control)
        self.assertEqual(value["active_maintenance"]["command_id"], command["id"])
        self.assertEqual(value["drives"][0]["active_maintenance"]["bytes"], 123)
        self.assertEqual(value["drives"][0]["contact_state"], "STALE")
        self.assertNotIn("seed", value["active_maintenance"])
        self.control.set("worker_heartbeat", 0)
        self.assertFalse(overview(self.control)["worker_online"])

    def test_interval_and_medium_changes_trigger_fresh_diagnostics(self):
        d = drive()
        calls = []

        def sample(value, sink):
            calls.append(value["medium_serial"])
            save_sample(
                self.control,
                {
                    "drive_id": value["id"],
                    "drive_serial": value["serial"],
                    "medium_serial": value["medium_serial"],
                    "started": time.time(),
                    "page_sample": {
                        "page": 46,
                        "time": time.time(),
                        "state": "UNAVAILABLE",
                    },
                },
            )

        with (
            patch("otam.web.diagnostics.discover_drives", return_value=[d]),
            patch("otam.web.diagnostics.collect", side_effect=sample),
        ):
            scan(self.control)
            scan(self.control)
            self.assertEqual(calls, ["TAPE"])
            d["medium_serial"] = "OTHER"
            scan(self.control)
            self.assertEqual(calls, ["TAPE", "OTHER"])
            scan(self.control, force=True)
            self.assertEqual(len(calls), 3)
            d["busy"] = True
            scan(self.control, force=True)
            self.assertEqual(len(calls), 3)

    def test_current_summary_excludes_historical_identities_and_alerts(self):
        now=time.time();d=drive()
        self.control.set('worker_heartbeat',now)
        self.control.set('hardware_inventory',{'time':now,'drives':[d]})
        old={**d,'id':'old','medium_serial':'OLD-TAPE','last_seen':now-10000}
        self.control.set('hardware_last_seen',{'old':old,d['id']:{**d,'last_seen':now-5000}})
        self.control.set('drive_alerts:old',{'3':{'code':3,'last_seen':now-10000}})
        result=overview(self.control)
        self.assertEqual(result['current_drive']['id'],d['id'])
        self.assertEqual(result['current_drive']['medium_serial'],'TAPE')
        self.assertEqual(result['current_drive']['last_seen'],now)
        self.assertEqual(result['observed_drive_count'],1)
        self.assertEqual(len(result['drives']),2)
        self.assertEqual(detail(self.control,'old')['warning_history'][0]['code'],3)

    def test_no_observed_drive_never_promotes_a_historical_tape(self):
        now=time.time();d=drive()
        self.control.set('worker_heartbeat',now)
        self.control.set('hardware_inventory',{'time':now,'drives':[]})
        self.control.set('hardware_last_seen',{d['id']:{**d,'last_seen':now-100}})
        result=overview(self.control)
        self.assertIsNone(result['current_drive'])
        self.assertEqual(result['observed_drive_count'],0)
        self.assertEqual(len(result['drives']),1)

    def test_multiple_observed_drives_have_one_deterministic_summary(self):
        now=time.time();a=drive();b={**a,'id':'second','device':'/dev/nst1','serial':'SECOND'}
        self.control.set('worker_heartbeat',now)
        self.control.set('hardware_inventory',{'time':now,'drives':[b,a]})
        result=overview(self.control)
        self.assertEqual(result['current_drive']['id'],a['id'])
        self.assertEqual(result['observed_drive_count'],2)
        self.control.set('hardware_inventory',{'time':now-100,'drives':[a]})
        self.assertEqual(overview(self.control)['current_drive']['contact_state'],'STALE')
