"""Configured profile identity and immutable slice snapshots for explicit printing."""
import hashlib
import os
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def selected_profile():
    configured = os.environ.get('CALICLAW_PROFILE_PATH', '').strip()
    path = Path(configured) if configured else ROOT / 'profiles/ender3-proven-pla.ini'
    data = path.read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    expected = os.environ.get('CALICLAW_PROFILE_SHA256', '').strip().lower()
    confirmed = bool(configured and expected and sha == expected)
    return {'bytes': data, 'sha256': sha, 'confirmed': confirmed,
            'label': 'Confirmed machine profile' if confirmed else 'Unconfirmed profile' if configured else '0.4 mm fixture (not for live printing)'}


def profile_snapshot(profile):
    folder = Path(tempfile.mkdtemp(prefix='caliclaw-profile-'))
    path = folder / 'profile.ini'
    path.write_bytes(profile['bytes'])
    return path


def validate_preparation(preparation, mesh_path, revision_id):
    if not preparation or not preparation.get('ok'):
        raise ValueError('Slice the checked part first.')
    profile = selected_profile()
    if not profile['confirmed'] or not preparation.get('profile_confirmed'):
        raise ValueError('A confirmed machine profile is required for live printing.')
    if profile['sha256'] != preparation['profile_sha256']:
        raise ValueError('Profile changed. Slice again.')
    if revision_id != preparation['revision_id'] or not mesh_path or digest(mesh_path) != preparation['mesh_sha256']:
        raise ValueError('Part changed. Slice again.')
    if digest(preparation['gcode_path']) != preparation['gcode_sha256']:
        raise ValueError('G-code changed. Slice again.')


def printer_identity():
    # Internal fingerprint only; never expose address or API key to the browser.
    identity = os.environ.get('OCTOPRINT_BASE_URL', '').rstrip('/') + '\0' + os.environ.get('OCTOPRINT_API_KEY', '')
    return hashlib.sha256(identity.encode()).hexdigest()
