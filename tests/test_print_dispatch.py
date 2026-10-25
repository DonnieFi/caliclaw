"""Exact dispatch safeguards carried forward across the printer-setup API merge.

Upload takes the server's checked slice directly; arbitrary multipart G-code is
rejected instead of being accepted and compared against the checked bytes.
"""
from pathlib import Path
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from backend.app import poc_api as api
from backend.app.print_preparation import digest, printer_identity


@pytest.fixture
def prepared(monkeypatch, tmp_path):
    profile=tmp_path/'profile.ini';profile.write_text('profile')
    overlay=tmp_path/'overlay.ini';overlay.write_text('overlay')
    monkeypatch.setenv('CALICLAW_PRINTER_CONFIG',str(tmp_path/'no-saved-config.json'))
    monkeypatch.setenv('CALICLAW_PROFILE_PATH',str(profile));monkeypatch.setenv('CALICLAW_PROFILE_SHA256',digest(profile))
    monkeypatch.setenv('CALICLAW_OVERLAY_PATH',str(overlay));monkeypatch.setenv('CALICLAW_OVERLAY_SHA256',digest(overlay))
    stl=tmp_path/'part.stl';stl.write_bytes(b'mesh')
    gcode=tmp_path/'part.gcode';gcode.write_bytes(b'G90\n')
    preparation={'id':'slice-1','ok':True,'revision_id':'r1','gcode_path':str(gcode),
                 'mesh_sha256':digest(stl),'gcode_sha256':digest(gcode),
                 'profile_sha256':digest(profile),'overlay_sha256':digest(overlay),
                 'profile_confirmed':True,'printer_id':printer_identity()}
    monkeypatch.setattr(api,'_last_stl',{'current':str(stl)})
    monkeypatch.setattr(api,'_last_revision_id','r1')
    monkeypatch.setattr(api,'_last_slice',preparation)
    monkeypatch.setattr(api,'_uploaded_slice',None)
    monkeypatch.setattr(api,'_real_printer_status',lambda:{'source':'octoprint','state':'Operational','simulated':False,
                         'flags':{'operational':True},'hotend':{'actual':22},'bed':{'actual':23}})
    return preparation,overlay


def upload():
    return api.printer_upload()


def test_wrong_upload_never_reaches_printer(prepared,monkeypatch):
    monkeypatch.setattr(api,'upload_file',lambda *a,**kw:pytest.fail('must not upload'))
    app=FastAPI();app.include_router(api.router)
    with TestClient(app) as client:
        response=client.post('/api/printer/upload',files={'file':('bad.gcode',b'wrong')})
    assert response.status_code==422


def test_changed_overlay_invalidates_slice(prepared):
    prepared[1].write_text('changed')
    assert api.printer_preparation()['ready'] is False


def test_selected_file_mismatch_never_starts(prepared,monkeypatch):
    monkeypatch.setattr(api,'upload_file',lambda path,name,**kw:{'files':{'local':{'name':name,'path':name}}})
    result=upload()
    monkeypatch.setattr(api,'get_job',lambda:{'state':'Operational','job':{'file':{'origin':'local','path':'other.gcode'}}})
    monkeypatch.setattr(api,'control_job',lambda *a:pytest.fail('must not start'))
    with pytest.raises(HTTPException) as exc:
        api.printer_start(api.StartRequest(confirm=True,filename=result['filename'],gcode_sha256=result['gcode_sha256']))
    assert exc.value.status_code==409


def test_upload_and_exact_print_verified(prepared,monkeypatch):
    calls=[]
    def accept(path,name,**kw):
        assert Path(path).read_bytes()==b'G90\n' and kw['print_after'] is False
        return {'files':{'local':{'name':name,'path':name}}}
    monkeypatch.setattr(api,'upload_file',accept)
    result=upload()
    monkeypatch.setattr(api,'get_job',lambda:{'state':'Printing' if calls else 'Operational',
                         'job':{'file':{'origin':'local','path':result['filename'],'name':result['filename']}}})
    monkeypatch.setattr(api,'control_job',lambda command:calls.append(command))
    response=api.printer_start(api.StartRequest(confirm=True,filename=result['filename'],gcode_sha256=result['gcode_sha256']))
    assert response['ok'] is True and response['message']=='Printing verified'
    assert calls==['start']


def test_missing_temperature_blocks_dispatch(prepared,monkeypatch):
    monkeypatch.setattr(api,'_real_printer_status',lambda:{'source':'octoprint','state':'Operational','flags':{'operational':True}})
    with pytest.raises(HTTPException):api._require_idle()


def test_active_print_blocks_upload(prepared,monkeypatch):
    monkeypatch.setattr(api,'_real_printer_status',lambda:{'source':'octoprint','state':'Paused','flags':{'operational':True,'paused':True}})
    monkeypatch.setattr(api,'upload_file',lambda *a,**kw:pytest.fail('must not upload'))
    with pytest.raises(HTTPException):upload()


def test_changed_revision_blocks_start(prepared,monkeypatch):
    monkeypatch.setattr(api,'_last_revision_id','r2')
    monkeypatch.setattr(api,'control_job',lambda *a:pytest.fail('must not start'))
    with pytest.raises(HTTPException):api.printer_start(api.StartRequest(confirm=True,filename='old.gcode',gcode_sha256=prepared[0]['gcode_sha256']))


def test_start_without_explicit_confirmation_blocks_before_dispatch(prepared,monkeypatch):
    monkeypatch.setattr(api,'control_job',lambda *a:pytest.fail('must not start'))
    with pytest.raises(HTTPException) as exc:api.printer_start(api.StartRequest())
    assert exc.value.status_code==400


def test_failed_upload_clears_previous_start_authority(prepared,monkeypatch):
    monkeypatch.setattr(api,'_uploaded_slice',{'filename':'old','gcode_sha256':prepared[0]['gcode_sha256']})
    def fail(*args,**kwargs):raise TimeoutError('response lost')
    monkeypatch.setattr(api,'upload_file',fail)
    with pytest.raises(HTTPException) as exc:upload()
    assert exc.value.status_code==502 and api._uploaded_slice is None
