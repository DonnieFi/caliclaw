"""Tests for revision versioning and restore."""
import tempfile, os
from pathlib import Path

from backend.app.db import init_db
from backend.app.repository import create_project
from backend.app.revisions import create_revision_child, is_slice_stale, restore_revision


def test_revision_child_and_restore():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    Path(path).unlink()
    init_db(path)
    project = create_project(path, "P")
    r1 = create_revision_child(path, project.id, None, params={"v": 1})
    r2 = create_revision_child(path, project.id, r1.id, params={"v": 2})
    assert r2.parent_id == r1.id
    restored = restore_revision(path, r1.id)
    assert restored.parent_id == r1.id
    assert restored.params == r1.params
    Path(path).unlink(missing_ok=True)


def test_slice_staleness():
    assert is_slice_stale("r1", "h1", "r2", "h1") is True
    assert is_slice_stale("r1", "h1", "r1", "h2") is True
    assert is_slice_stale("r1", "h1", "r1", "h1") is False
