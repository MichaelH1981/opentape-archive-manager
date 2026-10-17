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
        self.assertEqual(second["state"], "UNCHANGED")
        self.assertEqual(first["sequence"], second["sequence"])

    def test_sync_failure_preserves_catalog_and_records_error(self):
        from otam.web.replication import push

        config = replace(self.config, peer_url="https://catalog.invalid")
        with patch("httpx.Client.put", side_effect=OSError("offline")):
            with self.assertRaises(OSError):
                push(config, self.control)
        self.assertTrue(config.catalog.exists())
        with self.control.connect() as db:
            self.assertEqual(
                db.execute(
                    "SELECT state FROM sync_log ORDER BY id DESC LIMIT 1"
                ).fetchone()[0],
                "FAILED",
            )
        self.assertIsNone(self.control.get("last_push"))


if __name__ == "__main__":
    unittest.main()
