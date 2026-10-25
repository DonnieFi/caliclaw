"""SQLite storage and schema for CaliClaw contracts."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS profiles (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    kind TEXT NOT NULL,
    path TEXT,
    sha256 TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS revisions (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id),
    parent_id TEXT REFERENCES revisions(id),
    requirements_json TEXT NOT NULL DEFAULT '{}',
    assumptions_json TEXT NOT NULL DEFAULT '[]',
    params_json TEXT NOT NULL DEFAULT '{}',
    source_hash TEXT,
    artifact_id TEXT REFERENCES artifacts(id),
    validation_json TEXT NOT NULL DEFAULT '{}',
    run_id TEXT REFERENCES runs(id),
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS artifacts (
    id TEXT PRIMARY KEY,
    revision_id TEXT REFERENCES revisions(id),
    kind TEXT NOT NULL,
    path TEXT,
    sha256 TEXT,
    bytes INTEGER,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL,
    cursor TEXT,
    event_type TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    observed_at TEXT NOT NULL,
    dedup_key TEXT UNIQUE
);

CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    project_id TEXT REFERENCES projects(id),
    revision_id TEXT REFERENCES revisions(id),
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    effort TEXT,
    prompt_version TEXT,
    tool_version TEXT,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    usage_json TEXT NOT NULL DEFAULT '{}',
    metrics_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS run_attempts (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(id),
    attempt_index INTEGER NOT NULL,
    tool_name TEXT NOT NULL,
    args_json TEXT NOT NULL DEFAULT '{}',
    result_json TEXT NOT NULL DEFAULT '{}',
    finish_reason TEXT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    usage_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS printer_state (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL,
    status_json TEXT NOT NULL DEFAULT '{}',
    observed_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS conversations (
    project_id TEXT NOT NULL REFERENCES projects(id),
    session_id TEXT NOT NULL,
    messages_json TEXT NOT NULL DEFAULT '[]',
    PRIMARY KEY(project_id, session_id)
);

CREATE TABLE IF NOT EXISTS fit_reports (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id),
    revision_id TEXT REFERENCES revisions(id),
    note TEXT NOT NULL,
    measured_json TEXT NOT NULL DEFAULT '{}',
    keep_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL
);
"""


def init_db(path: str | Path) -> None:
    conn = sqlite3.connect(str(path))
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()


@contextmanager
def connect(path: str | Path):
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
