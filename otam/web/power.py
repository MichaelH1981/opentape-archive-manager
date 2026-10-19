"""Opt-in, narrowly scoped systemd bridge for an administrator-requested shutdown."""

from __future__ import annotations

import fcntl
import json
import os
import stat
import subprocess
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from ..common import SafetyError, sync_dir
from ..storage import io_lock
from .config import WebConfig
from .control import Control, boot_id


def marker(config: WebConfig) -> Path:
    return config.state / "poweroff.request"


def unit_active() -> bool:
    try:
        return subprocess.run(
            ["/usr/bin/systemctl", "is-active", "--quiet", "otam-poweroff.path"],
            timeout=5, check=False,
        ).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def request(config: WebConfig, control: Control, user_id: str, confirmation: str) -> dict:
    if config.role != "archive" or not config.allow_host_shutdown:
        raise SafetyError("Herunterfahren ist auf diesem Node nicht eingerichtet")
    if confirmation != config.name:
        raise SafetyError("Node-Name zur Bestätigung stimmt nicht überein")
    if not unit_active():
        raise SafetyError("Der geschützte Shutdown-Dienst ist nicht aktiv")
    with io_lock():
        token = control.begin_shutdown(user_id)
    path = marker(config)
    temporary: Path | None = None
    try:
        fd, name = tempfile.mkstemp(prefix=".poweroff-", dir=config.state)
        temporary = Path(name)
        with os.fdopen(fd, "w") as stream:
            json.dump(token, stream, separators=(",", ":"))
            stream.flush()
            os.fsync(stream.fileno())
        # link(2) refuses an existing request; no overwrite or symlink follow.
        os.link(temporary, path)
        sync_dir(config.state)
        return {"state": "REQUESTED", "request_id": token["id"]}
    except BaseException:
        control.clear_shutdown(token["id"])
        raise
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


@contextmanager
def _shared_io_lock(config: WebConfig, owner: int) -> Iterator[None]:
    # The helper's TMPDIR must match the web/worker units. A private 0700
    # directory prevents untrusted users from replacing this lock file.
    folder = Path(os.environ.get("TMPDIR", "")).resolve()
    details = folder.stat()
    if details.st_uid != owner or details.st_mode & 0o077:
        raise SafetyError("Shutdown-I/O-Sperrverzeichnis ist nicht geschützt")
    path = folder / f"otam-io-{owner}.lock"
    flags = os.O_RDWR | os.O_NOFOLLOW
    try:
        fd = os.open(path, flags | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        fd = os.open(path, flags)
    else:
        os.fchown(fd, owner, details.st_gid)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != owner or info.st_mode & 0o077:
            raise SafetyError("Unsichere Shutdown-I/O-Sperre")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise SafetyError("I/O-Auftrag aktiv; Herunterfahren abgebrochen") from error
        yield
    finally:
        os.close(fd)


def execute(config: WebConfig, control: Control) -> None:
    """Run only as root from the fixed otam-poweroff.service unit."""
    if os.geteuid() != 0 or config.role != "archive" or not config.allow_host_shutdown:
        raise SafetyError("Shutdown-Helfer benötigt root und ausdrückliche Node-Freigabe")
    path = marker(config)
    owner = control.path.stat().st_uid
    request_id = ""
    worker_stopped = False
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, "r") as stream:
            info = os.fstat(stream.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != owner
                    or info.st_mode & 0o077 or not 1 <= info.st_size <= 4096):
                raise SafetyError("Ungültige Shutdown-Anforderung")
            token = json.load(stream)
        if set(token) != {"id", "boot_id", "user_id", "time"}:
            raise SafetyError("Ungültige Shutdown-Anforderung")
        request_id = token["id"]
        pending = control.get("shutdown_pending", {})
        if (pending != token or token["boot_id"] != boot_id()
                or time.time() - token["time"] > 60):
            raise SafetyError("Shutdown-Anforderung abgelaufen oder verändert")
        # Consume before any systemctl call: a reboot must not replay the marker.
        path.unlink()
        sync_dir(config.state)
        with _shared_io_lock(config, owner):
            with control.connect() as db:
                active = db.execute("SELECT 1 FROM commands WHERE state='RUNNING' LIMIT 1").fetchone()
            if active:
                raise SafetyError("Ein OTAM-Auftrag läuft; Herunterfahren abgebrochen")
            subprocess.run(
                ["/usr/bin/systemctl", "stop", "otam-worker.service"],
                check=True, timeout=30,
            )
            worker_stopped = True
            with control.connect() as db:
                active = db.execute("SELECT 1 FROM commands WHERE state='RUNNING' LIMIT 1").fetchone()
            if active:
                raise SafetyError("Worker hat noch einen aktiven Auftrag")
            control.set("shutdown_status", {"state": "POWERING_OFF", "time": time.time(),
                                            "request_id": request_id})
            subprocess.run(["/usr/bin/systemctl", "poweroff", "--no-wall"],
                           check=True, timeout=15)
    except BaseException as error:
        path.unlink(missing_ok=True)
        if request_id:
            control.clear_shutdown(request_id)
        control.set("shutdown_status", {"state": "FAILED", "time": time.time(),
                                        "error": str(error)})
        if worker_stopped:
            subprocess.run(["/usr/bin/systemctl", "start", "otam-worker.service"],
                           check=False, timeout=30)
        raise


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="OTAM fixed-action poweroff helper")
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    config = WebConfig.load(args.config)
    execute(config, Control(config.state))


if __name__ == "__main__":
    main()
