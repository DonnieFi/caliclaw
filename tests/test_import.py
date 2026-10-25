import io
import asyncio
from pathlib import Path

import pytest
from fastapi import HTTPException, UploadFile
from backend.app import poc_api
from backend.app.db import init_db
from backend.app.repository import create_project, get_artifact, list_revisions


@pytest.fixture
def bench(tmp_path, monkeypatch):
    db = tmp_path / 'bench.db'
    init_db(db)
    monkeypatch.setattr(poc_api, 'DB_PATH', str(db))
    monkeypatch.setattr(poc_api, 'PROJECT', create_project(db, 'Test'))
    monkeypatch.setattr(poc_api, '_last_revision_id', None)
    monkeypatch.setattr(poc_api, '_last_stl', {})
    monkeypatch.setattr(poc_api, '_last_slice', {'old': True})
    monkeypatch.setenv('CALICLAW_ARTIFACT_ROOT', str(tmp_path / 'artifacts'))
    def forbidden(*args, **kwargs):
        raise AssertionError('No printer or slicer calls during import')
    for name in ['upload_file', 'control_job', 'slice_model', '_real_printer_status']:
        monkeypatch.setattr(poc_api, name, forbidden)
    return db


def upload(data, filename='part.stl'):
    return asyncio.run(poc_api.import_stl(UploadFile(file=io.BytesIO(data), filename=filename)))


def test_import_retains_originals_and_failed_import_keeps_current(bench):
    first = Path('web/fixtures/cube.stl').read_bytes()
    second = Path('web/fixtures/bracket.stl').read_bytes()
    one = upload(first)
    two = upload(second)
    revs = list_revisions(bench, poc_api.PROJECT.id)
    assert len(revs) == 2
    assert revs[1].parent_id == one['revision_id']
    assert revs[0].params['source'] == 'import'
    assert Path(get_artifact(bench, revs[0].artifact_id).path).read_bytes() == first
    assert Path(poc_api.revision_stl(one['revision_id']).path).read_bytes() == first
    assert Path(poc_api.current_stl().path).read_bytes() == second
    assert poc_api._last_slice is None
    for content, name in [(b'bad', 'bad.stl'), (first, 'part.txt')]:
        with pytest.raises(HTTPException):
            upload(content, name)
    assert poc_api._last_revision_id == two['revision_id']
    assert len(list_revisions(bench, poc_api.PROJECT.id)) == 2


def test_oversize_import_is_rejected(bench, monkeypatch):
    monkeypatch.setattr(poc_api, 'MAX_STL_BYTES', 10)
    with pytest.raises(HTTPException) as exc:
        upload(b'x' * 11)
    assert exc.value.status_code == 413
    assert poc_api._last_revision_id is None
