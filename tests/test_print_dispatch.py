"""Exact artifact dispatch contracts; no live hardware."""
import asyncio
import io

import pytest
from fastapi import HTTPException, UploadFile
from backend.app import poc_api as api
from backend.app.slicer import sha256_file


@pytest.fixture
def prepared(monkeypatch, tmp_path):
    profiles = tmp_path / 'profiles'
    profiles.mkdir()
    for name in ('ender3-proven-pla.ini', 'ender3-speed-preference.ini'):
        (profiles / name).write_text(name)
    stl = tmp_path / 'part.stl'
    stl.write_bytes(b'mesh')
    gcode = tmp_path / 'part.gcode'
    gcode.write_bytes(b'G90\n')
    s = {'ok': True, 'revision_id': 'r1', 'gcode_path': str(gcode),
         'stl_sha256': sha256_file(stl), 'gcode_sha256': sha256_file(gcode),
         'profile_sha256': sha256_file(profiles / 'ender3-proven-pla.ini'),
         'overlay_sha256': sha256_file(profiles / 'ender3-speed-preference.ini')}
    monkeypatch.setattr(api, 'ROOT', tmp_path)
    monkeypatch.setattr(api, '_last_stl', {'current': str(stl)})
    monkeypatch.setattr(api, '_last_revision_id', 'r1')
    monkeypatch.setattr(api, '_last_slice', s)
    monkeypatch.setattr(api, '_uploaded_slice', None)
    monkeypatch.setattr(api, '_real_printer_status', lambda: {
        'simulated': False, 'flags': {'operational': True},
        'hotend': {'actual': 22}, 'bed': {'actual': 23}})
    return s


def upload():
    return asyncio.run(api.printer_upload(UploadFile(filename='part.gcode', file=io.BytesIO(b'G90\n'))))


def test_wrong_upload_never_reaches_printer(prepared, monkeypatch):
    monkeypatch.setattr(api, 'upload_file', lambda *a, **kw: pytest.fail('must not upload'))
    with pytest.raises(HTTPException, match='409'):
        asyncio.run(api.printer_upload(UploadFile(filename='bad.gcode', file=io.BytesIO(b'wrong'))))


def test_changed_overlay_invalidates_slice(prepared):
    (api.ROOT / 'profiles/ender3-speed-preference.ini').write_text('changed')
    assert api.printer_preparation()['ready'] is False


def test_selected_file_mismatch_never_starts(prepared, monkeypatch):
    monkeypatch.setattr(api, 'upload_file', lambda path, name, **kw: {'files': {'local': {'name': name, 'path': name}}})
    result = upload()
    monkeypatch.setattr(api, 'get_job', lambda: {'job': {'file': {'origin': 'local', 'path': 'other.gcode'}}})
    monkeypatch.setattr(api, 'control_job', lambda *a: pytest.fail('must not start'))
    with pytest.raises(HTTPException) as exc:
        api.printer_start(api.ControlRequest(confirm=True, filename=result['filename'], gcode_sha256=result['gcode_sha256']))
    assert exc.value.status_code == 409


def test_upload_and_exact_print_verified(prepared, monkeypatch):
    calls = []
    def accept(path, name, **kw):
        assert path.read_bytes() == b'G90\n'
        assert kw['print_after'] is False
        return {'files': {'local': {'name': name, 'path': name}}}
    monkeypatch.setattr(api, 'upload_file', accept)
    result = upload()
    monkeypatch.setattr(api, 'get_job', lambda: {'state': 'Printing' if calls else 'Operational',
        'job': {'file': {'origin': 'local', 'path': result['filename'], 'name': result['filename']}}})
    monkeypatch.setattr(api, 'control_job', lambda command: calls.append(command))
    response = api.printer_start(api.ControlRequest(confirm=True, filename=result['filename'], gcode_sha256=result['gcode_sha256']))
    assert response['ok'] is True
    assert calls == ['start']


def test_missing_temperature_blocks_dispatch(prepared, monkeypatch):
    monkeypatch.setattr(api, '_real_printer_status', lambda: {'flags': {'operational': True}})
    with pytest.raises(HTTPException):
        api._require_idle()


def test_active_print_blocks_upload(prepared, monkeypatch):
    monkeypatch.setattr(api, '_real_printer_status', lambda: {'flags': {'operational': True, 'paused': True}})
    monkeypatch.setattr(api, 'upload_file', lambda *a, **kw: pytest.fail('must not upload'))
    with pytest.raises(HTTPException):
        upload()


def test_changed_revision_blocks_start(prepared, monkeypatch):
    monkeypatch.setattr(api, '_last_revision_id', 'r2')
    monkeypatch.setattr(api, 'control_job', lambda *a: pytest.fail('must not start'))
    with pytest.raises(HTTPException):
        api.printer_start(api.ControlRequest(confirm=True, filename='old.gcode', gcode_sha256=prepared['gcode_sha256']))


def test_start_without_explicit_confirmation_blocks_before_dispatch(prepared, monkeypatch):
    monkeypatch.setattr(api, 'control_job', lambda *a: pytest.fail('must not start'))
    with pytest.raises(HTTPException) as exc:
        api.printer_start(api.ControlRequest())
    assert exc.value.status_code == 400


def test_failed_upload_clears_previous_start_authority(prepared, monkeypatch):
    monkeypatch.setattr(api, '_uploaded_slice', {'filename': 'old', 'gcode_sha256': prepared['gcode_sha256']})
    def fail(*args, **kwargs):
        raise TimeoutError('response lost')
    monkeypatch.setattr(api, 'upload_file', fail)
    with pytest.raises(HTTPException) as exc:
        upload()
    assert exc.value.status_code == 502
    assert api._uploaded_slice is None
