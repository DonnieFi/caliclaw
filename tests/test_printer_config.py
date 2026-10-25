import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from backend.app import printer_config as config, printer_discovery, octoprint, host_checks
from backend.app.print_preparation import printer_identity, selected_profile


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setenv('CALICLAW_PRINTER_CONFIG', str(tmp_path / 'private.json'))
    monkeypatch.delenv('OCTOPRINT_BASE_URL', raising=False)


def make_printer(**kwargs):
    return config.PrinterConfig(name='My printer', base_url='http://printer.local:5000', api_key='private-key', **kwargs)


def test_manual_save_select_edit_and_private_storage():
    first = config.save_printer(make_printer())
    assert config.active_printer() is None  # saved settings never auto-select
    config.select_printer(first['id'])
    assert config.active_printer().api_key == 'private-key'
    assert 'private-key' not in json.dumps(config.list_printers())
    assert 'printer.local' not in json.dumps(config.list_printers())
    assert os.stat(config.config_path()).st_mode & 0o777 == 0o600
    before = printer_identity()
    second = config.save_printer(config.PrinterConfig(name='Other', base_url='http://second.local', api_key='second-key'))
    config.select_printer(second['id'])
    assert printer_identity() != before
    assert octoprint.base_url() == 'http://second.local'
    assert octoprint.api_key() == 'second-key'
    config.save_printer(config.PrinterConfig(id=second['id'], name='Changed', base_url='http://second.local'))
    assert config.active_printer().api_key == 'second-key'


@pytest.mark.parametrize('fields', [
    {'base_url':'file:///etc/passwd'}, {'base_url':'http://user:password@host'},
    {'ssh_alias':'host; reboot'}, {'ssh_alias':'-oProxyCommand=sh'},
    {'camera_service':'webcamd;reboot'}, {'camera_service':'octoprint'},
    {'klipper_log':'/tmp/log; reboot'}, {'volume':[200,-1,200]},
    {'snapshot_url':'http://user:secret@camera/snapshot'},
])
def test_rejects_commands_and_invalid_connections(fields):
    with pytest.raises(ValueError):
        config.PrinterConfig(**{'name':'Invalid','base_url':'http://printer.local',**fields})


def test_saved_profile_and_overlay_hashes(tmp_path):
    base=tmp_path/'base.ini';base.write_text('nozzle_diameter = 0.6\n')
    overlay=tmp_path/'overlay.ini';overlay.write_text('infill_speed = 90\n')
    base_hash=printer_discovery.inspect_profile(str(base))['sha256']
    overlay_hash=printer_discovery.inspect_profile(str(overlay))['sha256']
    saved=config.save_printer(make_printer(profile_path=str(base),profile_sha256=base_hash,overlay_path=str(overlay),overlay_sha256=overlay_hash))
    config.select_printer(saved['id'])
    profile=selected_profile()
    assert profile['confirmed'] and profile['overlay_sha256']==overlay_hash
    overlay.write_text('changed')
    assert not selected_profile()['confirmed']


def test_probe_only_gets_and_never_saves(monkeypatch):
    calls=[]
    payloads={
      '/api/version':{'api':'0.1','text':'OctoPrint 1.11.8'},
      '/api/printer':{},
      '/api/printerprofiles':{'profiles':{'current':{'current':True,'volume':{'width':230,'depth':230,'height':200},'extruder':{'nozzleDiameter':0.6}}}},
      '/api/settings':{'webcam':{'snapshot':'http://camera.local/?action=snapshot'},'api':{'key':'must-not-leak'}}}
    class Client:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def get(self,url,**kwargs):
            path=httpx.URL(url).path;calls.append(path)
            return httpx.Response(200,json=payloads[path],request=httpx.Request('GET',url))
    monkeypatch.setattr(printer_discovery.httpx,'Client',Client)
    result=printer_discovery.probe_printer(make_printer())
    assert result['reachable'] and result['suggested']['volume']==[230,230,200]
    assert result['suggested']['snapshot_url'].startswith('http://camera.local')
    assert len(calls)==4 and not config.config_path().exists()
    assert 'must-not-leak' not in json.dumps(result) and 'private-key' not in json.dumps(result)


def test_no_ssh_assumption_without_configuration(monkeypatch):
    monkeypatch.setattr(host_checks,'active_printer',lambda:None)
    monkeypatch.setattr(host_checks.subprocess,'run',lambda *a,**k:pytest.fail('No configured SSH'))
    assert not host_checks.run_check('camera_logs')['available']


def test_camera_never_receives_octoprint_key(monkeypatch):
    saved=config.save_printer(make_printer(snapshot_url='http://camera.local/?action=snapshot'))
    config.select_printer(saved['id'])
    def get(url,**kwargs):
        assert url=='http://camera.local/?action=snapshot' and 'headers' not in kwargs
        return httpx.Response(200,content=b'jpeg',request=httpx.Request('GET',url))
    monkeypatch.setattr(octoprint.httpx,'get',get)
    assert octoprint.camera_snapshot()==b'jpeg'


def test_discovery_returns_candidates_without_selecting(monkeypatch):
    class ZC:
        def get_service_info(self,*args,**kwargs):
            return SimpleNamespace(properties={b'path':b'/printer',b'p':b'never-return-this'},port=5000,parsed_addresses=lambda:['192.168.0.2'])
        def close(self): pass
    class Browser:
        def __init__(self,zc,types,listener):listener.add_service(zc,'_octoprint._tcp.local.','Workshop._octoprint._tcp.local.')
        def cancel(self): pass
    monkeypatch.setitem(sys.modules,'zeroconf',SimpleNamespace(Zeroconf=ZC,ServiceBrowser=Browser))
    result=printer_discovery.discover_printers(seconds=0)
    assert result['candidates'][0]['base_url']=='http://192.168.0.2:5000/printer'
    assert 'never-return-this' not in json.dumps(result)
    assert not config.config_path().exists()


def test_saving_candidate_preserves_existing_environment_selection(monkeypatch):
    monkeypatch.setenv('OCTOPRINT_BASE_URL','http://existing.local')
    assert config.active_printer().id=='environment'
    saved=config.save_printer(make_printer())
    assert config.active_printer().id=='environment'
    config.select_printer(saved['id'])
    assert config.active_printer().id==saved['id']
    config.select_printer('environment')
    assert config.active_printer().base_url=='http://existing.local'


def test_changed_address_does_not_inherit_credentials():
    saved=config.save_printer(make_printer())
    config.save_printer(config.PrinterConfig(id=saved['id'],name='Moved',base_url='http://other.local'))
    assert config.get_printer_config(saved['id']).api_key==''


def test_selected_printer_does_not_inherit_another_log(tmp_path,monkeypatch):
    from backend.app.printer_logs import get_log_events
    source=tmp_path/'existing.log';source.write_text('Existing printer only\n')
    monkeypatch.setenv('CALICLAW_PRINTER_LOG',str(source))
    monkeypatch.setenv('OCTOPRINT_BASE_URL','http://existing.local')
    saved=config.save_printer(make_printer())
    assert get_log_events()['events']==[{'message':'Existing printer only'}]
    config.select_printer(saved['id'])
    assert not get_log_events()['available']
