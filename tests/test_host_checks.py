from types import SimpleNamespace
import pytest
from backend.app import host_checks, poc_api
from fastapi import HTTPException
from backend.app.printer_config import PrinterConfig

@pytest.fixture(autouse=True)
def host_config(monkeypatch):
    config=PrinterConfig(name="Test",base_url="http://test.invalid",ssh_alias="test-camera-host",camera_service="webcamd",camera_restart="service")
    monkeypatch.setattr(host_checks,"active_printer",lambda:config)
    return config


IDLE = {'source': 'octoprint', 'state': 'Operational', 'flags': {'operational': True}, 'simulated': False}


def test_unknown_check_cannot_execute(monkeypatch):
    monkeypatch.setattr(host_checks.subprocess, 'run', lambda *a, **k: pytest.fail('must not execute'))
    with pytest.raises(ValueError):
        host_checks.run_check('reboot')


def test_fixed_command_and_redacted_output(monkeypatch):
    def run(args, **kwargs):
        assert args[-1] == 'journalctl -u webcamd -n 30 --no-pager -o cat | head -c 16384'
        return SimpleNamespace(returncode=0, stdout='octopi 192.168.1.4 https://private.local api_key=hidden {"token": "secret-value"}')
    monkeypatch.setattr(host_checks.subprocess, 'run', run)
    result = host_checks.run_check('camera_logs')
    assert result['available']
    for value in ['octopi', '192.168.1.4', 'private.local', 'hidden', 'secret-value']:
        assert value not in result['output']


@pytest.mark.parametrize('state', [
    {}, {**IDLE, 'simulated': True}, {**IDLE, 'state': 'Unknown'},
    {**IDLE, 'state': 'Printing'}, {**IDLE, 'state': 'Paused'},
    {**IDLE, 'flags': {'operational': True, 'printing': True}},
])
def test_recovery_refuses_unsafe_or_unknown_state(monkeypatch, state):
    monkeypatch.setattr(host_checks.subprocess, 'run', lambda *a, **k: pytest.fail('must not execute'))
    with pytest.raises(ValueError):
        host_checks.restart_camera(lambda: state)


def test_confirmed_recovery_targets_only_camera(monkeypatch):
    checks = iter([{'available': False}, {'available': True}])
    monkeypatch.setattr(host_checks, 'run_check', lambda name: next(checks))
    calls = []
    monkeypatch.setattr(host_checks.subprocess, 'run', lambda args, **kwargs: calls.append(args) or SimpleNamespace(returncode=0))
    result = host_checks.restart_camera(lambda: IDLE)
    assert result == {'restarted': True, 'snapshot_available': True}
    assert calls == [['ssh','-o','BatchMode=yes','-o','ConnectTimeout=5','test-camera-host','sudo -n /usr/sbin/service webcamd restart']]


def test_healthy_camera_is_not_restarted(monkeypatch):
    monkeypatch.setattr(host_checks, 'run_check', lambda name: {'available': True})
    monkeypatch.setattr(host_checks.subprocess, 'run', lambda *a, **k: pytest.fail('must not execute'))
    assert host_checks.restart_camera(lambda: IDLE)['restarted'] is False


def test_no_confirm_no_recovery(monkeypatch):
    monkeypatch.setattr(poc_api, 'restart_camera', lambda *a: pytest.fail('must not execute'))
    with pytest.raises(HTTPException):
        poc_api.camera_restart(poc_api.ControlRequest(confirm=False))


def test_state_change_before_restart_refuses(monkeypatch):
    monkeypatch.setattr(host_checks, 'run_check', lambda name: {'available': False})
    states = iter([IDLE, {}])
    with pytest.raises(ValueError):
        host_checks.restart_camera(lambda: next(states))
