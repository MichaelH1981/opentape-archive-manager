"""Read-only paginated catalog views shared by archive and catalog nodes."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from ..common import SafetyError
from .config import WebConfig
from .control import Control
from .progress import job_progress


class CatalogView:
    def __init__(self, config: WebConfig, control: Control):
        self.config = config
        self.control = control

    def path(self) -> Path | None:
        if self.config.role == "archive":
            return self.config.catalog if self.config.catalog.exists() else None
        active = self.control.get("active_snapshot")
        if not active:
            return None
        name = active["file"]
        if Path(name).name != name:
            raise SafetyError("Ungültiger Snapshot-Verweis")
        path = self.config.state / "snapshots" / name
        if not path.is_file():
            raise SafetyError("Veröffentlichter Katalog-Snapshot fehlt")
        return path

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection | None]:
        path = self.path()
        if path is None:
            yield None
            return
        db = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA query_only=ON")
        db.execute("PRAGMA trusted_schema=OFF")
        db.execute("BEGIN")
        try:
            yield db
        finally:
            db.close()

    def overview(self) -> dict[str, Any]:
        with self.connect() as db:
            if db is None:
                return {
                    "available": False,
                    "media_count": 0,
                    "file_count": 0,
                    "verified_bytes": 0,
                    "archive_count": 0,
                    "verified_count": 0,
                    "running_jobs": 0,
                    "recent": [],
                    "jobs": [],
                }

            def number(sql: str) -> int:
                return db.execute(sql).fetchone()[0] or 0

            return {
                "available": True,
                "media_count": number("SELECT count(*) FROM media"),
                "file_count": number("SELECT count(*) FROM files"),
                "archive_count": number("SELECT count(*) FROM archives"),
                "verified_count": number(
                    "SELECT count(*) FROM archives WHERE state='VERIFIED'"
                ),
                "verified_bytes": number(
                    "SELECT sum(bytes) FROM archives WHERE state='VERIFIED'"
                ),
                "running_jobs": number(
                    "SELECT count(*) FROM jobs WHERE state IN ('RUNNING','PLANNING')"
                ),
                "recent": [
                    dict(r)
                    for r in db.execute(
                        "SELECT a.id,a.state,a.bytes,a.created,m.label FROM archives a JOIN media m ON m.id=a.media_id ORDER BY a.created DESC LIMIT 5"
                    )
                ],
                "jobs": [
                    dict(r)
                    for r in db.execute(
                        "SELECT id,kind,state,phase,updated,error FROM jobs ORDER BY updated DESC LIMIT 5"
                    )
                ],
            }

    def media(self) -> list[dict[str, Any]]:
        with self.connect() as db:
            return (
                []
                if db is None
                else [
                    dict(r)
                    for r in db.execute(
                        """SELECT m.id,m.label,m.class,m.generation,m.capacity,m.manufacturer,m.serial,
                m.first_use,m.last_use,m.writes,m.last_verified,m.location,m.state,m.used,
                (SELECT count(*) FROM archives a WHERE a.media_id=m.id) archive_count FROM media m ORDER BY m.label,m.id"""
                    )
                ]
            )

    def archives(self, limit: int = 100, offset: int = 0) -> dict[str, Any]:
        with self.connect() as db:
            if db is None:
                return {"items": [], "total": 0}
            return {
                "total": db.execute("SELECT count(*) FROM archives").fetchone()[0],
                "items": [
                    dict(r)
                    for r in db.execute(
                        """SELECT a.id,a.media_id,a.job_id,a.tape_file,a.state,a.bytes,a.sha256,a.created,m.label,
                        (SELECT count(*) FROM files f WHERE f.archive_id=a.id) file_count FROM archives a
                        JOIN media m ON m.id=a.media_id ORDER BY a.created DESC,a.id LIMIT ? OFFSET ?""",
                        (limit, offset),
                    )
                ],
            }

    def files(
        self,
        *,
        q: str = "",
        checksum: str = "",
        file_type: str = "",
        media_id: str = "",
        archive_id: str = "",
        min_size: int | None = None,
        max_size: int | None = None,
        after: int | None = None,
        before: int | None = None,
        duplicates: bool = False,
        state: str = "",
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        clauses = ["instr(lower(f.path),lower(?))>0"]
        params: list[Any] = [q]
        for expression, value in [
            ("f.sha256=?", checksum),
            ("lower(f.type)=lower(?)", file_type),
            ("a.media_id=?", media_id),
            ("a.id=?", archive_id),
            ("a.state=?", state),
        ]:
            if value:
                clauses.append(expression)
                params.append(value)
        for expression, value in [
            ("f.size>=?", min_size),
            ("f.size<=?", max_size),
            ("f.mtime_ns>=?", after),
            ("f.mtime_ns<=?", before),
        ]:
            if value is not None:
                clauses.append(expression)
                params.append(value)
        if duplicates:
            clauses.append(
                "EXISTS(SELECT 1 FROM files c WHERE c.sha256=f.sha256 AND c.size=f.size AND (c.archive_id<>f.archive_id OR c.path<>f.path))"
            )
        base = (
            " FROM files f JOIN archives a ON a.id=f.archive_id JOIN media m ON m.id=a.media_id WHERE "
            + " AND ".join(clauses)
        )
        with self.connect() as db:
            if db is None:
                return {"items": [], "total": 0, "limit": limit, "offset": offset}
            total = db.execute("SELECT count(*)" + base, params).fetchone()[0]
            sql = (
                """SELECT f.*,a.media_id,a.tape_file,a.state,a.created,m.label,
                (SELECT count(*) FROM files c WHERE c.sha256=f.sha256 AND c.size=f.size) copies"""
                + base
                + " ORDER BY f.path,a.created DESC,f.archive_id LIMIT ? OFFSET ?"
            )
            return {
                "items": [dict(r) for r in db.execute(sql, [*params, limit, offset])],
                "total": total,
                "limit": limit,
                "offset": offset,
            }

    def jobs(self, limit: int = 100) -> list[dict[str, Any]]:
        with self.connect() as db:
            if db is None:
                return []
            rows = []
            for row in db.execute(
                """SELECT j.id,j.kind,j.state,j.media_id,j.created,j.updated,j.phase,j.error,
                          j.plan_json,m.label FROM jobs j LEFT JOIN media m ON m.id=j.media_id
                   ORDER BY j.created DESC LIMIT ?""", (limit,)
            ):
                item = dict(row)
                plan = json.loads(item.pop("plan_json") or "null")
                item["parent_job"] = plan.get("parent_job") if isinstance(plan, dict) else None
                item['progress'] = job_progress(db,item['id'],plan,item['state'])
                rows.append(item)
            return rows

    def job(self, ident: str) -> dict[str, Any]:
        with self.connect() as db:
            row = (
                None
                if db is None
                else db.execute("SELECT * FROM jobs WHERE id=?", (ident,)).fetchone()
            )
            if row is None:
                raise SafetyError("Job nicht gefunden")
            result = dict(row)
            plan = json.loads(result.pop("plan_json") or "null")
            if isinstance(plan, dict) and "archives" in plan:
                plan = {
                    **plan,
                    "archives": [
                        {k: v for k, v in a.items() if k != "files"}
                        | {
                            "file_count": len(a["files"]),
                            "payload_bytes": sum(f["size"] for f in a["files"]),
                        }
                        for a in plan["archives"]
                    ],
                }
            if isinstance(plan, dict) and "children" in plan:
                plan = {**plan, "children": [
                    {**child, "state": (db.execute(
                        "SELECT state FROM jobs WHERE id=?", (child["job_id"],)
                    ).fetchone() or {"state": "MISSING"})["state"]}
                    for child in plan["children"]
                ]}
            if isinstance(plan,dict) and 'source_entries' in plan:
                plan={k:v for k,v in plan.items() if k not in ('source_entries','inventory_entries','capture_paths')}
            result['progress'] = job_progress(db,ident,plan,result['state'])
            result["plan"] = plan
            result["report"] = json.loads(result.pop("report_json") or "null")
            result["tape_attempted"] = (
                db.execute(
                    "SELECT 1 FROM archives WHERE job_id=? LIMIT 1", (ident,)
                ).fetchone()
                is not None
            )
            result["staging"] = [
                dict(r)
                for r in db.execute(
                    "SELECT job_id,archive_id,phase,state,bytes,progress_bytes,total_bytes,updated,error FROM staged_archives WHERE job_id=? ORDER BY archive_id",
                    (ident,),
                )
            ]
            return result

    def staging(self) -> list[dict[str, Any]]:
        with self.connect() as db:
            return (
                []
                if db is None
                else [
                    dict(r)
                    for r in db.execute(
                        """SELECT s.job_id,s.archive_id,s.phase,s.state,s.bytes,s.progress_bytes,s.total_bytes,s.updated,s.error,
                j.state job_state FROM staged_archives s JOIN jobs j ON j.id=s.job_id ORDER BY s.updated DESC LIMIT 200"""
                    )
                ]
            )

    def events(
        self, job: str = "", limit: int = 100, before: int | None = None
    ) -> list[dict[str, Any]]:
        sql = "SELECT * FROM events WHERE 1=1"
        args: list[Any] = []
        if job:
            sql += " AND job_id=?"
            args.append(job)
        if before:
            sql += " AND seq<?"
            args.append(before)
        with self.connect() as db:
            rows = (
                []
                if db is None
                else [
                    dict(r)
                    for r in db.execute(
                        sql + " ORDER BY seq DESC LIMIT ?", [*args, limit]
                    )
                ]
            )
        for row in rows:
            row["details"] = json.loads(row.pop("details_json"))
        return rows

    def verifications(self) -> list[dict[str, Any]]:
        with self.connect() as db:
            return (
                []
                if db is None
                else [
                    dict(r)
                    for r in db.execute(
                        "SELECT * FROM verifications ORDER BY time DESC LIMIT 100"
                    )
                ]
            )
