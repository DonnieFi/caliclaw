"""Persist checked meshes and their revision atomically before making them current."""
from __future__ import annotations

import hashlib
import os
import shutil
import uuid
from pathlib import Path

from .db import connect
from .models import Artifact, Revision
from .repository import create_artifact, create_revision


def save_part(db_path, project_id, parent_id, mesh_path, *, params, validation, source=None):
    root = Path(os.environ.get('CALICLAW_ARTIFACT_ROOT', 'artifacts')).resolve()
    folder = root / uuid.uuid4().hex
    folder.mkdir(parents=True)
    try:
        target = folder / 'original.stl'
        shutil.copyfile(mesh_path, target)
        mesh_hash = hashlib.sha256(target.read_bytes()).hexdigest()
        if source is not None:
            (folder / 'source.scad').write_text(source)
        revision = Revision(project_id=project_id, parent_id=parent_id, params=params,
                            source_hash=hashlib.sha256(source.encode()).hexdigest() if source is not None else mesh_hash,
                            validation=validation)
        artifact = Artifact(revision_id=revision.id, kind='stl', path=str(target), sha256=mesh_hash,
                            bytes=target.stat().st_size, metadata=validation)
        with connect(db_path) as conn:
            create_revision(conn, revision)
            create_artifact(conn, artifact)
            conn.execute('UPDATE revisions SET artifact_id=? WHERE id=?', (artifact.id, revision.id))
        revision.artifact_id = artifact.id
        return revision, artifact
    except Exception:
        shutil.rmtree(folder)
        raise
