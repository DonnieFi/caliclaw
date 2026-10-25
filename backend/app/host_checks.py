"""Fixed printer-host evidence checks. No shell or path input from clients/models."""
import json
import os
import re
import subprocess
import shlex
from urllib.parse import urlsplit
from .printer_config import active_printer

from .collector import redact_text
from .octoprint import camera_snapshot, get_job

CHECK_NAMES = ('job_state', 'snapshot', 'camera_service', 'camera_logs', 'klipper_log')


def host_command(name, config):
    if not config or not config.ssh_alias:
        raise ValueError('SSH host checks are not configured for this printer.')
    service = shlex.quote(config.camera_service)
    if name == 'camera_service' and config.camera_service:
        command = f'systemctl show {service} --property=ActiveState,SubState --no-pager'
    elif name == 'camera_logs' and config.camera_service:
        command = f'journalctl -u {service} -n 30 --no-pager -o cat | head -c 16384'
    elif name == 'klipper_log' and config.klipper_log:
        command = f'tail -n 50 -- {shlex.quote(config.klipper_log)} | head -c 16384'
    else:
        raise ValueError('Host check is not configured.')
    return ['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=5', config.ssh_alias, command]


def safe_output(text):
    config = active_printer()
    if config:
        for value in [config.api_key, urlsplit(config.base_url).hostname, config.ssh_alias]:
            if value:
                text = text.replace(value, '<redacted>')
    # Redact actual configured credentials before general patterns.
    for name, value in os.environ.items():
        if value and len(value) >= 4 and any(s in name.lower() for s in ('key', 'token', 'password', 'secret')):
            text = text.replace(value, '<redacted>')
    text = re.sub(r'''(?i)(["']?(?:api[_-]?key|token|password|secret|authorization)["']?\s*[:=]\s*)(?:"[^"\n]*"|'[^'\n]*'|[^\s,}]+)''', r'\1<redacted>', text)
    text = redact_text(text)
    text = re.sub(r'https?://[^\s<>]+', '<address>', text)
    text = re.sub(r'\b(?:\d{1,3}\.){3}\d{1,3}\b|\b(?:[0-9a-fA-F]{0,4}:){2,}[0-9a-fA-F:]+\b', '<address>', text)
    text = re.sub(r'\b[\w-]+(?:\.[\w-]+)*\.(?:local|lan|com|net|org|io)\b', '<host>', text)
    text = re.sub(r'\b(?:octopi|localhost)\b', '<host>', text, flags=re.I)
    return text[:16384]


def run_check(name):
    if name not in CHECK_NAMES:
        raise ValueError('Unknown host check.')
    try:
        if name == 'job_state':
            job = get_job()
            text = json.dumps({'state': job.get('state', 'Unknown'), 'progress': job.get('progress')})
            code = 0
        elif name == 'snapshot':
            data = camera_snapshot()
            code = 0 if data.startswith(b'\xff\xd8\xff') else 1
            text = 'JPEG snapshot available.' if code == 0 else 'Snapshot unavailable.'
        else:
            result = subprocess.run(host_command(name, active_printer()), capture_output=True, text=True, timeout=12)
            code = result.returncode
            text = result.stdout if code == 0 else 'Check unavailable.'
        return {'name': name, 'exit': code, 'output': safe_output(text), 'available': code == 0}
    except (OSError, subprocess.TimeoutExpired, RuntimeError, ValueError):
        return {'name': name, 'exit': None, 'output': 'Check unavailable.', 'available': False}
    except Exception:
        # Client/network errors must not reveal connection strings or credentials.
        return {'name': name, 'exit': None, 'output': 'Check unavailable.', 'available': False}


def known_idle(status):
    flags = status.get('flags') or {}
    return (not status.get('simulated') and status.get('source') == 'octoprint'
            and status.get('state', '').lower() in ('operational', 'ready', 'idle')
            and flags.get('operational') is True
            and not any(flags.get(key) for key in ('printing', 'paused', 'pausing', 'cancelling', 'finishing', 'error', 'closedOrError')))


def restart_camera(status_reader):
    if not known_idle(status_reader()):
        raise ValueError('Camera recovery requires a known-idle printer.')
    if run_check('snapshot')['available']:
        return {'restarted': False, 'snapshot_available': True}
    if not known_idle(status_reader()):
        raise ValueError('Printer state changed. Camera recovery refused.')
    config = active_printer()
    if not config or not config.ssh_alias or not config.camera_service or config.camera_restart == 'disabled':
        raise ValueError('Camera recovery is not configured for this printer.')
    service = shlex.quote(config.camera_service.removesuffix('.service'))
    command = (f'sudo -n /usr/sbin/service {service} restart' if config.camera_restart == 'service'
               else f'sudo -n systemctl restart {service}.service')
    args = ['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=5', config.ssh_alias, command]
    try:
        result = subprocess.run(args, capture_output=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError('Camera service restart unavailable.') from exc
    if result.returncode != 0:
        raise ValueError('Camera service restart was not permitted.')
    return {'restarted': True, 'snapshot_available': run_check('snapshot')['available']}
