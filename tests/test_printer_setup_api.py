import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.app import poc_api
from backend.app import printer_config


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('CALICLAW_PRINTER_CONFIG',str(tmp_path/'printers.json'))
    monkeypatch.delenv('OCTOPRINT_BASE_URL',raising=False)
    monkeypatch.setattr(poc_api,'_last_slice',{'old':True})
    monkeypatch.setattr(poc_api,'_uploaded_slice',{'old':True})
    app=FastAPI();app.include_router(poc_api.router)
    with TestClient(app) as client:
        yield client


def test_review_save_selection_and_secret_free_reads(client):
    response=client.post('/api/printers',json={'name':'Bench','base_url':'http://bench.local','api_key':'do-not-echo'})
    assert response.status_code==200 and 'do-not-echo' not in response.text
    saved=response.json()
    assert client.get('/api/printers').json()['active_id'] is None
    assert poc_api._last_slice is None and poc_api._uploaded_slice is None
    assert client.post('/api/printers/select',json={'printer_id':saved['id']}).status_code==200
    assert 'do-not-echo' not in client.get('/api/printers').text
    assert 'bench.local' not in client.get('/api/printers').text
    assert 'do-not-echo' not in client.get('/api/printers/'+saved['id']+'/setup').text
    assert printer_config.active_printer().api_key=='do-not-echo'
    assert client.post('/api/printers/select',json={'printer_id':'unknown'}).status_code==400


def test_probe_edit_reuses_key_only_for_same_address(client,monkeypatch):
    saved=client.post('/api/printers',json={'name':'Bench','base_url':'http://bench.local','api_key':'private-key'}).json()
    observed=[]
    monkeypatch.setattr(poc_api,'probe_printer',lambda config:observed.append(config.api_key) or {'reachable':True})
    client.post('/api/printers/probe',json={'id':saved['id'],'name':'Bench','base_url':'http://bench.local'})
    client.post('/api/printers/probe',json={'id':saved['id'],'name':'Bench','base_url':'http://different.local'})
    assert observed==['private-key','']


def test_configuration_rejects_host_shell_input(client):
    response=client.post('/api/printers',json={'name':'Invalid','base_url':'http://bench.local','ssh_alias':'host; reboot'})
    assert response.status_code==422


def test_switch_rejects_controls_rendered_for_previous_printer(client,monkeypatch):
    first=client.post('/api/printers',json={'name':'First','base_url':'http://first.local'}).json()
    second=client.post('/api/printers',json={'name':'Second','base_url':'http://second.local'}).json()
    client.post('/api/printers/select',json={'printer_id':first['id']})
    old_identity=printer_config.connection_identity()
    client.post('/api/printers/select',json={'printer_id':second['id']})
    monkeypatch.setattr(poc_api,'control_job',lambda *a:pytest.fail('Must not operate on changed printer'))
    monkeypatch.setattr(poc_api,'set_tool_target',lambda *a:pytest.fail('Must not heat changed printer'))
    assert client.post('/api/printer/cancel',json={'confirm':True,'printer_id':old_identity}).status_code==409
    assert client.post('/api/printer/targets',json={'tool':200,'printer_id':old_identity}).status_code==409
    assert client.post('/api/camera/restart',json={'confirm':True,'printer_id':old_identity}).status_code==409
