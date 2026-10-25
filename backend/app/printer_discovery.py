"""Read-only mDNS discovery and bounded probes; no automatic printer selection."""
import threading
from urllib.parse import urljoin
import httpx

from .printer_config import PrinterConfig, normalized_url


def discover_printers(seconds=3):
    try:
        from zeroconf import ServiceBrowser, Zeroconf
    except ImportError:
        return {'candidates': [], 'message': 'Network discovery is not installed. Enter an OctoPrint address manually.'}
    found = {}
    lock = threading.Lock()

    class Listener:
        def add_service(self, zc, type_, name):
            info = zc.get_service_info(type_, name, timeout=500)
            if not info:
                return
            props = {k.decode(errors='replace'): v.decode(errors='replace') if v else '' for k, v in info.properties.items()}
            if type_ == '_http._tcp.local.' and props.get('type', '').lower() != 'octoprint':
                return
            addresses = info.parsed_addresses()
            if not addresses or not 0 < info.port <= 65535:
                return
            host = addresses[0]
            if ':' in host:
                host = '[' + host + ']'
            path = props.get('path', '/')
            if not path.startswith('/') or path.startswith('//'):
                path = '/'
            try:
                url = normalized_url(f'http://{host}:{info.port}{path}')
            except ValueError:
                return
            with lock:
                if len(found) < 32:
                    found[url] = {'name': name.split('._')[0][:80], 'base_url': url, 'source': 'mdns', 'verified': False}
        def update_service(self, zc, type_, name):
            self.add_service(zc, type_, name)
        def remove_service(self, zc, type_, name):
            pass
    zc = None
    browser = None
    try:
        zc = Zeroconf()
        browser = ServiceBrowser(zc, ['_octoprint._tcp.local.', '_http._tcp.local.'], listener=Listener())
        threading.Event().wait(min(5, max(0, seconds)))
        with lock:
            candidates = list(found.values())
        return {'candidates': candidates, 'message': 'Select a candidate to review and test. Discovery does not activate it.' if candidates else 'No advertised printers found. Enter an OctoPrint address manually.'}
    except OSError:
        return {'candidates': [], 'message': 'Network discovery unavailable. Enter an OctoPrint address manually.'}
    finally:
        if browser:
            browser.cancel()
        if zc:
            zc.close()


def inspect_profile(path):
    import hashlib
    from pathlib import Path
    file = Path(path)
    if not file.is_file() or file.stat().st_size > 1024 * 1024:
        raise ValueError('Profile must be a readable INI file below 1 MiB.')
    data = file.read_bytes()
    allowed = {'nozzle_diameter', 'gcode_flavor', 'bed_shape', 'max_print_height', 'first_layer_speed', 'retract_lift'}
    fields = {}
    for line in data.decode(errors='replace').splitlines():
        key, separator, value = line.partition('=')
        if separator and key.strip() in allowed:
            fields[key.strip()] = value.strip()[:200]
    return {'sha256': hashlib.sha256(data).hexdigest(), 'settings': fields}


def probe_printer(config: PrinterConfig):
    """Only GET requests. A reachable OctoPrint host is not firmware readiness."""
    headers = {'X-Api-Key': config.api_key} if config.api_key else {}
    try:
        with httpx.Client(timeout=4, follow_redirects=False) as client:
            response = client.get(config.base_url + '/api/version', headers=headers)
            response.raise_for_status()
            version = response.json()
            if 'api' not in version or not str(version.get('text', '')).startswith('OctoPrint'):
                return {'reachable': False, 'message': 'Endpoint did not identify itself as OctoPrint.'}
            result = {'reachable': True, 'transport': 'octoprint', 'message': 'OctoPrint responded. Review settings before saving.', 'capabilities': {'status': False, 'printer_profiles': False, 'camera_settings': False}, 'suggested': {}}
            for endpoint in ['printer', 'printerprofiles', 'settings']:
                response = client.get(config.base_url + '/api/' + endpoint, headers=headers)
                if response.status_code != 200:
                    continue
                data = response.json()
                if endpoint == 'printer':
                    result['capabilities']['status'] = True
                if endpoint == 'printerprofiles':
                    result['capabilities']['printer_profiles'] = True
                    profiles = data.get('profiles', {})
                    profile = next((p for p in profiles.values() if p.get('current')), None)
                    if profile:
                        volume = profile.get('volume', {})
                        dimensions = [volume.get(key) for key in ('width', 'depth', 'height')]
                        if all(isinstance(n, (int, float)) and 0 < n <= 10000 for n in dimensions):
                            result['suggested']['volume'] = dimensions
                        nozzle = profile.get('extruder', {}).get('nozzleDiameter')
                        if isinstance(nozzle, (int, float)) and 0 < nozzle <= 5:
                            result['suggested']['nozzle'] = nozzle
                if endpoint == 'settings':
                    result['capabilities']['camera_settings'] = True
                    # Legacy compatibility fields remain available in OctoPrint 1.x.
                    snapshot = (data.get('webcam') or {}).get('snapshot')
                    if not snapshot:
                        for webcam in (data.get('webcam') or {}).get('webcams', []):
                            snapshot = (webcam.get('compat') or {}).get('snapshot')
                            if snapshot:
                                break
                    if snapshot:
                        try:
                            candidate = urljoin(config.base_url + '/', snapshot)
                            checked = PrinterConfig(name='candidate', base_url=config.base_url, snapshot_url=candidate)
                            result['suggested']['snapshot_url'] = checked.snapshot_url
                        except ValueError:
                            pass
            return result
    except (httpx.HTTPError, ValueError, TypeError, KeyError):
        return {'reachable': False, 'message': 'Connection failed or access denied. Check the address, API key and permissions.'}
