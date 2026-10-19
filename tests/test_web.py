"""HTTP, worker and independent-catalog acceptance tests; synthetic data only."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sqlite3
import tempfile
import time
import unittest
import uuid
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from otam.catalog import Catalog
from otam.common import SafetyError
from otam.web.config import Resource, WebConfig, password_hash
from otam.web.control import Control
from otam.web.query import CatalogView
from otam.web.replication import (
    digest,
    export_nas,
    make_snapshot,
    metadata_header,
    sign,
)
from otam.web.worker import execute, run_once, validate_command, worker_lock

WEB_AVAILABLE = (
    importlib.util.find_spec("fastapi") is not None
    and importlib.util.find_spec("httpx") is not None
)
PASSWORD = "test-only-password-1234"
HASH = password_hash(PASSWORD)


@unittest.skipUnless(WEB_AVAILABLE, "Optional [web] dependencies not installed")
class AccountMigration(unittest.TestCase):
    def test_v1_control_upgrade_preserves_commands_and_invalidates_anonymous_sessions(self):
        from otam.web.accounts import bootstrap

        with tempfile.TemporaryDirectory(prefix="otam-account-upgrade-") as folder:
            state = Path(folder)
            with sqlite3.connect(state / "control.sqlite") as db:
                db.executescript("""
                    CREATE TABLE commands(id TEXT PRIMARY KEY,kind TEXT,state TEXT,
                        created REAL,updated REAL,payload TEXT,result TEXT,error TEXT,idempotency TEXT UNIQUE);
                    CREATE TABLE sessions(hash TEXT PRIMARY KEY,csrf TEXT,expires REAL);
                    CREATE TABLE attempts(ip TEXT,time REAL);
                    CREATE TABLE resources(id TEXT PRIMARY KEY,path TEXT UNIQUE);
                    CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT);
                    CREATE TABLE sync_log(id INTEGER PRIMARY KEY,time REAL,direction TEXT,
                        state TEXT,sequence INTEGER,details TEXT);
                    INSERT INTO sessions VALUES('old','csrf',9999999999);
                    INSERT INTO settings VALUES('operation_mode','\"simulator\"');
                    INSERT INTO commands VALUES('existing','plan','SUCCEEDED',1,1,'{}',NULL,NULL,'prior-key');
                    PRAGMA user_version=1;
                """)
            control = Control(state)
            bootstrap(control, "admin", HASH)
            with control.connect() as db:
                self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 2)
                self.assertEqual(db.execute("SELECT count(*) FROM sessions").fetchone()[0], 0)
                self.assertEqual(db.execute("SELECT state FROM commands WHERE id='existing'").fetchone()[0], "SUCCEEDED")
                self.assertEqual(db.execute("SELECT value FROM settings WHERE key='operation_mode'").fetchone()[0], '"simulator"')
                self.assertEqual(db.execute("SELECT role FROM users WHERE username='admin'").fetchone()[0], "admin")
            bootstrap(control, "admin", password_hash("different-password-1234"))
            with control.connect() as db:
                self.assertEqual(db.execute("SELECT password_hash FROM users WHERE username='admin'").fetchone()[0], HASH)


@unittest.skipUnless(WEB_AVAILABLE, "Optional [web] dependencies not installed")
class WebAcceptance(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient
        from otam.web.app import create_app

        self.temp = tempfile.TemporaryDirectory(
            prefix="otam-web-", dir=os.environ.get("OTAM_TEST_TMPDIR")
        )
        self.root = Path(self.temp.name).resolve()
        self.source = self.root / "sources"
        self.source.mkdir()
        (self.source / "photo.jpg").write_bytes(b"synthetic image contents\n")
        (self.source / "document.pdf").write_bytes(b"synthetic document contents\n")
        self.key = self.root / "peer.key"
        self.key.write_text("synthetic-peer-secret-" + "a" * 32)
        self.key.chmod(0o600)
        node = self.root / "node"
        self.config = WebConfig(
            str(uuid.uuid4()),
            "Acceptance",
            "archive",
            node / "state",
            node / "catalog.sqlite",
            node / "staging",
            node / "media",
            node / "restore",
            HASH,
            allowed_hosts=("testserver", "127.0.0.1"),
            sources=(Resource("source-1", "Test files", self.source),),
            peer_key_file=self.key,
        )
        self.app = create_app(self.config)
        self.control = self.app.state.control
        self.client = TestClient(self.app)
        self.csrf = self.client.post(
            "/api/v1/login", json={"username": "admin", "password": PASSWORD}
        ).json()["csrf"]

    def tearDown(self):
        self.client.close()
        self.temp.cleanup()

    def command(self, kind, payload, key=None):
        response = self.client.post(
            "/api/v1/commands",
            json={"kind": kind, "payload": payload},
            headers={
                "X-CSRF-Token": self.csrf,
                "Idempotency-Key": key or str(uuid.uuid4()),
            },
        )
        self.assertEqual(response.status_code, 202, response.text)
        return response.json()

    def work(self):
        self.assertTrue(run_once(self.config, self.control))
        row = self.control.commands()[0]
        self.assertEqual(row["state"], "SUCCEEDED", row)
        return row["result"]

    def test_staging_speedtest_settings_are_editable_but_not_effective(self):
        from fastapi.testclient import TestClient

        self.config.staging.mkdir(parents=True, exist_ok=True)
        path = "/api/v1/staging/transfer-settings/default-staging"
        value = {"write_rate_bytes_per_second": 85_000_000,
                 "buffer_bytes": 1024 * 1024 ** 2}
        self.assertEqual(self.client.put(path, json=value).status_code, 403)
        invalid = {**value, "buffer_bytes": 1000}
        self.assertEqual(self.client.put(path, json=invalid,
                                         headers={"X-CSRF-Token": self.csrf}).status_code, 409)
        saved = self.client.put(path, json=value,
                                headers={"X-CSRF-Token": self.csrf})
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertFalse(saved.json()["effective"])
        self.assertEqual(set(saved.json()["storage"]), {"mount", "source", "device", "type"})
        speedtests = self.client.get("/api/v1/staging/speedtests").json()
        self.assertEqual(speedtests["settings"]["default-staging"]["buffer_bytes"],
                         value["buffer_bytes"])
        self.assertEqual(speedtests["items"], [])
        with self.assertRaises(SafetyError):
            validate_command(self.config, self.control, "staging-speedtest",
                             {"staging_id": "default-staging", "seconds": 0})
        viewer = self.client.post("/api/v1/users", json={
            "username": "speed.viewer", "password": "viewer-password-1234", "role": "viewer",
        }, headers={"X-CSRF-Token": self.csrf})
        self.assertEqual(viewer.status_code, 201)
        other = TestClient(self.app)
        try:
            csrf = other.post("/api/v1/login", json={
                "username": "speed.viewer", "password": "viewer-password-1234",
            }).json()["csrf"]
            self.assertEqual(other.put(path, json=value,
                                       headers={"X-CSRF-Token": csrf}).status_code, 403)
            self.assertEqual(other.post("/api/v1/commands", json={
                "kind": "staging-speedtest", "payload": {"staging_id": "default-staging", "seconds": 60},
            }, headers={"X-CSRF-Token": csrf,
                        "Idempotency-Key": str(uuid.uuid4())}).status_code, 403)
        finally:
            other.close()

    def archived(self):
        self.command("create-medium", {"label": "TEST-001"})
        medium = self.work()["media_id"]
        self.command("plan", {"media_id": medium, "source_id": "source-1"})
        plan = self.work()
        self.command("stage", {"job_id": plan["job_id"]})
        self.work()
        self.command(
            "backup",
            {
                "job_id": plan["job_id"],
                "confirm": plan["job_id"],
                "plan_hash": plan["sha256"],
            },
        )
        self.work()
        return medium, plan

    def replica(self):
        from fastapi.testclient import TestClient
        from otam.web.app import create_app

        cfg = replace(
            self.config,
            role="catalog",
            state=self.root / "replica" / "state",
            catalog=self.root / "replica" / "unused.sqlite",
            sources=(),
            publisher_id=self.config.node_id,
        )
        app = create_app(cfg)
        client = TestClient(app)
        return cfg, app, client

    def upload(self, client, meta, content):
        return client.put(
            "/api/v1/replication/snapshot",
            content=content,
            headers={
                "Authorization": "Bearer " + self.config.peer_key().decode(),
                "X-OTAM-Manifest": metadata_header(meta),
                "Content-Length": str(meta["bytes"]),
            },
        )

    def test_http_archive_staging_catalog_restore_cycle(self):
        medium, plan = self.archived()
        job = self.client.get("/api/v1/jobs/" + plan["job_id"]).json()
        self.assertEqual(job["state"], "VERIFIED")
        self.assertTrue(all(s["phase"] == "STAGING_CLEANUP" for s in job["staging"]))
        files = self.client.get("/api/v1/files").json()
        self.assertEqual(files["total"], 2)
        self.assertTrue(all(f["state"] == "VERIFIED" for f in files["items"]))
        payload = {
            "media_id": medium,
            "paths": ["photo.jpg"],
            "target_name": "restored-1",
        }
        r = self.client.post(
            "/api/v1/restore-plan", json=payload, headers={"X-CSRF-Token": self.csrf}
        )
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["media_count"], 1)
        self.command("restore", payload)
        self.work()
        self.assertEqual(
            (self.config.restore_root / "restored-1/photo.jpg").read_bytes(),
            (self.source / "photo.jpg").read_bytes(),
        )
        self.command("restore", payload)
        run_once(self.config, self.control)
        self.assertEqual(self.control.commands()[0]["state"], "FAILED")
        self.assertTrue((self.source / "photo.jpg").exists())

    def test_source_browser_and_guided_two_medium_archive_set(self):
        album = self.source / "album"
        album.mkdir()
        (album / "a.raw").write_bytes(b"a" * 60_000)
        (album / "b.raw").write_bytes(b"b" * 60_000)
        (album / "link").symlink_to(self.source / "photo.jpg")
        listing = self.client.get("/api/v1/source-tree", params={"source_id": "source-1"})
        self.assertEqual(listing.status_code, 200, listing.text)
        self.assertIn("album", [item["path"] for item in listing.json()["items"]])
        nested = self.client.get("/api/v1/source-tree", params={"source_id": "source-1", "path": "album"})
        self.assertEqual({item["path"] for item in nested.json()["items"]},
                         {"album/a.raw", "album/b.raw"})
        (album / "link").unlink()
        traversal = self.client.get("/api/v1/source-tree", params={"source_id": "source-1", "path": "../"})
        self.assertEqual(traversal.status_code, 409)

        first = execute(self.config, self.control, "create-medium",
                        {"label": "SET-1", "capacity": 125_000})["media_id"]
        second = execute(self.config, self.control, "create-medium",
                         {"label": "SET-2", "capacity": 125_000})["media_id"]
        plan = execute(self.config, self.control, "plan", {
            "media_ids": [first, second], "source_id": "source-1", "target": 70_000,
            "selected_paths": ["album"], "verify_mode": "media",
        })
        self.assertEqual(plan["file_count"], 2)
        self.assertEqual(plan["media_ids"], [first, second])
        with self.assertRaises(SafetyError):
            execute(self.config, self.control, "backup-set", {
                "job_id": plan["job_id"], "confirm": plan["job_id"],
                "plan_hash": plan["sha256"], "media_id": second,
            })
        payload = {"job_id": plan["job_id"], "confirm": plan["job_id"],
                   "plan_hash": plan["sha256"]}
        first_result = execute(self.config, self.control, "backup-set",
                               {**payload, "media_id": first})
        self.assertEqual(first_result["state"], "WAITING_MEDIA")
        self.assertEqual(first_result["next_media_id"], second)
        detail = self.client.get("/api/v1/jobs/" + plan["job_id"]).json()
        self.assertEqual([child["state"] for child in detail["plan"]["children"]],
                         ["VERIFIED", "PLANNED"])
        second_result = execute(self.config, self.control, "backup-set",
                                {**payload, "media_id": second})
        self.assertEqual(second_result["state"], "VERIFIED")
        files = self.client.get("/api/v1/files").json()["items"]
        self.assertEqual({row["path"] for row in files}, {"album/a.raw", "album/b.raw"})
        self.assertEqual({row["media_id"] for row in files}, {first, second})
        self.assertEqual((album / "a.raw").read_bytes(), b"a" * 60_000)
        self.assertEqual((album / "b.raw").read_bytes(), b"b" * 60_000)
        catalog = Catalog(self.config.catalog)
        try:
            with catalog.db:
                catalog.db.execute("UPDATE jobs SET state='INTERRUPTED' WHERE id=?",
                                   (plan["job_id"],))
        finally:
            catalog.close()
        from otam.tape import SimulatedTape
        second_tape = SimulatedTape(self.control.resource(second))
        before = second_tape.positions()
        repaired = execute(self.config, self.control, "backup-set",
                           {**payload, "media_id": second})
        self.assertEqual(repaired["state"], "VERIFIED")
        self.assertEqual(second_tape.positions(), before)

    def test_unhashable_media_selection_returns_client_error(self):
        response = self.client.post("/api/v1/commands", json={
            "kind": "plan", "payload": {"source_id": "source-1",
                                      "media_ids": [{"wrong": "type"}, "another"],
                                      "target": 70_000}},
            headers={"X-CSRF-Token": self.csrf, "Idempotency-Key": str(uuid.uuid4())})
        self.assertEqual(response.status_code, 409, response.text)

    def test_authentication_csrf_origin_and_host(self):
        from fastapi.testclient import TestClient

        anonymous = TestClient(self.app)
        self.assertEqual(anonymous.get("/api/v1/files").status_code, 401)
        body = {"kind": "create-medium", "payload": {"label": "X"}}
        headers = {"Idempotency-Key": "test-command"}
        self.assertEqual(
            self.client.post(
                "/api/v1/commands", json=body, headers=headers
            ).status_code,
            403,
        )
        headers.update({"X-CSRF-Token": self.csrf, "Origin": "https://evil.example"})
        self.assertEqual(
            self.client.post(
                "/api/v1/commands", json=body, headers=headers
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.get(
                "/api/v1/node", headers={"Host": "evil.example"}
            ).status_code,
            400,
        )
        self.assertEqual(self.client.get("/").headers["x-frame-options"], "DENY")
        self.assertIn(
            "script-src 'self'", self.client.get("/").headers["content-security-policy"]
        )
        anonymous.close()

    def test_session_expiry_and_logout(self):
        self.assertIn(
            "HttpOnly",
            self.client.post(
                "/api/v1/login", json={"username": "admin", "password": PASSWORD}
            ).headers["set-cookie"],
        )
        self.csrf = self.client.get("/api/v1/session").json()["csrf"]
        self.assertEqual(
            self.client.post(
                "/api/v1/logout", json={}, headers={"X-CSRF-Token": self.csrf}
            ).status_code,
            200,
        )
        self.assertEqual(self.client.get("/api/v1/session").status_code, 401)

    def test_local_users_roles_language_and_session_revocation(self):
        from fastapi.testclient import TestClient

        headers = {"X-CSRF-Token": self.csrf}
        initial = self.client.get("/api/v1/users").json()["items"]
        self.assertEqual(len(initial), 1)
        self.assertEqual(initial[0]["role"], "admin")
        self.assertNotIn("password_hash", initial[0])
        self.assertEqual(
            self.client.patch(
                "/api/v1/users/" + initial[0]["id"],
                json={"enabled": False}, headers=headers,
            ).status_code, 409,
        )
        created = self.client.post(
            "/api/v1/users",
            json={"username": "archive.viewer", "password": "viewer-password-1234", "role": "viewer"},
            headers=headers,
        )
        self.assertEqual(created.status_code, 201, created.text)
        ident = created.json()["id"]
        viewer = TestClient(self.app)
        signed = viewer.post(
            "/api/v1/login", json={"username": "archive.viewer", "password": "viewer-password-1234"}
        )
        self.assertEqual(signed.status_code, 200, signed.text)
        self.assertEqual(signed.json()["role"], "viewer")
        vheaders = {"X-CSRF-Token": signed.json()["csrf"], "Idempotency-Key": str(uuid.uuid4())}
        self.assertEqual(viewer.get("/api/v1/files").status_code, 200)
        self.assertEqual(viewer.get("/api/v1/users").status_code, 403)
        self.assertEqual(viewer.post(
            "/api/v1/commands", json={"kind": "create-medium", "payload": {"label": "blocked"}},
            headers=vheaders,
        ).status_code, 403)
        self.assertEqual(viewer.put(
            "/api/v1/account/locale", json={"locale": "en"}, headers=vheaders,
        ).json()["locale"], "en")
        self.assertEqual(viewer.get("/api/v1/session").json()["locale"], "en")
        self.assertEqual(viewer.post(
            "/api/v1/account/password",
            json={"current_password": "viewer-password-1234", "new_password": "new-viewer-password-1234"},
            headers=vheaders,
        ).status_code, 200)
        self.assertEqual(viewer.get("/api/v1/session").status_code, 200)
        self.assertEqual(viewer.post(
            "/api/v1/login", json={"username": "archive.viewer", "password": "viewer-password-1234"}
        ).status_code, 401)
        self.assertEqual(self.client.patch(
            "/api/v1/users/" + ident, json={"enabled": False}, headers=headers,
        ).status_code, 200)
        self.assertEqual(viewer.get("/api/v1/session").status_code, 401)
        self.assertEqual(viewer.post(
            "/api/v1/login", json={"username": "archive.viewer", "password": "new-viewer-password-1234"}
        ).status_code, 401)
        viewer.close()

    def test_operator_cannot_manage_users_or_approve_tape_maintenance(self):
        from fastapi.testclient import TestClient

        created = self.client.post(
            "/api/v1/users",
            json={"username": "operator1", "password": "operator-password-1234", "role": "operator"},
            headers={"X-CSRF-Token": self.csrf},
        )
        self.assertEqual(created.status_code, 201, created.text)
        operator = TestClient(self.app)
        signed = operator.post(
            "/api/v1/login", json={"username": "operator1", "password": "operator-password-1234"}
        ).json()
        headers = {"X-CSRF-Token": signed["csrf"], "Idempotency-Key": str(uuid.uuid4())}
        self.assertEqual(operator.get("/api/v1/users").status_code, 403)
        self.assertEqual(operator.put(
            "/api/v1/operation-mode", json={"mode": "physical"}, headers=headers,
        ).status_code, 403)
        self.assertEqual(operator.post(
            "/api/v1/commands", json={"kind": "tape-maintenance", "payload": {}},
            headers=headers,
        ).status_code, 403)
        self.assertEqual(operator.post(
            "/api/v1/commands", json={"kind": "create-medium", "payload": {"label": "allowed"}},
            headers=headers,
        ).status_code, 202)
        operator.close()

    def test_login_rate_limit(self):
        for _ in range(10):
            self.assertEqual(
                self.client.post(
                    "/api/v1/login", json={"username": "admin", "password": "incorrect"}
                ).status_code,
                401,
            )
        self.assertEqual(
            self.client.post(
                "/api/v1/login", json={"username": "admin", "password": PASSWORD}
            ).status_code,
            429,
        )

    def test_unknown_paths_commands_and_unreviewed_plans_rejected(self):
        self.command("create-medium", {"label": "TEST"})
        media = self.work()["media_id"]
        response = self.client.post(
            "/api/v1/commands",
            json={"kind": "plan", "payload": {"media_id": media, "source_id": "/etc"}},
            headers={"X-CSRF-Token": self.csrf, "Idempotency-Key": "untrusted-source"},
        )
        self.assertEqual(response.status_code, 409)
        self.command("plan", {"media_id": media, "source_id": "source-1"})
        plan = self.work()
        with self.assertRaises(SafetyError):
            validate_command(
                self.config,
                self.control,
                "backup",
                {
                    "job_id": plan["job_id"],
                    "confirm": plan["job_id"],
                    "plan_hash": "wrong",
                },
            )
        with self.assertRaises(SafetyError):
            validate_command(
                self.config,
                self.control,
                "restore",
                {"media_id": media, "target_name": "../escape"},
            )
        with self.assertRaises(SafetyError):
            validate_command(
                self.config,
                self.control,
                "plan",
                {"media_id": media, "source_id": "source-1", "source": "/etc"},
            )
        self.assertEqual(
            self.client.post(
                "/api/v1/commands",
                json={"kind": "erase", "payload": {}},
                headers={
                    "X-CSRF-Token": self.csrf,
                    "Idempotency-Key": "forbidden-command",
                },
            ).status_code,
            409,
        )

    def test_malformed_command_types_and_huge_filters_return_client_errors(self):
        for kind, payload in [
            ("plan", {"source_id": {}, "media_id": 123}),
            ("stage", {"job_id": 123}),
            ("verify", {"media_id": []}),
        ]:
            result = self.client.post(
                "/api/v1/commands",
                json={"kind": kind, "payload": payload},
                headers={
                    "X-CSRF-Token": self.csrf,
                    "Idempotency-Key": str(uuid.uuid4()),
                },
            )
            self.assertEqual(result.status_code, 409, result.text)
        self.assertEqual(
            self.client.get(
                "/api/v1/files", params={"min_size": str(10**40)}
            ).status_code,
            422,
        )
        self.assertEqual(
            self.client.post(
                "/api/v1/login", json={"username": "ungültig", "password": PASSWORD}
            ).status_code,
            401,
        )

    def test_queue_is_durable_idempotent_and_interrupts_without_retry(self):
        first = self.command("create-medium", {"label": "FIRST"}, "same-request-key")
        self.assertEqual(
            self.command("create-medium", {"label": "FIRST"}, "same-request-key")["id"],
            first["id"],
        )
        fresh = Control(self.config.state)
        running = fresh.claim()
        self.assertEqual(running["id"], first["id"])
        fresh.interrupt_running()
        self.assertIsNone(fresh.claim())
        self.assertEqual(fresh.commands()[0]["state"], "INTERRUPTED")
        with self.assertRaises(SafetyError):
            fresh.enqueue("create-medium", {"label": "OTHER"}, "same-request-key")

    def test_only_one_worker_per_node(self):
        with worker_lock(self.config):
            with self.assertRaises(SafetyError):
                with worker_lock(self.config):
                    self.fail("Second worker acquired lock")

    def test_catalog_filters_pagination_and_copies(self):
        medium, plan = self.archived()
        self.command("plan", {"media_id": medium, "source_id": "source-1"})
        p = self.work()
        self.command(
            "backup",
            {"job_id": p["job_id"], "confirm": p["job_id"], "plan_hash": p["sha256"]},
        )
        self.work()
        r = self.client.get(
            "/api/v1/files",
            params={
                "q": "PHOTO",
                "file_type": ".jpg",
                "duplicates": "true",
                "limit": 1,
            },
        ).json()
        self.assertEqual(r["total"], 2)
        self.assertEqual(len(r["items"]), 1)
        self.assertEqual(r["items"][0]["copies"], 2)
        r = self.client.get(
            "/api/v1/files", params={"checksum": r["items"][0]["sha256"], "offset": 1}
        ).json()
        self.assertEqual(len(r["items"]), 1)
        self.assertEqual(
            self.client.get("/api/v1/files", params={"min_size": 100000}).json()[
                "total"
            ],
            0,
        )
        self.assertEqual(
            self.client.get("/api/v1/files", params={"limit": 100000}).status_code, 422
        )

    def test_export_json_csv_and_formula_escape(self):
        (self.source / "=SUM(1).txt").write_text("test")
        self.archived()
        r = self.client.get("/api/v1/export?table=files&format=csv")
        self.assertEqual(r.status_code, 200)
        self.assertIn("'=SUM", r.text)
        self.assertEqual(
            len(self.client.get("/api/v1/export?table=files&format=json").json()), 3
        )
        self.assertEqual(
            self.client.get("/api/v1/export?table=sqlite_master").status_code, 400
        )

    def test_replica_survives_primary_shutdown_and_has_own_ui(self):
        self.archived()
        cfg, app, client = self.replica()
        path, meta = make_snapshot(self.config, self.control)
        self.assertEqual(self.upload(client, meta, path.read_bytes()).status_code, 200)
        self.config.catalog.rename(self.config.catalog.with_suffix(".offline"))
        r = client.post(
            "/api/v1/login", json={"username": "admin", "password": PASSWORD}
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(client.get("/api/v1/files").json()["total"], 2)
        self.assertEqual(client.get("/api/v1/node").json()["role"], "catalog")
        self.assertIn("Dein Langzeitarchiv", client.get("/").text)
        self.assertEqual(
            client.post("/api/v1/commands", json={"kind": "backup"}).status_code, 404
        )
        self.assertEqual(client.get("/api/v1/hardware").status_code, 404)
        client.close()

    def test_invalid_or_partial_snapshot_never_replaces_last_valid(self):
        self.archived()
        cfg, app, client = self.replica()
        path, meta = make_snapshot(self.config, self.control)
        body = path.read_bytes()
        self.assertEqual(self.upload(client, meta, body).status_code, 200)
        before = app.state.control.get("active_snapshot")
        newer = sign({**meta, "sequence": meta["sequence"] + 1}, self.config.peer_key())
        self.assertEqual(self.upload(client, newer, body[:-100]).status_code, 409)
        broken = bytearray(body)
        broken[100] ^= 1
        self.assertEqual(self.upload(client, newer, bytes(broken)).status_code, 409)
        self.assertEqual(app.state.control.get("active_snapshot"), before)
        self.assertFalse(list((cfg.state / "snapshots").glob("*.partial")))
        client.close()

    def test_snapshot_authentication_replay_identity_and_idempotence(self):
        cfg, app, client = self.replica()
        path, meta = make_snapshot(self.config, self.control)
        body = path.read_bytes()
        self.assertEqual(
            client.put("/api/v1/replication/snapshot", content=body).status_code, 401
        )
        self.assertEqual(self.upload(client, meta, body).json()["state"], "PUBLISHED")
        self.assertEqual(self.upload(client, meta, body).json()["state"], "UNCHANGED")
        wrong = sign(
            {**meta, "publisher": str(uuid.uuid4()), "sequence": meta["sequence"] + 1},
            self.config.peer_key(),
        )
        self.assertEqual(self.upload(client, wrong, body).status_code, 409)
        newer = sign({**meta, "sequence": meta["sequence"] + 1}, self.config.peer_key())
        self.assertEqual(self.upload(client, newer, body).status_code, 200)
        self.assertEqual(self.upload(client, meta, body).status_code, 409)
        badsig = {**newer, "signature": "0" * 64}
        self.assertEqual(self.upload(client, badsig, body).status_code, 409)
        client.close()

    def test_snapshot_validates_schema_and_recovers_orphan_publication(self):
        cfg, app, client = self.replica()
        path, meta = make_snapshot(self.config, self.control)
        folder = cfg.state / "snapshots"
        folder.mkdir()
        orphan = folder / f"{meta['sequence']:012d}-{meta['sha256']}.sqlite"
        orphan.write_bytes(path.read_bytes())
        orphan.chmod(0o400)
        self.assertEqual(self.upload(client, meta, path.read_bytes()).status_code, 200)
        arbitrary = self.root / "invalid.sqlite"
        db = sqlite3.connect(arbitrary)
        db.execute("CREATE TABLE unknown(x)")
        db.commit()
        db.close()
        invalid = sign(
            {
                **meta,
                "sequence": meta["sequence"] + 1,
                "bytes": arbitrary.stat().st_size,
                "sha256": digest(arbitrary),
            },
            self.config.peer_key(),
        )
        self.assertEqual(
            self.upload(client, invalid, arbitrary.read_bytes()).status_code, 409
        )
        self.assertEqual(
            app.state.control.get("active_snapshot")["sequence"], meta["sequence"]
        )
        client.close()

    def test_snapshot_limit_and_no_credentials_in_public_api(self):
        cfg, app, client = self.replica()
        path, meta = make_snapshot(self.config, self.control)
        too_large = sign(
            {**meta, "bytes": cfg.max_snapshot_bytes + 1}, self.config.peer_key()
        )
        self.assertEqual(self.upload(client, too_large, b"bad").status_code, 409)
        for route in ["/node", "/replication", "/overview"]:
            data = self.client.get("/api/v1" + route).text
            self.assertNotIn(self.key.read_text(), data)
            self.assertNotIn(HASH, data)
        client.close()

    def test_nas_export_has_explicit_target_marker_and_never_overwrites(self):
        folder = self.root / "nas"
        folder.mkdir()
        config = replace(self.config, nas_backup=folder)
        path, meta = make_snapshot(config, self.control)
        with self.assertRaises(SafetyError):
            export_nas(config, path, meta)
        (folder / ".otam-backup-target").write_text(config.node_id)
        export_nas(config, path, meta)
        snapshots = list(folder.glob("*.sqlite"))
        self.assertEqual(len(snapshots), 1)
        self.assertEqual(digest(snapshots[0]), meta["sha256"])
        with self.assertRaises(FileExistsError):
            export_nas(config, path, meta)
        self.assertEqual(len(list(folder.glob("*.sqlite"))), 1)

    def test_explicit_staging_revalidation_preserves_strict_write_checks(self):
        self.command("create-medium", {"label": "TEST"})
        media = self.work()["media_id"]
        self.command("plan", {"media_id": media, "source_id": "source-1"})
        plan = self.work()
        self.command("stage", {"job_id": plan["job_id"]})
        self.work()
        catalog = Catalog(self.config.catalog)
        row = catalog.db.execute(
            "SELECT path,fingerprint_json FROM staged_archives WHERE job_id=?",
            (plan["job_id"],),
        ).fetchone()
        path = Path(row["path"])
        path.chmod(0o600)
        path.chmod(0o400)  # Same bytes/inode/mtime, changed ctime.
        catalog.close()
        self.command(
            "backup",
            {
                "job_id": plan["job_id"],
                "confirm": plan["job_id"],
                "plan_hash": plan["sha256"],
            },
        )
        run_once(self.config, self.control)
        self.assertEqual(self.control.commands()[0]["state"], "FAILED")
        self.assertEqual(self.client.get("/api/v1/archives").json()["total"], 0)
        self.command(
            "stage",
            {
                "job_id": plan["job_id"],
                "revalidate_ready": True,
                "confirm": plan["job_id"],
            },
        )
        self.work()
        self.command(
            "backup",
            {
                "job_id": plan["job_id"],
                "confirm": plan["job_id"],
                "plan_hash": plan["sha256"],
            },
        )
        self.work()
        self.assertEqual(
            self.client.get("/api/v1/jobs/" + plan["job_id"]).json()["state"],
            "VERIFIED",
        )

    def test_revalidation_rejects_changed_contents_identity_or_unconfirmed_request(
        self,
    ):
        self.command("create-medium", {"label": "TEST"})
        media = self.work()["media_id"]
        self.command("plan", {"media_id": media, "source_id": "source-1"})
        plan = self.work()
        self.command("stage", {"job_id": plan["job_id"]})
        self.work()
        with self.assertRaises(SafetyError):
            validate_command(
                self.config,
                self.control,
                "stage",
                {"job_id": plan["job_id"], "revalidate_ready": True},
            )
        catalog = Catalog(self.config.catalog)
        row = catalog.db.execute(
            "SELECT path FROM staged_archives WHERE job_id=?", (plan["job_id"],)
        ).fetchone()
        path = Path(row[0])
        old = path.stat()
        path.chmod(0o600)
        with path.open("r+b") as f:
            f.seek(600)
            value = f.read(1)
            f.seek(600)
            f.write(bytes([value[0] ^ 1]))
        os.utime(path, ns=(old.st_atime_ns, old.st_mtime_ns))
        path.chmod(0o400)
        catalog.close()
        self.command(
            "stage",
            {
                "job_id": plan["job_id"],
                "revalidate_ready": True,
                "confirm": plan["job_id"],
            },
        )
        run_once(self.config, self.control)
        self.assertEqual(self.control.commands()[0]["state"], "FAILED")
        self.assertIn("checksum", self.control.commands()[0]["error"])

    def test_identical_catalog_is_not_reuploaded_or_duplicated(self):
        import base64
        import httpx
        from otam.web.replication import push

        config = replace(self.config, peer_url="https://catalog.invalid")

        def receipt(url, **kwargs):
            meta = json.loads(
                base64.urlsafe_b64decode(kwargs["headers"]["X-OTAM-Manifest"])
            )
            return httpx.Response(
                200, json={"state": "PUBLISHED", "sequence": meta["sequence"]}
            )

        with patch("httpx.Client.put", side_effect=receipt) as send:
            first = push(config, self.control)
            second = push(config, self.control)
            self.assertEqual(send.call_count, 1)
        self.assertEqual(first["state"], "SUCCEEDED")
        self.assertEqual(second["targets"][0]["state"], "UNCHANGED")
        self.assertEqual(
            first["targets"][0]["sequence"], second["targets"][0]["sequence"]
        )

    def test_sync_failure_preserves_catalog_and_records_error(self):
        from otam.web.replication import push

        config = replace(self.config, peer_url="https://catalog.invalid")
        with patch("httpx.Client.put", side_effect=OSError("offline")):
            self.assertEqual(push(config, self.control)["state"], "PARTIAL")
        self.assertTrue(config.catalog.exists())
        with self.control.connect() as db:
            self.assertEqual(
                db.execute(
                    "SELECT state FROM sync_log ORDER BY id DESC LIMIT 1"
                ).fetchone()[0],
                "FAILED",
            )
        self.assertIsNone(self.control.get("last_push"))

    def target(self, kind="catalog", address="https://catalog.example", **overrides):
        return dict(
            label="Optional destination",
            kind=kind,
            address=address,
            enabled=True,
            interval=300,
            allow_http=False,
            key=self.key.read_text(),
            **overrides,
        )

    def save_target_http(self, ident, data):
        return self.client.put(
            "/api/v1/replication/targets/" + ident,
            json=data,
            headers={"X-CSRF-Token": self.csrf},
        )

    def test_local_catalog_needs_no_targets_and_optional_configuration_is_durable(self):
        from otam.web.targets import public_targets

        self.assertTrue(self.config.catalog.is_file())
        self.assertEqual(public_targets(self.config, self.control), [])
        self.assertFalse(self.client.get("/api/v1/node").json()["sync_configured"])
        ident = str(uuid.uuid4())
        response = self.save_target_http(ident, self.target())
        self.assertEqual(response.status_code, 200, response.text)
        self.assertNotIn(self.key.read_text(), response.text)
        self.assertNotIn("key_file", response.text)
        restarted = Control(self.config.state)
        self.assertEqual(public_targets(self.config, restarted)[0]["id"], ident)
        self.assertEqual(self.control.path.stat().st_mode & 0o777, 0o600)
        data = self.target()
        data.update(enabled=False, key="")
        self.assertEqual(self.save_target_http(ident, data).status_code, 200)
        self.assertFalse(self.client.get("/api/v1/node").json()["sync_configured"])
        response = self.client.request(
            "DELETE",
            "/api/v1/replication/targets/" + ident,
            json={},
            headers={"X-CSRF-Token": self.csrf},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(public_targets(self.config, restarted), [])
        self.assertTrue(self.config.catalog.is_file())

    def test_multiple_targets_isolate_failure_and_retry_only_unsent_catalog(self):
        from otam.web.replication import push
        from otam.web.targets import initialize_directory

        offline = str(uuid.uuid4())
        good = str(uuid.uuid4())
        folder = self.root / "snapshots"
        folder.mkdir()
        self.assertEqual(self.save_target_http(offline, self.target()).status_code, 200)
        self.assertEqual(
            self.save_target_http(
                good, self.target("directory", str(folder))
            ).status_code,
            200,
        )
        initialize_directory(self.config, self.control, good, self.config.node_id)
        with patch(
            "httpx.Client.put", side_effect=OSError("secret-must-not-appear")
        ) as send:
            result = push(self.config, self.control)
            self.assertEqual(result["state"], "PARTIAL")
            self.assertEqual(
                [r["state"] for r in result["targets"]], ["FAILED", "SUCCEEDED"]
            )
            second = push(self.config, self.control)
            self.assertEqual(second["targets"][1]["state"], "UNCHANGED")
            self.assertEqual(send.call_count, 2)
            self.assertEqual(len(list(folder.glob("*.sqlite"))), 1)
            self.assertNotIn(
                "secret-must-not-appear", self.client.get("/api/v1/replication").text
            )
            # Failure does not prevent searching the mandatory local primary.
            self.assertEqual(self.client.get("/api/v1/files").status_code, 200)
            self.command("sync", {})
            self.assertTrue(run_once(self.config, self.control))
            self.assertEqual(self.control.commands()[0]["state"], "FAILED")

    def test_target_configuration_is_authenticated_validated_and_marker_is_explicit(
        self,
    ):
        ident = str(uuid.uuid4())
        path = "/api/v1/replication/targets/" + ident
        self.assertEqual(self.client.put(path, json=self.target()).status_code, 403)
        for patch_data in (
            {"address": "http://catalog.example"},
            {"address": "https://user:pass@catalog.example"},
            {"key": "short"},
            {"key": "ä" * 40},
            {"interval": True},
            {"enabled": "yes"},
            {"kind": "directory", "address": str(self.source)},
            {"kind": "directory", "address": str(self.config.state)},
        ):
            data = self.target()
            data.update(patch_data)
            self.assertIn(self.save_target_http(ident, data).status_code, (400, 409))
        folder = self.root / "destination"
        folder.mkdir()
        self.assertEqual(
            self.save_target_http(
                ident, self.target("directory", str(folder))
            ).status_code,
            200,
        )
        marker = folder / ".otam-backup-target"
        self.assertFalse(marker.exists())
        endpoint = path + "/initialize"
        headers = {"X-CSRF-Token": self.csrf}
        self.assertEqual(
            self.client.post(
                endpoint, json={"confirmation": "wrong"}, headers=headers
            ).status_code,
            409,
        )
        self.assertEqual(
            self.client.post(
                endpoint, json={"confirmation": self.config.node_id}, headers=headers
            ).status_code,
            200,
        )
        self.assertEqual(marker.read_text().strip(), self.config.node_id)
        self.assertEqual(
            self.client.post(
                endpoint, json={"confirmation": self.config.node_id}, headers=headers
            ).status_code,
            503,
        )
        self.assertEqual(marker.read_text().strip(), self.config.node_id)

    def test_destinations_use_distinct_keys_and_revalidate_directory_resolution(self):
        import base64
        import httpx
        from otam.web.replication import push
        from otam.web.targets import save_target, initialize_directory

        keys = {
            "https://one.example": "first-target-" + "a" * 32,
            "https://two.example": "second-target-" + "b" * 32,
        }
        for address, key in keys.items():
            data = self.target(address=address)
            data["key"] = key
            save_target(self.config, self.control, str(uuid.uuid4()), data)

        def receipt(url, **kwargs):
            key = keys[url.split("/api/")[0]].encode()
            self.assertEqual(
                kwargs["headers"]["Authorization"], "Bearer " + key.decode()
            )
            meta = json.loads(
                base64.urlsafe_b64decode(kwargs["headers"]["X-OTAM-Manifest"])
            )
            self.assertEqual(meta["signature"], sign(meta, key)["signature"])
            return httpx.Response(
                200, json={"state": "PUBLISHED", "sequence": meta["sequence"]}
            )

        with patch("httpx.Client.put", side_effect=receipt) as send:
            self.assertEqual(push(self.config, self.control)["state"], "SUCCEEDED")
            self.assertEqual(send.call_count, 2)
        folder = self.root / "mutable-target"
        folder.mkdir()
        ident = str(uuid.uuid4())
        save_target(
            self.config, self.control, ident, self.target("directory", str(folder))
        )
        initialize_directory(self.config, self.control, ident, self.config.node_id)
        # A target symlink retargeted into source data must never become writable.
        (folder / ".otam-backup-target").unlink()
        folder.rmdir()
        folder.symlink_to(self.source, target_is_directory=True)
        with patch("httpx.Client.put", side_effect=receipt):
            result = push(self.config, self.control)
        self.assertEqual(result["targets"][-1]["state"], "FAILED")
        self.assertEqual(
            sorted(p.name for p in self.source.iterdir()), ["document.pdf", "photo.jpg"]
        )

    def test_legacy_targets_remain_removed_after_restart_and_target_intervals(self):
        from otam.web.targets import delete_target, targets, save_target
        from otam.web.replication import push

        config = replace(self.config, peer_url="https://catalog.example")
        self.assertEqual(targets(config, self.control)[0]["id"], "legacy-catalog")
        delete_target(config, self.control, "legacy-catalog")
        self.assertEqual(targets(config, Control(config.state)), [])
        ident = str(uuid.uuid4())
        save_target(config, self.control, ident, self.target())
        self.control.set(
            "target_status:" + ident,
            {"time": time.time(), "revision": 1, "state": "SUCCEEDED"},
        )
        with patch("httpx.Client.put") as send:
            push(config, self.control, due_only=True)
            send.assert_not_called()
        # A changed target configuration invalidates both the interval and prior receipt.
        save_target(config, self.control, ident, self.target())
        with patch("httpx.Client.put", side_effect=OSError("offline")) as send:
            push(config, self.control, due_only=True)
            send.assert_called_once()

    def test_resource_picker_and_persistent_source_registration(self):
        from otam.web import resources

        config = replace(self.config, directory_roots=(self.root,))
        before = resources.browse(config, self.control)
        self.assertTrue(before["items"])
        self.assertEqual(
            resources.browse(config, self.control, str(self.source))["path"],
            str(self.source),
        )
        second = self.root / "second-source"
        second.mkdir()
        (second / "new.txt").write_text("source remains untouched")
        ident = str(uuid.uuid4())
        resources.save(
            config,
            self.control,
            ident,
            dict(kind="source", label="New source", path=str(second)),
        )
        self.assertIn(
            ident,
            [r.id for r in resources.effective(config, Control(config.state)).sources],
        )
        with patch(
            "otam.web.resources.filesystem", side_effect=OSError("unavailable source")
        ) as probe:
            listing = resources.overview(config, self.control)
            self.assertTrue(
                all(r["available"] is None for r in listing if r["kind"] == "source")
            )
            self.assertNotIn(self.source, [c.args[0] for c in probe.call_args_list])
            self.assertNotIn(second, [c.args[0] for c in probe.call_args_list])

        for path in [
            str(config.state),
            str(config.media_root),
            str(self.root / ".."),
            "/etc",
        ]:
            with self.assertRaises((SafetyError, OSError)):
                resources.browse(config, self.control, path)
        link = self.root / "symlink"
        link.symlink_to(second, target_is_directory=True)
        with self.assertRaises(SafetyError):
            resources.save(
                config,
                self.control,
                str(uuid.uuid4()),
                dict(kind="source", label="Link", path=str(link)),
            )
        resources.remove(config, self.control, ident)
        self.assertTrue((second / "new.txt").is_file())

    def test_staging_selection_is_bound_to_job_and_not_silently_redirected(self):
        from otam.web import resources

        config = replace(self.config, directory_roots=(self.root,))
        folder = self.root / "second-staging"
        folder.mkdir()
        ident = str(uuid.uuid4())
        resources.save(
            config,
            self.control,
            ident,
            dict(kind="staging", label="Other SSD", path=str(folder)),
        )
        medium = execute(
            config, self.control, "create-medium", {"label": "STAGING-TEST"}
        )["media_id"]
        plan = execute(
            config,
            self.control,
            "plan",
            {"media_id": medium, "source_id": "source-1", "staging_id": ident},
        )
        result = execute(config, self.control, "stage", {"job_id": plan["job_id"]})
        self.assertEqual(result["staging"], str(folder))
        with self.assertRaises(SafetyError):
            resources.remove(config, self.control, ident)
        result = execute(
            config,
            self.control,
            "backup",
            {
                "job_id": plan["job_id"],
                "confirm": plan["job_id"],
                "plan_hash": plan["sha256"],
            },
        )
        self.assertEqual(result["state"], "VERIFIED")
        with self.assertRaises(SafetyError):
            resources.save(
                config,
                self.control,
                str(uuid.uuid4()),
                dict(kind="source", label="Staging-as-source", path=str(folder)),
            )

        resources.remove(config, self.control, ident)
        self.assertTrue(folder.is_dir())

    def test_physical_mode_and_one_use_approval_require_fresh_identified_media(self):
        from otam.web import maintenance

        config = replace(self.config, physical_maintenance=True)
        maintenance.set_mode(config, self.control, "physical")
        with self.assertRaises(SafetyError):
            validate_command(
                config,
                self.control,
                "create-medium",
                {"label": "No implicit simulation"},
            )
        with self.assertRaises(SafetyError):
            maintenance.prepare(config, self.control, "drive", "qualify")
        drive = {
            "id": "drive",
            "device": "/dev/nst0",
            "serial": "DRIVE123",
            "medium_serial": "TAPE123",
            "ready": True,
            "sg": "/dev/sg1",
        }
        self.control.set("hardware_inventory", {"time": time.time(), "drives": [drive]})
        grant = maintenance.prepare(config, self.control, "drive", "qualify")
        payload = {
            "approval_id": grant["id"],
            "confirmation": grant["confirmation"],
            "destructive_confirmed": True,
        }
        validate_command(config, self.control, "tape-maintenance", payload)
        missing_checkbox = dict(payload, destructive_confirmed=False)
        with self.assertRaises(SafetyError):
            maintenance.approval(config, self.control, missing_checkbox)
        with patch("otam.web.maintenance.time.time", return_value=time.time() + 301):
            with self.assertRaises(SafetyError):
                maintenance.approval(config, self.control, payload)
        bad = dict(payload, confirmation="wrong")
        with self.assertRaises(SafetyError):
            maintenance.approval(config, self.control, bad)
        with patch(
            "otam.web.maintenance.LinuxMaintenance",
            side_effect=SafetyError("medium changed before lock"),
        ):
            with self.assertRaises(SafetyError):
                maintenance.execute(config, self.control, payload)
        with self.assertRaises(SafetyError):
            maintenance.approval(config, self.control, payload)
        self.assertEqual(
            self.control.get("maintenance_progress:" + grant["id"])["state"], "FAILED"
        )
        self.command("hardware-scan", {})
        with self.assertRaises(SafetyError):
            maintenance.set_mode(config, self.control, "simulator")

    def test_storage_and_maintenance_api_keep_authentication_and_catalog_role_boundaries(
        self,
    ):
        self.assertEqual(self.client.get("/api/v1/directories").status_code, 200)
        path = "/api/v1/storage-resources/" + str(uuid.uuid4())
        data = dict(kind="source", label="Escaping", path="/etc")
        self.assertEqual(self.client.put(path, json=data).status_code, 403)
        self.assertEqual(
            self.client.put(
                path, json=data, headers={"X-CSRF-Token": self.csrf}
            ).status_code,
            409,
        )
        self.assertEqual(
            self.client.put(
                "/api/v1/operation-mode",
                json={"mode": "physical"},
                headers={"X-CSRF-Token": self.csrf},
            ).status_code,
            409,
        )
        cfg, app, client = self.replica()
        try:
            csrf = client.post(
                "/api/v1/login", json={"username": "admin", "password": PASSWORD}
            ).json()["csrf"]
            self.assertEqual(client.get("/api/v1/directories").status_code, 404)
            self.assertEqual(
                client.put(path, json=data, headers={"X-CSRF-Token": csrf}).status_code,
                404,
            )
        finally:
            client.close()

    def test_hardware_status_and_diagnostics_are_authenticated_cached_and_role_bound(
        self,
    ):
        status = self.client.get("/api/v1/hardware/status")
        self.assertEqual(status.status_code, 200)
        self.assertEqual(status.json()["drives"], [])
        ident = "a" * 32
        self.assertEqual(
            self.client.get("/api/v1/hardware/diagnostics/" + ident).status_code, 404
        )
        self.assertEqual(
            self.client.get("/api/v1/hardware/diagnostics/invalid").status_code, 400
        )
        self.control.set(
            "drive_diagnostics:" + ident, {"time": time.time(), "pages": {}}
        )
        self.assertEqual(
            self.client.get("/api/v1/hardware/diagnostics/" + ident).status_code, 200
        )
        from unittest.mock import patch

        with patch(
            "otam.web.diagnostics.discover_drives",
            side_effect=AssertionError("HTTP must not probe devices"),
        ):
            self.assertEqual(
                self.client.get("/api/v1/hardware/status").status_code, 200
            )
            self.assertEqual(self.client.get("/api/v1/hardware").status_code, 200)
        cfg, app, client = self.replica()
        try:
            client.post(
                "/api/v1/login", json={"username": "admin", "password": PASSWORD}
            )
            self.assertEqual(client.get("/api/v1/hardware/status").status_code, 404)
        finally:
            client.close()
        self.client.post("/api/v1/logout", json={}, headers={"X-CSRF-Token": self.csrf})
        self.assertEqual(self.client.get("/api/v1/hardware/status").status_code, 401)


if __name__ == "__main__":
    unittest.main()
