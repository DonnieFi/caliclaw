"""Contract and persistence tests for CaliClaw."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from backend.app.db import init_db
from backend.app.models import Artifact, Project, Revision, Run, RunAttempt, Event
from backend.app.repository import (
    create_artifact,
    create_project,
    create_revision,
    create_run,
    create_run_attempt,
    get_artifact,
    get_project,
    get_revision,
    get_run,
    record_event,
    update_run,
)


@pytest.fixture()
def db_path():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    Path(path).unlink()
    init_db(path)
    yield path
    Path(path).unlink(missing_ok=True)


def test_project_revision_artifact_roundtrip(db_path):
    project = create_project(db_path, "Bracket", "test")
    assert get_project(db_path, project.id).name == "Bracket"

    revision = Revision(project_id=project.id, requirements={"width": 40}, params={"wall": 4})
    create_revision(db_path, revision)
    loaded = get_revision(db_path, revision.id)
    assert loaded is not None
    assert loaded.requirements == {"width": 40}
    assert loaded.params == {"wall": 4}

    artifact = Artifact(revision_id=revision.id, kind="stl", sha256="abc", bytes=10)
    create_artifact(db_path, artifact)
    loaded_artifact = get_artifact(db_path, artifact.id)
    assert loaded_artifact.kind == "stl"
    assert loaded_artifact.sha256 == "abc"


def test_revision_parent_chain(db_path):
    project = create_project(db_path, "P")
    r1 = Revision(project_id=project.id, params={"v": 1})
    create_revision(db_path, r1)
    r2 = Revision(project_id=project.id, parent_id=r1.id, params={"v": 2})
    create_revision(db_path, r2)
    assert get_revision(db_path, r2.id).parent_id == r1.id


def test_event_dedup(db_path):
    event = Event(source_id="pi", event_type="temperature", dedup_key="k1")
    assert record_event(db_path, event) is True
    duplicate = Event(id="e2", source_id="pi", event_type="temperature", dedup_key="k1")
    assert record_event(db_path, duplicate) is False


def test_run_and_attempt_accounting(db_path):
    project = create_project(db_path, "P")
    run = Run(project_id=project.id, provider="reflection", model="configured", status="running")
    create_run(db_path, run)
    attempt = RunAttempt(run_id=run.id, attempt_index=0, tool_name="build_model", args={"scad": "x"})
    create_run_attempt(db_path, attempt)
    run.status = "completed"
    run.usage = {"total_tokens": 100}
    update_run(db_path, run)
    loaded = get_run(db_path, run.id)
    assert loaded.status == "completed"
    assert loaded.usage == {"total_tokens": 100}


def test_stale_slice_provenance_is_data(db_path):
    project = create_project(db_path, "P")
    r1 = Revision(project_id=project.id, params={"v": 1})
    create_revision(db_path, r1)
    artifact = Artifact(revision_id=r1.id, kind="stl", sha256="hash1")
    create_artifact(db_path, artifact)
    r1.artifact_id = artifact.id
    # Re-run creation updates revision row through repository helper by recreating? Instead update directly via create_revision only once; here check immutability expectation: new revision required.
    r2 = Revision(project_id=project.id, parent_id=r1.id, params={"v": 2})
    create_revision(db_path, r2)
    assert get_revision(db_path, r2.id).artifact_id is None
