"""Configured profile identity and immutable slice snapshots for explicit printing."""
import hashlib
import os
import tempfile
from pathlib import Path
from .printer_config import active_printer, config_path, connection_identity

ROOT = Path(__file__).resolve().parents[2]


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def selected_profile():
    printer = active_printer()
    legacy = not config_path().exists()
    configured = printer.profile_path if printer else (os.environ.get('CALICLAW_PROFILE_PATH') or os.environ.get('CALICLAW_SLICER_PROFILE', '')) if legacy else ''
    path = Path(configured) if configured else ROOT / 'profiles/ender3-proven-pla.ini'
    data = path.read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    expected = printer.profile_sha256 if printer else os.environ.get('CALICLAW_PROFILE_SHA256', '') if legacy else ''
    overlay_path = printer.overlay_path if printer else (os.environ.get('CALICLAW_OVERLAY_PATH') or os.environ.get('CALICLAW_SLICER_OVERLAY', '')) if legacy else ''
    overlay_expected = printer.overlay_sha256 if printer else os.environ.get('CALICLAW_OVERLAY_SHA256', '') if legacy else ''
    overlay = Path(overlay_path).read_bytes() if overlay_path else None
    overlay_sha = hashlib.sha256(overlay).hexdigest() if overlay is not None else None
    confirmed = bool(configured and expected and sha == expected.lower() and
                     (overlay is None or overlay_expected and overlay_sha == overlay_expected.lower()))
    return {'bytes': data, 'sha256': sha, 'confirmed': confirmed, 'overlay_bytes': overlay,
            'overlay_sha256': overlay_sha,
            'label': 'Confirmed machine profile' + (' + overlay' if overlay is not None else '') if confirmed else 'Unconfirmed profile' if configured else '0.4 mm fixture (not for live printing)'}


def profile_snapshot(profile):
    folder = Path(tempfile.mkdtemp(prefix='caliclaw-profile-'))
    path = folder / 'profile.ini'
    path.write_bytes(profile['bytes'])
    return path


def validate_preparation(preparation, mesh_path, revision_id, *, require_confirmed=True):
    if not preparation or not preparation.get('ok'):
        raise ValueError('Slice the checked part first.')
    profile = selected_profile()
    if require_confirmed and (not profile['confirmed'] or not preparation.get('profile_confirmed')):
        raise ValueError('A confirmed machine profile is required for live printing.')
    if profile['sha256'] != preparation['profile_sha256'] or profile['overlay_sha256'] != preparation.get('overlay_sha256'):
        raise ValueError('Profile changed. Slice again.')
    if preparation.get('printer_id') != printer_identity():
        raise ValueError('Selected printer changed. Slice again.')
    if revision_id != preparation['revision_id'] or not mesh_path or digest(mesh_path) != preparation['mesh_sha256']:
        raise ValueError('Part changed. Slice again.')
    if digest(preparation['gcode_path']) != preparation['gcode_sha256']:
        raise ValueError('G-code changed. Slice again.')


def printer_identity():
    return connection_identity()
