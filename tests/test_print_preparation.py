from pathlib import Path
from types import SimpleNamespace
import pytest
from fastapi import HTTPException
from backend.app import poc_api
from backend.app.print_preparation import digest


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    mesh = tmp_path / 'part.stl'
    mesh.write_bytes(Path('web/fixtures/cube.stl').read_bytes())
    profile = tmp_path / 'machine.ini'
    profile.write_text('nozzle_diameter = 0.6\n')
    gcode = tmp_path / 'part.gcode'
    gcode.write_text('; isolated test gcode\n')
    monkeypatch.setenv('CALICLAW_PROFILE_PATH', str(profile))
    monkeypatch.setenv('CALICLAW_PROFILE_SHA256', digest(profile))
    monkeypatch.setattr(poc_api, '_last_stl', {'current': str(mesh)})
    monkeypatch.setattr(poc_api, '_last_revision_id', 'rev-1')
    monkeypatch.setattr(poc_api, '_last_slice', None)
    monkeypatch.setattr(poc_api, '_uploaded_slice', None)
    monkeypatch.setattr(poc_api, '_real_printer_status', lambda: {'source': 'octoprint', 'state': 'Operational', 'flags': {'operational': True}, 'simulated': False, 'hotend':{'actual':22}, 'bed':{'actual':23}})
    def slice_model(stl, selected):
        assert Path(selected).read_bytes() == profile.read_bytes()
        return SimpleNamespace(ok=True, gcode_path=str(gcode), estimates={'printing_time': '2m'}, profile_sha256=digest(selected))
    monkeypatch.setattr(poc_api, 'slice_model', slice_model)
    calls = []
    def upload(path, filename, *, print_after):
        assert Path(path) == gcode and print_after is False
        calls.append('upload')
        return {'files': {'local': {'name': filename, 'path': filename}}}
    monkeypatch.setattr(poc_api, 'upload_file', upload)
    monkeypatch.setattr(poc_api, 'control_job', lambda action: calls.append(action) or {'ok': True})
    return mesh, profile, gcode, calls


def test_slice_upload_confirm_start_and_selected_file_binding(prepared, monkeypatch):
    mesh, profile, gcode, calls = prepared
    view = poc_api.slice_now()
    assert view['ready'] and view['profile'] == 'Confirmed machine profile'
    assert poc_api._last_slice['profile_sha256'] == digest(profile)
    assert poc_api._last_slice['mesh_sha256'] == digest(mesh)
    uploaded = poc_api.printer_upload()
    assert uploaded['uploaded'] and calls == ['upload']
    req = poc_api.StartRequest(confirm=True, filename=uploaded['filename'], slice_id=uploaded['slice_id'], gcode_sha256=uploaded['gcode_sha256'])
    monkeypatch.setattr(poc_api, 'get_job', lambda: {'state': 'Operational', 'job': {'file': {'origin': 'local', 'path': 'other.gcode'}}})
    with pytest.raises(HTTPException):
        poc_api.printer_start(req)
    monkeypatch.setattr(poc_api, 'get_job', lambda: {'state': 'Operational', 'job': {'file': {'origin': 'local', 'path': uploaded['filename']}}})
    with pytest.raises(HTTPException):
        poc_api.printer_start(poc_api.StartRequest(confirm=False))
    assert calls == ['upload']
    poc_api.printer_start(req)
    assert calls == ['upload', 'start']
    with pytest.raises(HTTPException):
        poc_api.printer_start(req)
    assert calls == ['upload', 'start']


@pytest.mark.parametrize('changed', ['mesh', 'profile', 'gcode', 'revision'])
def test_stale_preparation_cannot_upload(prepared, monkeypatch, changed):
    mesh, profile, gcode, calls = prepared
    poc_api.slice_now()
    if changed == 'revision':
        monkeypatch.setattr(poc_api, '_last_revision_id', 'rev-2')
    else:
        {'mesh': mesh, 'profile': profile, 'gcode': gcode}[changed].write_text('changed')
    with pytest.raises(HTTPException):
        poc_api.printer_upload()
    assert calls == []


def test_fixture_and_simulation_cannot_upload(prepared, monkeypatch):
    monkeypatch.delenv('CALICLAW_PROFILE_SHA256')
    assert not poc_api.slice_now()['ready']
    with pytest.raises(HTTPException):
        poc_api.printer_upload()
    monkeypatch.setenv('CALICLAW_PROFILE_SHA256', digest(prepared[1]))
    poc_api.slice_now()
    monkeypatch.setattr(poc_api, '_real_printer_status', lambda: {'simulated': True})
    with pytest.raises(HTTPException):
        poc_api.printer_upload()
    assert prepared[3] == []


@pytest.mark.parametrize('action', ['pause', 'resume', 'cancel'])
def test_confirm_and_live_status_required_for_controls(prepared, monkeypatch, action):
    function = getattr(poc_api, 'printer_' + action)
    with pytest.raises(HTTPException):
        function(poc_api.ControlRequest(confirm=False))
    monkeypatch.setattr(poc_api, '_real_printer_status', lambda: {'simulated': True})
    with pytest.raises(HTTPException):
        function(poc_api.ControlRequest(confirm=True))
    assert prepared[3] == []


def test_actual_slicer_uses_exact_configured_profile(tmp_path, monkeypatch):
    profile = tmp_path / 'verified-test-fixture.ini'
    profile.write_bytes(Path('profiles/ender3-proven-pla.ini').read_bytes())
    monkeypatch.setenv('CALICLAW_PROFILE_PATH', str(profile))
    monkeypatch.setenv('CALICLAW_PROFILE_SHA256', digest(profile))
    monkeypatch.setattr(poc_api, '_last_stl', {'current': str(Path('web/fixtures/cube.stl').resolve())})
    monkeypatch.setattr(poc_api, '_last_revision_id', 'test-cube')
    monkeypatch.setattr(poc_api, '_last_slice', None)
    monkeypatch.setattr(poc_api, '_uploaded_slice', None)
    result = poc_api.slice_now()
    assert result['ready']
    assert result['estimates']['printing_time']
    assert poc_api._last_slice['profile_sha256'] == digest(profile)
    assert 'M220 S150' not in Path(poc_api._last_slice['gcode_path']).read_text()


def test_changed_printer_cannot_start(prepared, monkeypatch):
    poc_api.slice_now()
    uploaded = poc_api.printer_upload()
    monkeypatch.setenv('OCTOPRINT_BASE_URL', 'http://different-printer.invalid')
    with pytest.raises(HTTPException):
        poc_api.printer_start(poc_api.StartRequest(confirm=True, filename=uploaded['filename'], slice_id=uploaded['slice_id'], gcode_sha256=uploaded['gcode_sha256']))
    assert prepared[3] == ['upload']


def test_pause_resume_cancel_without_model(prepared, monkeypatch):
    monkeypatch.setattr(poc_api, 'reflection_config_from_env', lambda: pytest.fail('Controls must not need a model'))
    for action, flags in [('pause', {'printing': True}), ('resume', {'paused': True}), ('cancel', {'printing': True})]:
        monkeypatch.setattr(poc_api, '_real_printer_status', lambda: {'source': 'octoprint', 'flags': flags})
        getattr(poc_api, 'printer_' + action)(poc_api.ControlRequest(confirm=True))
    assert prepared[3] == ['pause', 'resume', 'cancel']


def test_explicit_overlay_is_sliced_and_changes_invalidate(tmp_path,monkeypatch):
    profile=tmp_path/'base.ini';profile.write_bytes(Path('profiles/ender3-proven-pla.ini').read_bytes())
    overlay=tmp_path/'speed.ini';overlay.write_bytes(Path('profiles/ender3-speed-preference.ini').read_bytes())
    monkeypatch.setenv('CALICLAW_PROFILE_PATH',str(profile))
    monkeypatch.setenv('CALICLAW_PROFILE_SHA256',digest(profile))
    monkeypatch.setenv('CALICLAW_OVERLAY_PATH',str(overlay))
    monkeypatch.setenv('CALICLAW_OVERLAY_SHA256',digest(overlay))
    monkeypatch.setattr(poc_api,'_last_stl',{'current':str(Path('web/fixtures/cube.stl').resolve())})
    monkeypatch.setattr(poc_api,'_last_revision_id','cube')
    monkeypatch.setattr(poc_api,'_last_slice',None)
    monkeypatch.setattr(poc_api,'_uploaded_slice',None)
    result=poc_api.slice_now()
    assert result['ready'] and 'overlay' in result['profile']
    assert poc_api._last_slice['overlay_sha256']==digest(overlay)
    gcode=Path(poc_api._last_slice['gcode_path']).read_text()
    assert 'M220 S150' in gcode
    overlay.write_text('changed')
    with pytest.raises(HTTPException):
        poc_api.checked_preparation()


def test_switch_during_slice_does_not_publish_for_new_printer(prepared,monkeypatch):
    original=poc_api.slice_model
    def changing_slice(*args,**kwargs):
        # This must be possible while the slicer runs; pause/cancel use this lock too.
        assert poc_api._control_lock.acquire(blocking=False)
        poc_api._control_lock.release()
        monkeypatch.setenv('OCTOPRINT_BASE_URL','http://changed-during-slice.invalid')
        return original(*args,**kwargs)
    monkeypatch.setattr(poc_api,'slice_model',changing_slice)
    with pytest.raises(HTTPException) as exc:
        poc_api.slice_now()
    assert exc.value.status_code==409 and poc_api._last_slice is None
