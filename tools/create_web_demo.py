"""Create a NEW simulator-only demonstration using synthetic regular files."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from otam.web.config import initialize, WebConfig
from otam.web.control import Control
from otam.web.worker import execute


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    parser.add_argument("--password-file", type=Path, required=True)
    args = parser.parse_args()
    root = args.directory.resolve()
    root.mkdir(parents=True, exist_ok=False, mode=0o700)
    source = root / "synthetic-source"
    source.mkdir()
    groups = {
        "Fotografien/2024/Alpen": [
            "Bergsee_001.jpg",
            "Sonnenaufgang_002.jpg",
            "Panorama_003.raw",
        ],
        "Dokumente/Haus": ["Grundriss.pdf", "Versicherung_2024.pdf", "Inventar.csv"],
        "Familie/Erinnerungen": [
            "Sommerfest_2023.mp4",
            "Reisetagebuch.txt",
            "Familienarchiv.json",
        ],
    }
    for group, files in groups.items():
        folder = source / group
        folder.mkdir(parents=True)
        for name in files:
            # Extensions illustrate a private archive; contents are explicitly synthetic.
            (folder / name).write_bytes(
                ("OTAM SIMULATOR DEMO — synthetic data: " + name + "\n").encode() * 2500
            )
    password = args.password_file.read_text().rstrip("\r\n")
    initialize(root / "node.json", root / "archive-node", "archive", password, [source])
    data = json.loads((root / "node.json").read_text())
    data["name"] = "OTAM · Simulator-Vorschau"
    data["sources"][0]["label"] = "Beispieldaten (synthetisch)"
    (root / "node.json").write_text(json.dumps(data, indent=2) + "\n")
    config = WebConfig.load(root / "node.json")
    control = Control(config.state)
    medium = execute(config, control, "create-medium", {"label": "FAMILIE · TEST-001"})
    plan = execute(
        config,
        control,
        "plan",
        {"media_id": medium["media_id"], "source_id": "source-1"},
    )
    execute(
        config,
        control,
        "backup",
        {
            "job_id": plan["job_id"],
            "confirm": plan["job_id"],
            "plan_hash": plan["sha256"],
        },
    )
    (source / "Dokumente/Haus/Inventar.csv").write_text(
        "OTAM synthetic updated inventory\n" * 2000
    )
    next_plan = execute(
        config,
        control,
        "plan",
        {"media_id": medium["media_id"], "source_id": "source-1"},
    )
    execute(config, control, "stage", {"job_id": next_plan["job_id"]})
    execute(config, control, "create-medium", {"label": "DOKUMENTE · TEST-002"})
    print(
        json.dumps(
            {
                "config": str(root / "node.json"),
                "role": "archive",
                "synthetic_only": True,
            }
        )
    )


if __name__ == "__main__":
    main()
