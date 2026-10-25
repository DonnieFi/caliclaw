"""Private printer connections. Discovery proposes; only operator setup selects."""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import threading
import uuid
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator

_LOCK = threading.RLock()


def normalized_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError('Use an HTTP(S) address without credentials, query or fragment.')
    _ = parsed.port  # validate port syntax
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip('/'), '', ''))


class PrinterConfig(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: str = ''
    name: str = Field(min_length=1, max_length=80)
    transport: Literal['octoprint'] = 'octoprint'
    base_url: str
    api_key: str = ''
    firmware: Literal['unknown', 'klipper', 'marlin', 'other'] = 'unknown'
    volume: tuple[float, float, float] | None = None
    nozzle: float | None = Field(default=None, gt=0, le=5)
    profile_path: str = ''
    profile_sha256: str = ''
    overlay_path: str = ''
    overlay_sha256: str = ''
    snapshot_url: str = ''
    ssh_alias: str = ''
    camera_service: str = ''
    camera_restart: Literal['disabled', 'service', 'systemctl'] = 'disabled'
    klipper_log: str = ''
    local_log: str = ''

    @field_validator('base_url')
    @classmethod
    def valid_base(cls, value):
        return normalized_url(value)

    @field_validator('snapshot_url')
    @classmethod
    def valid_snapshot(cls, value):
        return cls._snapshot(value)

    @staticmethod
    def _snapshot(value):
        if not value:
            return ''
        parsed = urlsplit(value)
        if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
            raise ValueError('Use an HTTP(S) snapshot address without credentials.')
        return value

    @field_validator('ssh_alias')
    @classmethod
    def valid_alias(cls, value):
        if value and not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}', value):
            raise ValueError('Use an SSH config alias, not a command.')
        return value

    @field_validator('camera_service')
    @classmethod
    def valid_service(cls, value):
        if value and (not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.@-]{0,100}', value) or any(s in value.lower() for s in ('octoprint', 'ssh', 'network', 'klipper'))):
            raise ValueError('Choose a camera-only service name.')
        return value

    @field_validator('klipper_log')
    @classmethod
    def valid_log(cls, value):
        if value and not re.fullmatch(r'/[A-Za-z0-9_/.-]{1,240}', value):
            raise ValueError('Use an absolute log path without shell syntax.')
        return value

    @field_validator('volume')
    @classmethod
    def valid_volume(cls, value):
        import math
        if value and any(not math.isfinite(n) or n <= 0 or n > 10000 for n in value):
            raise ValueError('Build volume dimensions must be positive millimetres.')
        return value


def config_path():
    return Path(os.environ.get('CALICLAW_PRINTER_CONFIG', 'printers.local.json'))


def _read():
    path = config_path()
    if not path.exists():
        return {'active_id': 'environment' if os.environ.get('OCTOPRINT_BASE_URL', '').strip() else None, 'printers': []}
    return json.loads(path.read_text())


def _write(data):
    path = config_path().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.printers-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(data, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def environment_printer():
    url = os.environ.get('OCTOPRINT_BASE_URL', '').strip()
    if not url:
        return None
    try:
        return PrinterConfig(id='environment', name='Environment printer', base_url=url,
                         api_key=os.environ.get('OCTOPRINT_API_KEY', ''),
                         profile_path=(os.environ.get('CALICLAW_PROFILE_PATH') or os.environ.get('CALICLAW_SLICER_PROFILE', '')),
                         profile_sha256=os.environ.get('CALICLAW_PROFILE_SHA256', ''),
                         overlay_path=(os.environ.get('CALICLAW_OVERLAY_PATH') or os.environ.get('CALICLAW_SLICER_OVERLAY', '')),
                         overlay_sha256=os.environ.get('CALICLAW_OVERLAY_SHA256', ''),
                         snapshot_url=os.environ.get('CALICLAW_SNAPSHOT_URL', ''),
                         local_log=os.environ.get('CALICLAW_PRINTER_LOG', ''))

    except ValueError:
        return None


def active_printer():
    with _LOCK:
        if not config_path().exists():
            return environment_printer()
        data = _read()
        if data['active_id'] == 'environment':
            return environment_printer()
        return next((PrinterConfig(**p) for p in data['printers'] if p['id'] == data['active_id']), None)


def public_printer(printer):
    return {'id': printer.id, 'name': printer.name, 'transport': printer.transport,
            'firmware': printer.firmware, 'volume': printer.volume, 'nozzle': printer.nozzle,
            'has_key': bool(printer.api_key), 'has_profile': bool(printer.profile_path),
            'has_overlay': bool(printer.overlay_path), 'has_camera': bool(printer.snapshot_url),
            'has_host_checks': bool(printer.ssh_alias),
            'has_camera_recovery': bool(printer.ssh_alias and printer.camera_service and printer.camera_restart != 'disabled')}


def list_printers():
    with _LOCK:
        data = _read()
        printers = [PrinterConfig(**p) for p in data['printers']]
        active = active_printer()
        environment = environment_printer()
        if environment:
            printers.insert(0, environment)
        return {'active_id': active.id if active else None, 'printers': [public_printer(p) for p in printers]}


def save_printer(printer):
    with _LOCK:
        data = _read()
        if not printer.id:
            printer = printer.model_copy(update={'id': uuid.uuid4().hex})
        elif not any(p['id'] == printer.id for p in data['printers']):
            raise ValueError('Unknown saved printer.')
        previous = next((p for p in data['printers'] if p['id'] == printer.id), {})
        if not printer.api_key and previous and previous.get('base_url') == printer.base_url:
            printer = printer.model_copy(update={'api_key': previous.get('api_key', '')})
        data['printers'] = [p for p in data['printers'] if p['id'] != printer.id] + [printer.model_dump()]
        _write(data)
        return public_printer(printer)


def select_printer(printer_id):
    with _LOCK:
        data = _read()
        if not (printer_id == 'environment' and environment_printer()) and not any(p['id'] == printer_id for p in data['printers']):
            raise ValueError('Unknown saved printer.')
        data['active_id'] = printer_id
        _write(data)
        return list_printers()


def connection_identity():
    printer = active_printer()
    data = printer.model_dump() if printer else {}
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


def get_printer_config(printer_id):
    with _LOCK:
        return next((PrinterConfig(**p) for p in _read()['printers'] if p['id'] == printer_id), None)
