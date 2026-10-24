"""Repository helpers for CaliClaw contracts."""
from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path
from typing import Any, Optional

from .db import connect
from .models import (
    Artifact,
    Event,
    Profile,
    Project,
    Revision,
    Run,
    RunAttempt,
    from_json,
    to_json,
    utc_now,
)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def create_project(conn_or_path, name: str, description: str | None = None) -> Project:
    project = Project(name=name, description=description)
    with _connection(conn_or_path) as conn:
        conn.execute(
            "INSERT INTO projects (id,name,description,created_at,updated_at) VALUES (?,?,?,?,?)",
            (project.id, project.name, project.description, project.created_at, project.updated_at),
        )
    return project


def get_project(conn_or_path, project_id: str) -> Optional[Project]:
    with _connection(conn_or_path) as conn:
        row = conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
    if not row:
        return None
    return Project(
        id=row["id"], name=row["name"], description=row["description"],
        created_at=row["created_at"], updated_at=row["updated_at"],
    )


def create_revision(conn_or_path, revision: Revision) -> Revision:
    with _connection(conn_or_path) as conn:
        conn.execute(
            """INSERT INTO revisions
            (id,project_id,parent_id,requirements_json,assumptions_json,params_json,source_hash,artifact_id,validation_json,run_id,created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                revision.id, revision.project_id, revision.parent_id,
                to_json(revision.requirements), to_json(revision.assumptions),
                to_json(revision.params), revision.source_hash, revision.artifact_id,
                to_json(revision.validation), revision.run_id, revision.created_at,
            ),
        )
    return revision


def get_revision(conn_or_path, revision_id: str) -> Optional[Revision]:
    with _connection(conn_or_path) as conn:
        row = conn.execute("SELECT * FROM revisions WHERE id=?", (revision_id,)).fetchone()
    if not row:
        return None
    return Revision(
        id=row["id"], project_id=row["project_id"], parent_id=row["parent_id"],
        requirements=from_json(row["requirements_json"], {}),
        assumptions=from_json(row["assumptions_json"], []),
        params=from_json(row["params_json"], {}),
        source_hash=row["source_hash"], artifact_id=row["artifact_id"],
        validation=from_json(row["validation_json"], {}),
        run_id=row["run_id"], created_at=row["created_at"],
    )


def list_revisions(conn_or_path, project_id: str) -> list[Revision]:
    with _connection(conn_or_path) as conn:
        rows = conn.execute(
            "SELECT * FROM revisions WHERE project_id=? ORDER BY created_at", (project_id,)
        ).fetchall()
    return [get_revision(conn_or_path, r["id"]) for r in rows]  # type: ignore[misc]


def create_artifact(conn_or_path, artifact: Artifact) -> Artifact:
    with _connection(conn_or_path) as conn:
        conn.execute(
            """INSERT INTO artifacts (id,revision_id,kind,path,sha256,bytes,metadata_json,created_at)
            VALUES (?,?,?,?,?,?,?,?)""",
            (
                artifact.id, artifact.revision_id, artifact.kind, artifact.path,
                artifact.sha256, artifact.bytes, to_json(artifact.metadata), artifact.created_at,
            ),
        )
    return artifact


def get_artifact(conn_or_path, artifact_id: str) -> Optional[Artifact]:
    with _connection(conn_or_path) as conn:
        row = conn.execute("SELECT * FROM artifacts WHERE id=?", (artifact_id,)).fetchone()
    if not row:
        return None
    return Artifact(
        id=row["id"], revision_id=row["revision_id"], kind=row["kind"],
        path=row["path"], sha256=row["sha256"], bytes=row["bytes"],
        metadata=from_json(row["metadata_json"], {}), created_at=row["created_at"],
    )


def create_profile(conn_or_path, profile: Profile) -> Profile:
    with _connection(conn_or_path) as conn:
        conn.execute(
            """INSERT INTO profiles (id,name,kind,path,sha256,metadata_json,created_at)
            VALUES (?,?,?,?,?,?,?)""",
            (
                profile.id, profile.name, profile.kind, profile.path,
                profile.sha256, to_json(profile.metadata), profile.created_at,
            ),
        )
    return profile


def record_event(conn_or_path, event: Event) -> bool:
    """Return True if inserted, False if duplicate dedup_key."""
    with _connection(conn_or_path) as conn:
        try:
            conn.execute(
                """INSERT INTO events (id,source_id,cursor,event_type,payload_json,observed_at,dedup_key)
                VALUES (?,?,?,?,?,?,?)""",
                (
                    event.id, event.source_id, event.cursor, event.event_type,
                    to_json(event.payload), event.observed_at, event.dedup_key,
                ),
            )
            return True
        except sqlite3.IntegrityError:
            return False


def create_run(conn_or_path, run: Run) -> Run:
    with _connection(conn_or_path) as conn:
        conn.execute(
            """INSERT INTO runs (id,project_id,revision_id,provider,model,effort,prompt_version,tool_version,status,started_at,finished_at,usage_json,metrics_json)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                run.id, run.project_id, run.revision_id, run.provider, run.model, run.effort,
                run.prompt_version, run.tool_version, run.status, run.started_at, run.finished_at,
                to_json(run.usage), to_json(run.metrics),
            ),
        )
    return run


def update_run(conn_or_path, run: Run) -> None:
    with _connection(conn_or_path) as conn:
        conn.execute(
            """UPDATE runs SET status=?,finished_at=?,usage_json=?,metrics_json=? WHERE id=?""",
            (run.status, run.finished_at, to_json(run.usage), to_json(run.metrics), run.id),
        )


def create_run_attempt(conn_or_path, attempt: RunAttempt) -> RunAttempt:
    with _connection(conn_or_path) as conn:
        conn.execute(
            """INSERT INTO run_attempts
            (id,run_id,attempt_index,tool_name,args_json,result_json,finish_reason,started_at,finished_at,usage_json)
            VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                attempt.id, attempt.run_id, attempt.attempt_index, attempt.tool_name,
                to_json(attempt.args), to_json(attempt.result), attempt.finish_reason,
                attempt.started_at, attempt.finished_at, to_json(attempt.usage),
            ),
        )
    return attempt


def record_printer_state(conn_or_path, source_id: str, status: dict[str, Any]) -> str:
    pid = new_id("printer_state")
    with _connection(conn_or_path) as conn:
        conn.execute(
            "INSERT INTO printer_state (id,source_id,status_json,observed_at) VALUES (?,?,?,?)",
            (pid, source_id, to_json(status), utc_now()),
        )
    return pid


def get_run(conn_or_path, run_id: str) -> Optional[Run]:
    with _connection(conn_or_path) as conn:
        row = conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
    if not row:
        return None
    return Run(
        id=row["id"], project_id=row["project_id"], revision_id=row["revision_id"],
        provider=row["provider"], model=row["model"], effort=row["effort"],
        prompt_version=row["prompt_version"], tool_version=row["tool_version"],
        status=row["status"], started_at=row["started_at"], finished_at=row["finished_at"],
        usage=from_json(row["usage_json"], {}), metrics=from_json(row["metrics_json"], {}),
    )


class _connection:
    def __init__(self, conn_or_path: Any):
        self.conn_or_path = conn_or_path
        self._conn: sqlite3.Connection | None = None
        self._owns = False

    def __enter__(self) -> sqlite3.Connection:
        if isinstance(self.conn_or_path, (str, Path)):
            from .db import connect

            self._cm = connect(self.conn_or_path)
            self._conn = self._cm.__enter__()
            self._owns = True
        else:
            self._conn = self.conn_or_path
            self._conn.row_factory = self._conn.row_factory or sqlite3.Row
        return self._conn

    def __exit__(self, *exc):
        if self._owns:
            return self._cm.__exit__(*exc)
        return False
