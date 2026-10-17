"""Read-only environment discovery; no devices are opened or repositioned."""
from __future__ import annotations

import glob
import platform
import shutil
import subprocess
from pathlib import Path
from typing import Any


def discover() -> dict[str, Any]:
    result: dict[str, Any] = {"system": platform.system(), "kernel": platform.release(),
                              "machine": platform.machine(), "python": platform.python_version(),
                              "real_tape_writes": "disabled_pending_hardware_acceptance"}
    release = Path("/etc/os-release")
    result["os_release"] = release.read_text() if release.exists() else None
    result["tools"] = {name: shutil.which(name) for name in
                       ("tar", "mt", "mbuffer", "lsscsi", "lspci", "sg_inq", "sg_logs", "smartctl")}
    result["tar_version"] = None
    if result["tools"]["tar"]:
        try:
            run = subprocess.run([result["tools"]["tar"], "--version"], capture_output=True,
                                 text=True, timeout=5, check=False)
            result["tar_version"] = run.stdout.splitlines()[:1]
        except (OSError, subprocess.TimeoutExpired) as error:
            result["tar_version"] = str(error)
    result["devices"] = sorted(glob.glob("/dev/nst[0-9]*"))
    result["tape_sysfs"] = []
    for name in sorted(glob.glob("/sys/class/scsi_tape/nst*")):
        entry: dict[str, Any] = {"sysfs": name, "device_path": str((Path(name) / "device").resolve())}
        for attr in ("vendor", "model", "rev", "serial", "type"):
            path = Path(name) / "device" / attr
            try:
                entry[attr] = path.read_text().strip()
            except OSError:
                entry[attr] = None
        result["tape_sysfs"].append(entry)
    result["scsi_hosts"] = []
    for name in sorted(glob.glob("/sys/class/scsi_host/host*")):
        driver = Path(name) / "proc_name"
        try:
            result["scsi_hosts"].append({"host": name, "driver": driver.read_text().strip()})
        except OSError:
            result["scsi_hosts"].append({"host": name, "driver": None})
    return result
