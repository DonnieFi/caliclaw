"""Live diagnosis never silently substitutes evaluation evidence."""
import json
import os

from backend.app.printer_logs import MAX_LOG_BYTES, get_log_events


def test_no_source_is_unavailable(monkeypatch):
    monkeypatch.delenv('CALICLAW_PRINTER_LOG', raising=False)
    assert get_log_events() == {
        'available': False, 'events': [], 'reason': 'Printer log unavailable.'}


def test_configured_log_is_redacted_with_provenance(tmp_path, monkeypatch):
    source = tmp_path / 'printer.log'
    source.write_text('Connected\napi_key=plain-secret\n{"token": "quoted-secret"}\nhttp://printer/?key=url-secret\n')
    monkeypatch.setenv('CALICLAW_PRINTER_LOG', str(source))
    result = get_log_events()
    encoded = json.dumps(result)
    assert result['available']
    assert result['events'][0]['message'] == 'Connected'
    assert result['source_updated_at']
    assert not result['truncated']
    for secret in ['plain-secret', 'quoted-secret', 'url-secret', str(source)]:
        assert secret not in encoded


def test_unreadable_source_does_not_fall_back(tmp_path, monkeypatch):
    monkeypatch.setenv('CALICLAW_PRINTER_LOG', str(tmp_path / 'missing'))
    assert not get_log_events()['available']
    monkeypatch.setenv('CALICLAW_PRINTER_LOG', str(tmp_path))
    assert not get_log_events()['available']


def test_fifo_does_not_block(tmp_path, monkeypatch):
    source = tmp_path / 'fifo'
    os.mkfifo(source)
    monkeypatch.setenv('CALICLAW_PRINTER_LOG', str(source))
    assert not get_log_events()['available']


def test_tail_discards_partial_secret_line(tmp_path, monkeypatch):
    source = tmp_path / 'printer.log'
    source.write_text('password=' + 's' * MAX_LOG_BYTES + '\nLatest event\n')
    monkeypatch.setenv('CALICLAW_PRINTER_LOG', str(source))
    result = get_log_events()
    assert result['truncated']
    assert result['events'] == [{'message': 'Latest event'}]


def test_chat_tool_reports_missing_source(monkeypatch):
    from fastapi import Request, Response
    from backend.app import poc_api
    from backend.app.provider import ProviderResponse

    monkeypatch.delenv('CALICLAW_PRINTER_LOG', raising=False)
    monkeypatch.setattr(poc_api, 'reflection_config_from_env', lambda: object())
    monkeypatch.setattr(poc_api, 'PROJECT', None)
    monkeypatch.setattr(poc_api, '_sessions', {})

    class Provider:
        def chat(self, messages, **kwargs):
            results = [m for m in messages if m['role'] == 'tool']
            if not results:
                return ProviderResponse(content='', tool_calls=[{
                    'id': 'log', 'function': {'name': 'get_log_events', 'arguments': '{}'}
                }], finish_reason='tool_calls', usage={})
            payload = json.loads(results[-1]['content'])
            assert payload['available'] is False
            assert payload['events'] == []
            assert 'log' not in payload
            return ProviderResponse(content='Printer log unavailable.', tool_calls=[], finish_reason='stop', usage={})

    monkeypatch.setattr(poc_api, 'ProviderAdapter', lambda cfg: Provider())
    result = poc_api.chat(poc_api.ChatRequest(message='Diagnose the printer'),
                         Request({'type': 'http', 'headers': []}), Response())
    assert result.reply == 'Printer log unavailable.'
