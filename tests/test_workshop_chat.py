import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import Request, Response
from backend.app import poc_api, cad_revision
from backend.app.conversations import load_conversation
from backend.app.db import init_db
from backend.app.fit import record_fit
from backend.app.provider import ProviderResponse
from backend.app.repository import create_project, list_revisions
from backend.app.worker import build_model


@pytest.fixture
def workshop(tmp_path, monkeypatch):
    db = tmp_path / 'chat.db'
    init_db(db)
    project = create_project(db, 'Chat')
    monkeypatch.setattr(poc_api, 'DB_PATH', str(db))
    monkeypatch.setattr(poc_api, 'PROJECT', project)
    monkeypatch.setattr(poc_api, '_sessions', {})
    monkeypatch.setattr(poc_api, '_last_stl', {})
    monkeypatch.setattr(poc_api, '_last_revision_id', None)
    monkeypatch.setattr(poc_api, '_last_slice', None)
    monkeypatch.setenv('CALICLAW_ARTIFACT_ROOT', str(tmp_path / 'artifacts'))
    monkeypatch.setattr(poc_api, 'reflection_config_from_env', lambda: None)
    return db, project


def chat(message, phase='brainstorm'):
    return poc_api.chat(poc_api.ChatRequest(message=message, phase=phase),
                        Request({'type': 'http', 'headers': [(b'cookie', b'caliclaw_session=test')]}), Response())


def test_offline_notes_survive_new_session_cache(workshop, monkeypatch):
    db, project = workshop
    assert 'Saved your brainstorm' in chat('Need a spacer, height 12 mm').reply
    monkeypatch.setattr(poc_api, '_sessions', {})
    assert 'model key' in chat('Make it', 'design').reply
    history = load_conversation(db, project.id, 'test')
    assert history[0]['content'] == 'Need a spacer, height 12 mm'
    assert list_revisions(db, project.id) == []


def test_brainstorm_cannot_build_even_if_provider_requests_it(workshop, monkeypatch):
    db, project = workshop
    class Provider:
        def chat(self, messages, tools, **kwargs):
            assert all(t['function']['name'] not in ('build_model', 'slice_model') for t in tools)
            if messages[-1]['role'] != 'tool':
                return ProviderResponse(content='', tool_calls=[{'id': 'bad', 'function': {'name': 'build_model', 'arguments': '{}'}}], finish_reason='tool_calls', usage={})
            return ProviderResponse(content='What should the spacer fit?', tool_calls=[], finish_reason='stop', usage={})
    monkeypatch.setattr(poc_api, 'reflection_config_from_env', lambda: object())
    monkeypatch.setattr(poc_api, 'ProviderAdapter', lambda cfg: Provider())
    chat('A spacer')
    assert list_revisions(db, project.id) == []


def test_fit_revision_preserves_dimensions_and_failed_build_keeps_part(workshop, monkeypatch):
    db, project = workshop
    # Real OpenSCAD and independent mesh validation; skip only the preview subprocess.
    monkeypatch.setattr('backend.app.worker.render_preview', lambda *args: None)
    source = 'cube([width, depth, height]);'
    result, first, artifact = cad_revision.build_revision(db, project.id, None, source, {'width': 10, 'depth': 8, 'height': 5})
    assert result.ok
    record_fit(db, project.id, revision_id=first.id, note='Height needs 1 mm more', measured={'height': 4}, keep=['width'])
    result, second, _ = cad_revision.build_revision(db, project.id, first.id, source, {'width': 10, 'depth': 8, 'height': 6})
    assert result.ok and second.parent_id == first.id
    assert second.params['dimensions']['width'] == 10
    assert second.validation['bounds_mm'][1][2] == 6
    assert Path(artifact.path).is_file()
    for dims in [{'width': 11, 'depth': 8, 'height': 6}, {'depth': 8, 'height': 6}]:
        with pytest.raises(ValueError, match='protected dimension'):
            cad_revision.build_revision(db, project.id, first.id, source, dims)
    failed, rev, art = cad_revision.build_revision(db, project.id, second.id, 'cube([;', {'width': 10})
    assert not failed.ok and rev is None
    assert len(list_revisions(db, project.id)) == 2


def test_explicit_design_and_revise_use_same_history_and_one_build(workshop, monkeypatch):
    db, project = workshop
    chat('Keep this brainstorm: a measured spacer')
    monkeypatch.setattr('backend.app.worker.render_preview', lambda *args: None)
    class Provider:
        def __init__(self):
            self.calls = 0
        def chat(self, messages, **kwargs):
            self.calls += 1
            assert any('Keep this brainstorm' in str(m.get('content')) for m in messages)
            if self.calls <= 2:
                args = {'scad': 'cube([width, depth, height]);', 'dimensions': {'width': 10, 'depth': 8, 'height': 5}}
                return ProviderResponse(content='', tool_calls=[{'id': str(self.calls), 'function': {'name': 'build_model', 'arguments': json.dumps(args)}}], finish_reason='tool_calls', usage={})
            return ProviderResponse(content='Built.', tool_calls=[], finish_reason='stop', usage={})
    monkeypatch.setattr(poc_api, 'reflection_config_from_env', lambda: object())
    monkeypatch.setattr(poc_api, 'ProviderAdapter', lambda cfg: Provider())
    chat('Design it', 'design')
    first = poc_api._last_revision_id
    assert len(list_revisions(db, project.id)) == 1
    chat('Revise it', 'revise')
    revisions = list_revisions(db, project.id)
    assert len(revisions) == 2 and revisions[-1].parent_id == first
    current = poc_api._last_stl['current']
    monkeypatch.setattr(cad_revision, 'build_model', lambda source: SimpleNamespace(ok=False, stl_path=None, error='compile failed', mesh=None, sha256=None))
    chat('Try a revision', 'revise')
    assert poc_api._last_stl['current'] == current
    assert len(list_revisions(db, project.id)) == 2
