from __future__ import annotations

import io
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from otam.archive import add_bytes, metadata_tar, verify_archive
from otam.catalog import Catalog
from otam.cli import main
from otam.common import SafetyError, encode, sha256
from otam.service import ArchiveService, scan
from otam.tape import LinuxTape, SimulatedTape


class Workflows(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(dir=os.environ.get("OTAM_TEST_TMPDIR", "/var/tmp" if sys.platform.startswith("linux") else None))
        self.base = Path(self.temp.name).resolve()
        self.source = self.base / "source"
        self.source.mkdir()
        (self.source / "nested").mkdir()
        (self.source / "nested" / "picture ü\n.jpg").write_bytes(bytes(range(256)) * 12)
        (self.source / "empty").write_bytes(b"")
        (self.source / "notes.txt").write_bytes(b"long term archive\n")
        self.tape = SimulatedTape.create(self.base / "medium", "TEST-A", 10_000_000)
        self.catalog = Catalog(self.base / "catalog.sqlite")
        self.service = ArchiveService(self.catalog, self.tape)
        self.media = self.service.register()["media_id"]
        self.spool = self.base / "spool"

    def tearDown(self) -> None:
        self.catalog.close()
        self.temp.cleanup()

    def backup(self, target: int = 75000000000) -> dict:
        plan = self.service.plan(self.source, self.media, target)
        return self.service.backup(plan["job_id"], plan["job_id"], self.spool)

    def test_full_cycle_append_restore_and_tar_compatibility(self) -> None:
        before = {p.relative_to(self.source): sha256(p) for p in self.source.rglob("*") if p.is_file()}
        first = self.backup()
        self.assertEqual(first["state"], "VERIFIED")
        with self.tape.locked():
            header_hash = sha256(self.tape.read(0))
            data_hash = sha256(self.tape.read(1))
        (self.source / "new.txt").write_text("another version")
        second = self.backup()
        with self.tape.locked():
            self.assertEqual(sha256(self.tape.read(0)), header_hash)
            self.assertEqual(sha256(self.tape.read(1)), data_hash)
            self.assertEqual(self.tape.positions(), [0, 1, 2, 3, 4])
        target = self.base / "restore"
        report = self.service.restore(self.media, target, archive_id=first["archives"][0])
        self.assertEqual(report["files"], 3)
        for name, checksum in before.items():
            self.assertEqual(sha256(target / name), checksum)
            self.assertEqual(sha256(self.source / name), checksum)
        self.assertEqual(self.service.verify(self.media)["archives"], 2)
        run = subprocess.run(["tar", "-tf", str(self.tape.path / "00000001.tar")],
                             capture_output=True, check=True)
        self.assertIn(b"OTAM/manifest.json", run.stdout)
        # Independent tar extraction of a controlled safe archive.
        independent = self.base / "independent"
        independent.mkdir()
        subprocess.run(["tar", "-xf", str(self.tape.path / "00000001.tar"), "-C", str(independent)], check=True)
        for name, checksum in before.items():
            self.assertEqual(sha256(independent / "data" / name), checksum)
        self.assertNotEqual(second["job_id"], first["job_id"])

    def test_plan_requires_exact_confirmation_and_single_execution(self) -> None:
        plan = self.service.plan(self.source, self.media)
        with self.assertRaises(SafetyError):
            self.service.backup(plan["job_id"], "yes", self.spool)
        self.service.backup(plan["job_id"], plan["job_id"], self.spool)
        with self.assertRaises(SafetyError):
            self.service.backup(plan["job_id"], plan["job_id"], self.spool)

    def test_stale_plan_and_tampered_plan(self) -> None:
        plan = self.service.plan(self.source, self.media)
        other = self.service.plan(self.source, self.media)
        self.service.backup(other["job_id"], other["job_id"], self.spool)
        with self.assertRaises(SafetyError):
            self.service.backup(plan["job_id"], plan["job_id"], self.spool)
        with self.catalog.db:
            self.catalog.db.execute("UPDATE jobs SET plan_json=replace(plan_json,'notes.txt','fraud.txt') WHERE id=?", (plan["job_id"],))
        with self.assertRaises(SafetyError):
            self.service.backup(plan["job_id"], plan["job_id"], self.spool)

    def test_source_changed_after_planning(self) -> None:
        plan = self.service.plan(self.source, self.media)
        file = self.source / "notes.txt"
        old = file.stat()
        file.write_bytes(b"x" * old.st_size)
        os.utime(file, ns=(old.st_atime_ns, old.st_mtime_ns))
        with self.assertRaises(SafetyError):
            self.service.backup(plan["job_id"], plan["job_id"], self.spool)
        with self.tape.locked():
            self.assertEqual(self.tape.positions(), [0])
        self.assertEqual(self.catalog.db.execute("SELECT state FROM jobs WHERE id=?", (plan["job_id"],)).fetchone()[0], "FAILED")

    def test_wrong_medium_and_lock(self) -> None:
        other = SimulatedTape.create(self.base / "other", "OTHER", 10_000_000)
        with self.assertRaises(SafetyError):
            ArchiveService(self.catalog, other).plan(self.source, self.media)
        with self.tape.locked():
            with self.assertRaises(SafetyError):
                with SimulatedTape(self.tape.path).locked():
                    pass
            data = self.base / "dummy"
            data.write_bytes(b"foo")
            with self.assertRaises(SafetyError):
                self.tape.append(data, "wrong-id")

    def test_write_failure_and_restart_never_verified(self) -> None:
        plan = self.service.plan(self.source, self.media)
        faulty = SimulatedTape(self.tape.path, fail_after=1200)
        with self.assertRaises(OSError):
            ArchiveService(self.catalog, faulty).backup(plan["job_id"], plan["job_id"], self.spool)
        self.assertTrue(faulty.has_partial())
        state = self.catalog.db.execute("SELECT state FROM archives").fetchone()[0]
        self.assertEqual(state, "INCOMPLETE")
        restarted = ArchiveService(self.catalog, SimulatedTape(self.tape.path))
        with self.assertRaises(SafetyError):
            restarted.plan(self.source, self.media)
        self.assertEqual(self.catalog.db.execute("SELECT state FROM jobs WHERE id=?", (plan["job_id"],)).fetchone()[0], "FAILED")

    def test_interrupted_write(self) -> None:
        plan = self.service.plan(self.source, self.media)
        faulty = SimulatedTape(self.tape.path, interrupt_after=700)
        with self.assertRaises(KeyboardInterrupt):
            ArchiveService(self.catalog, faulty).backup(plan["job_id"], plan["job_id"], self.spool)
        self.assertEqual(self.catalog.db.execute("SELECT state FROM jobs WHERE id=?", (plan["job_id"],)).fetchone()[0], "INTERRUPTED")
        self.assertTrue(faulty.has_partial())

    def test_read_failure_blocks_receipt(self) -> None:
        plan = self.service.plan(self.source, self.media)
        faulty = SimulatedTape(self.tape.path, read_error=1)
        with self.assertRaises(OSError):
            ArchiveService(self.catalog, faulty).backup(plan["job_id"], plan["job_id"], self.spool)
        with self.tape.locked():
            self.assertEqual(self.tape.positions(), [0, 1])
        self.assertEqual(self.catalog.db.execute("SELECT state FROM archives").fetchone()[0], "INCOMPLETE")

    def test_receipt_write_failure_blocks_commit(self) -> None:
        plan = self.service.plan(self.source, self.media)
        original = self.tape.append
        def append(path, media):
            if path.name.startswith("receipt-"):
                self.tape.fail_after = 20
            return original(path, media)
        with patch.object(self.tape, "append", side_effect=append):
            with self.assertRaises(OSError):
                self.service.backup(plan["job_id"], plan["job_id"], self.spool)
        self.assertTrue(self.tape.has_partial())
        self.assertEqual(self.catalog.db.execute("SELECT state FROM archives").fetchone()[0], "INCOMPLETE")

    def test_capacity_and_no_archive_splitting(self) -> None:
        plan = self.service.plan(self.source, self.media, target=1000)
        self.assertEqual(len(plan["archives"]), 3)
        self.assertTrue(any(sum(e["size"] for e in m["files"]) > 1000 for m in plan["archives"]))
        tiny = SimulatedTape.create(self.base / "tiny", "TINY", 32768)
        service = ArchiveService(self.catalog, tiny)
        media = service.register()["media_id"]
        with self.assertRaises(SafetyError):
            service.plan(self.source, media)
        data = self.base / "oversize"
        data.write_bytes(b"x" * 32768)
        with tiny.locked():
            with self.assertRaises(SafetyError):
                tiny.append(data, media)
            self.assertEqual(tiny.positions(), [0])

    def test_selected_files_and_subdirectory_are_only_inventory(self) -> None:
        plan = self.service.plan(self.source, self.media, selected=["notes.txt", "nested"])
        paths = [entry["path"] for archive in plan["archives"] for entry in archive["files"]]
        self.assertEqual(paths, ["nested/picture ü\n.jpg", "notes.txt"])
        self.assertNotIn("empty", paths)
        self.assertEqual(plan["selected_paths"], ["nested", "notes.txt"])
        result = self.service.backup(plan["job_id"], plan["job_id"], self.spool)
        self.assertEqual(result["state"], "VERIFIED")
        self.assertEqual(result["files"], 2)
        for selection in (["../notes.txt"], ["missing.txt"], []):
            with self.assertRaises(SafetyError):
                self.service.plan(self.source, self.media, selected=selection)

    def test_deferred_media_verification_reads_all_before_commit(self) -> None:
        plan = self.service.plan(self.source, self.media, target=1000, verify_mode="media")
        self.assertGreater(len(plan["archives"]), 1)
        result = self.service.backup(plan["job_id"], plan["job_id"], self.spool)
        self.assertEqual(result["state"], "VERIFIED")
        self.assertEqual(result["verification"], "media")
        self.assertEqual(len(result["archives"]), len(plan["archives"]))
        self.assertEqual(self.service.verify(self.media)["archives"], len(plan["archives"]))

    def test_deferred_read_error_never_claims_verified(self) -> None:
        plan = self.service.plan(self.source, self.media, target=1000, verify_mode="media")
        with patch.object(self.tape, "open_read", side_effect=OSError("readback failed")):
            with self.assertRaises(OSError):
                self.service.backup(plan["job_id"], plan["job_id"], self.spool)
        self.assertGreater(len(self.tape.positions()), 1)
        self.assertEqual(self.catalog.db.execute(
            "SELECT count(*) FROM archives WHERE job_id=? AND state='VERIFIED'", (plan["job_id"],)
        ).fetchone()[0], 0)
        self.assertEqual(self.catalog.db.execute(
            "SELECT state FROM jobs WHERE id=?", (plan["job_id"],)
        ).fetchone()[0], "FAILED")
        self.assertTrue(any(self.spool.rglob("*.tar")))

    def test_deferred_resume_after_cleanup_crash_does_not_rewrite(self) -> None:
        from otam.staging import StagingStore

        plan = self.service.plan(self.source, self.media, target=1000, verify_mode="media")
        original_cleanup = StagingStore.cleanup
        calls = 0

        def interrupted_cleanup(store, job, archive):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("simulated crash during cleanup")
            return original_cleanup(store, job, archive)

        with patch.object(StagingStore, "cleanup", interrupted_cleanup):
            with self.assertRaises(OSError):
                self.service.backup(plan["job_id"], plan["job_id"], self.spool)
        before = self.tape.positions()
        report = self.service.backup(plan["job_id"], plan["job_id"], self.spool, resume=True)
        self.assertEqual(report["state"], "VERIFIED")
        self.assertEqual(self.tape.positions(), before)
        self.assertEqual(self.catalog.db.execute(
            "SELECT count(*) FROM archives WHERE job_id=? AND state='VERIFIED'",
            (plan["job_id"],)).fetchone()[0], len(plan["archives"]))

    def test_unexpected_end_of_medium_marks_incomplete(self) -> None:
        plan = self.service.plan(self.source, self.media)
        with patch.object(self.tape, "append", side_effect=SafetyError("Injected EOM")):
            with self.assertRaises(SafetyError):
                self.service.backup(plan["job_id"], plan["job_id"], self.spool)
        self.assertEqual(self.catalog.db.execute("SELECT state FROM archives").fetchone()[0], "INCOMPLETE")

    def test_corruption_demotes_verified_and_restore_fails(self) -> None:
        self.backup()
        path = self.tape.path / "00000001.tar"
        with path.open("r+b") as f:
            f.seek(2000)
            f.write(b"CORRUPT")
        with self.assertRaises(SafetyError):
            self.service.verify(self.media)
        self.assertEqual(self.catalog.db.execute("SELECT state FROM archives").fetchone()[0], "SUSPECT")
        with self.assertRaises(SafetyError):
            self.service.restore(self.media, self.base / "bad-restore")

    def test_catalog_loss_rebuild_and_restore(self) -> None:
        self.backup(target=1000)
        self.catalog.close()
        self.catalog = Catalog(self.base / "fresh.sqlite")
        self.service = ArchiveService(self.catalog, self.tape)
        report = self.service.rebuild(self.media)
        self.assertEqual(report["archives"], 3)
        self.assertFalse(report["incomplete_tail"])
        self.assertEqual(len(self.catalog.search()), 3)
        self.assertEqual(self.service.restore(self.media, self.base / "recovered")["files"], 3)

    def test_catalog_loss_rebuilds_deferred_receipts_by_reading_data(self) -> None:
        plan = self.service.plan(self.source, self.media, target=1000, verify_mode="media")
        self.service.backup(plan["job_id"], plan["job_id"], self.spool)
        self.catalog.close()
        self.catalog = Catalog(self.base / "deferred-rebuilt.sqlite")
        self.service = ArchiveService(self.catalog, self.tape)
        report = self.service.rebuild(self.media)
        self.assertEqual(report["archives"], len(plan["archives"]))
        self.assertEqual(len(self.catalog.search()), 3)
        self.assertEqual(self.service.restore(self.media, self.base / "deferred-restored")["files"], 3)

    def test_restore_reads_archive_as_stream_without_local_tape_copy(self) -> None:
        self.backup()
        original_read = self.tape.read

        def metadata_only(position: int) -> Path:
            if position % 2:
                raise AssertionError("Data archive must use the streaming API")
            return original_read(position)

        @contextmanager
        def open_read(position: int):
            with (self.tape.path / f"{position:08d}.tar").open("rb") as stream:
                yield stream

        self.tape.read = metadata_only  # type: ignore[method-assign]
        self.tape.open_read = open_read  # type: ignore[method-assign]
        report = self.service.restore(self.media, self.base / "stream-restored")
        self.assertEqual(report["files"], 3)
        self.assertEqual(
            sha256(self.base / "stream-restored" / "notes.txt"),
            sha256(self.source / "notes.txt"),
        )

    def test_rebuild_preserves_prior_pairs_with_incomplete_tail(self) -> None:
        first = self.backup()
        plan = self.service.plan(self.source, self.media)
        faulty = SimulatedTape(self.tape.path, interrupt_after=500)
        with self.assertRaises(KeyboardInterrupt):
            ArchiveService(self.catalog, faulty).backup(plan["job_id"], plan["job_id"], self.spool)
        fresh = Catalog(self.base / "fresh.sqlite")
        try:
            service = ArchiveService(fresh, self.tape)
            report = service.rebuild(self.media)
            self.assertTrue(report["incomplete_tail"])
            self.assertEqual(report["archives"], 1)
            self.assertEqual(service.restore(self.media, self.base / "previous", archive_id=first["archives"][0])["files"], 3)
        finally:
            fresh.close()

    def test_hard_crash_recovery_and_no_duplicate_append(self) -> None:
        plan = self.service.plan(self.source, self.media)
        real_finish = self.catalog.finish
        def crash_on_finish(job, state, error=None, report=None):
            if state == "VERIFIED":
                raise SystemExit("Simulated process death before job result")
            real_finish(job, state, error, report)
        with patch.object(self.catalog, "finish", side_effect=crash_on_finish):
            with self.assertRaises(SystemExit):
                self.service.backup(plan["job_id"], plan["job_id"], self.spool)
        # Emulate unhandled SIGKILL leaving the job RUNNING.
        with self.catalog.db:
            self.catalog.db.execute("UPDATE jobs SET state='RUNNING' WHERE id=?", (plan["job_id"],))
        self.assertEqual(self.service.recover_jobs(self.media), 1)
        with self.assertRaises(SafetyError):
            self.service.backup(plan["job_id"], plan["job_id"], self.spool)
        self.service.rebuild(self.media)
        with self.tape.locked():
            self.assertEqual(self.tape.positions(), [0, 1, 2])

    def test_actual_process_death_after_receipt_is_recoverable(self) -> None:
        plan = self.service.plan(self.source, self.media)
        script = """
import os, sys
from pathlib import Path
from otam.catalog import Catalog
from otam.service import ArchiveService
from otam.tape import SimulatedTape
class CrashTape(SimulatedTape):
    def append(self, source, expected_media):
        position = super().append(source, expected_media)
        if source.name.startswith('receipt-'):
            os._exit(91)
        return position
catalog = Catalog(Path(sys.argv[1]))
ArchiveService(catalog, CrashTape(Path(sys.argv[2]))).backup(sys.argv[3], sys.argv[3], Path(sys.argv[4]))
"""
        import sys
        run = subprocess.run([sys.executable, "-c", script, str(self.catalog.path), str(self.tape.path),
                              plan["job_id"], str(self.spool)], capture_output=True)
        self.assertEqual(run.returncode, 91, run.stderr)
        self.assertEqual(self.catalog.db.execute("SELECT state FROM jobs WHERE id=?", (plan["job_id"],)).fetchone()[0], "RUNNING")
        self.assertEqual(self.catalog.db.execute("SELECT state FROM archives").fetchone()[0], "WRITING")
        self.assertEqual(self.service.recover_jobs(self.media), 1)
        self.assertEqual(self.service.rebuild(self.media)["archives"], 1)
        self.assertEqual(self.catalog.db.execute("SELECT state FROM archives").fetchone()[0], "VERIFIED")
        self.assertEqual(self.service.restore(self.media, self.base / "after-crash")["files"], 3)

    def test_restore_missing_requested_path_is_reported(self) -> None:
        self.backup()
        with self.assertRaises(SafetyError):
            self.service.restore_plan(self.media, ["notes.txt", "missing-file"])

    def test_restore_no_overwrite_and_no_symlink_traversal(self) -> None:
        self.backup()
        target = self.base / "restore"
        self.service.restore(self.media, target)
        original = (target / "notes.txt").read_bytes()
        with self.assertRaises(FileExistsError):
            self.service.restore(self.media, target)
        self.assertEqual((target / "notes.txt").read_bytes(), original)
        outside = self.base / "outside"
        outside.mkdir()
        link_target = self.base / "link-restore"
        link_target.mkdir()
        (link_target / "nested").symlink_to(outside, target_is_directory=True)
        with self.assertRaises(OSError):
            self.service.restore(self.media, link_target, ["nested"])
        self.assertEqual(list(outside.iterdir()), [])
        parent_link = self.base / "parent-link"
        parent_link.symlink_to(outside, target_is_directory=True)
        with self.assertRaises(OSError):
            self.service.restore(self.media, parent_link / "new")
        self.assertEqual(list(outside.iterdir()), [])

    def test_unsafe_tar_members_and_missing_files(self) -> None:
        plan = self.service.plan(self.source, self.media)
        manifest = plan["archives"][0]
        for name, typeflag in (("data/../outside", tarfile.REGTYPE), ("/absolute", tarfile.REGTYPE),
                               ("data/link", tarfile.SYMTYPE), ("data/device", tarfile.CHRTYPE)):
            with self.subTest(name=name):
                path = self.base / "evil.tar"
                with tarfile.open(path, "w") as tar:
                    add_bytes(tar, "OTAM/manifest.json", encode(manifest))
                    info = tarfile.TarInfo(name)
                    info.type = typeflag
                    info.linkname = "../../outside"
                    tar.addfile(info)
                with self.assertRaises(SafetyError):
                    verify_archive(path)
        missing = self.base / "missing.tar"
        metadata_tar(missing, "OTAM/manifest.json", manifest)
        with self.assertRaises(SafetyError):
            verify_archive(missing)

    def test_symlink_source_rejected_and_unknown_media_readonly(self) -> None:
        (self.source / "link").symlink_to(self.source / "notes.txt")
        with self.assertRaises(OSError):
            self.service.plan(self.source, self.media)
        (self.source / "link").unlink()
        with self.catalog.db:
            self.catalog.db.execute("UPDATE media SET state='ARCHIVED' WHERE id=?", (self.media,))
        with self.assertRaises(SafetyError):
            self.service.plan(self.source, self.media)
        self.service.rebuild(self.media)
        self.assertEqual(self.catalog.db.execute("SELECT state FROM media").fetchone()[0], "ARCHIVED")

    def test_sequence_gap_and_receipt_chain(self) -> None:
        self.backup()
        receipt = self.tape.path / "00000002.tar"
        receipt.rename(self.tape.path / "00000004.tar")
        with self.tape.locked():
            with self.assertRaises(SafetyError):
                self.tape.positions()
        (self.tape.path / "00000004.tar").rename(receipt)
        with self.tape.locked():
            from otam.archive import read_metadata
            value = read_metadata(receipt, "receipt.json")
        value["previous"] = "0" * 64
        metadata_tar(receipt, "receipt.json", value)
        with self.assertRaises(SafetyError):
            self.service.verify(self.media)

    def test_real_device_and_reinitialization_blocked(self) -> None:
        with self.assertRaises(SafetyError):
            LinuxTape(Path("/dev/nst0"))
        with self.assertRaises(SafetyError):
            SimulatedTape.create(Path("/dev/nst0"), "NO", 100000)
        with self.assertRaises(FileExistsError):
            SimulatedTape.create(self.tape.path, "NO", 100000)
        with self.assertRaises(SafetyError):
            SimulatedTape(self.source)

    def test_standalone_recovery_without_application_imports(self) -> None:
        self.backup()
        import sys
        utility = Path(__file__).resolve().parents[1] / "tools" / "recover_tar.py"
        target = self.base / "standalone"
        run = subprocess.run([sys.executable, "-I", str(utility), str(self.tape.path / "00000001.tar"),
                              str(self.tape.path / "00000002.tar"), str(target)],
                             cwd=self.base, capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(json.loads(run.stdout)["restored_verified_files"], 3)
        self.assertEqual((target / "notes.txt").read_bytes(), (self.source / "notes.txt").read_bytes())
        repeat = subprocess.run([sys.executable, "-I", str(utility), str(self.tape.path / "00000001.tar"),
                                 str(self.tape.path / "00000002.tar"), str(target)], capture_output=True)
        self.assertNotEqual(repeat.returncode, 0)

    def test_rebuild_is_atomic_on_catalog_conflict(self) -> None:
        self.backup(target=1000)
        with self.tape.locked():
            found = scan(self.tape, self.media)
        fresh = Catalog(self.base / "atomic.sqlite")
        try:
            service = ArchiveService(fresh, self.tape)
            service.register()
            job = fresh.job("test", self.media)
            import copy
            wrong = copy.deepcopy(found[-1]["manifest"])
            wrong["created"] += 100
            fresh.record_archive(wrong, job, found[-1]["position"], "INCOMPLETE")
            with self.assertRaises(SafetyError):
                service.rebuild(self.media)
            self.assertEqual(fresh.db.execute("SELECT count(*) FROM archives").fetchone()[0], 1)
        finally:
            fresh.close()

    def test_restore_cannot_write_into_medium(self) -> None:
        self.backup()
        with self.assertRaises(SafetyError):
            self.service.restore(self.media, self.tape.path / "restore")

    def test_schema_future_version_rejected(self) -> None:
        future = self.base / "future.sqlite"
        db = sqlite3.connect(future)
        db.execute("PRAGMA user_version=99")
        db.close()
        with self.assertRaises(SafetyError):
            Catalog(future)

    def test_search_copies_and_export(self) -> None:
        self.backup()
        self.backup()
        rows = self.catalog.search("notes.txt")
        self.assertEqual(len(rows), 2)
        self.assertEqual(len(self.catalog.search(checksum=rows[0]["sha256"])), 2)
        self.assertEqual(self.catalog.export()["schema_version"], 2)
        output = io.StringIO()
        with patch("sys.stdout", output):
            self.assertEqual(main(["--db", str(self.catalog.path), "export", "--format", "csv"]), 0)
        self.assertIn("notes.txt", output.getvalue())

    def test_source_catalog_overlap_blocked(self) -> None:
        with self.assertRaises(SafetyError):
            self.service.plan(self.base, self.media)


if __name__ == "__main__":
    unittest.main()
