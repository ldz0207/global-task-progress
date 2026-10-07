"""Check runtime dependencies and local service readiness; no package installs."""
import argparse
import importlib
import json
import os
from pathlib import Path
import sys

MIN_VERSION = (3, 10)
MODULES = (
    'argparse', 'contextlib', 'copy', 'dataclasses', 'datetime', 'hashlib',
    'http.server', 'json', 'math', 'pathlib', 'shutil', 'socket', 'sqlite3',
    'subprocess', 'threading', 'time', 'urllib.request', 'uuid',
    'concurrent.futures', 'tempfile',
)
IDENTITY = 'agent-global-progress-v1'
PORT = 8790


def runtime_check():
    missing = []
    for name in MODULES + (('msvcrt',) if os.name == 'nt' else ('fcntl',)):
        try:
            importlib.import_module(name)
        except (ImportError, OSError) as exc:
            missing.append({'module': name, 'error': str(exc)})
    result = {'ok': sys.version_info[:2] >= MIN_VERSION and not missing,
              'executable': sys.executable, 'version': sys.version.split()[0],
              'minimum': '3.10', 'missing_modules': missing,
              'third_party_packages': []}
    if result['ok']:
        try:
            import hashlib
            import sqlite3
            with sqlite3.connect(':memory:') as db:
                if db.execute('select 1').fetchone() != (1,):
                    raise RuntimeError('SQLite query verification failed')
            if hashlib.sha256(b'abc').hexdigest() != 'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad':
                raise RuntimeError('SHA-256 verification failed')
            result['sqlite_version'] = sqlite3.sqlite_version
        except Exception as exc:
            result.update(ok=False, error=str(exc))
    return result


def storage_check(state):
    """Use a unique disposable directory; never change existing task files."""
    import tempfile
    try:
        if not state.is_absolute():
            raise ValueError('state_dir must be an absolute path')
        if not Path(state.anchor).is_dir():
            raise ValueError('Data drive is unavailable; choose an explicit available directory')
        if state.exists() and not state.is_dir():
            raise ValueError('state_dir is a file, not a directory')
        parent = state
        while not parent.exists():
            parent = parent.parent
        with tempfile.TemporaryDirectory(prefix='.progress-check-', dir=parent) as folder:
            original = Path(folder) / 'check.part'
            final = Path(folder) / 'check.json'
            with original.open('x', encoding='utf-8') as stream:
                json.dump({'ok': True}, stream)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(original, final)
            if json.loads(final.read_text(encoding='utf-8')) != {'ok': True}:
                raise OSError('Atomic write/read verification failed')
        return {'ok': True, 'state_dir': str(state.resolve()), 'checked_parent': str(parent)}
    except (OSError, ValueError) as exc:
        return {'ok': False, 'state_dir': str(state), 'error': str(exc)}


def service_check(state, port=None):
    import socket
    import urllib.error
    import urllib.request
    from task_progress import resolve_port, guard_port_change, free_ports, service_url
    port = resolve_port(state, port)
    guard_port_change(state, port)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(service_url(port) + 'api/health', timeout=2) as response:
            value = json.load(response)
        if value.get('identity') != IDENTITY:
            raise ValueError('Selected port belongs to another service')
        actual = value.get('state_dir')
        if not actual or not Path(actual).is_absolute() or Path(actual).resolve() != state.resolve():
            raise ValueError('Existing service uses a different data directory; reuse it explicitly')
        if value.get('port') is not None and value['port'] != port:
            raise ValueError('Health response port does not match the selected port')
        return {'ok': True, 'status': 'reuse', 'port': port, 'url': service_url(port), 'pid': value.get('pid')}
    except urllib.error.HTTPError as exc:
        return {'ok': False, 'status': 'conflict', 'port': port, 'error': str(exc), 'available_ports': free_ports()}
    except urllib.error.URLError:
        # A failed HTTP connection may still mean an occupied/non-HTTP port.
        try:
            with socket.socket() as probe:
                if os.name == 'nt':
                    probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
                probe.bind(('127.0.0.1', port))
            return {'ok': True, 'status': 'available', 'port': port, 'url': service_url(port)}
        except OSError as exc:
            return {'ok': False, 'status': 'conflict', 'port': port, 'error': str(exc), 'available_ports': free_ports()}
    except (OSError, ValueError, TypeError, AttributeError) as exc:
        return {'ok': False, 'status': 'conflict', 'port': port, 'error': str(exc), 'available_ports': free_ports()}


def check_environment(state, *, runtime_only=False, port=None, select_port=False):
    runtime = runtime_check()
    checks = {'runtime': runtime}
    if not runtime_only and runtime['ok']:
        folder = Path(__file__).resolve().parent
        required = ('task_progress.py', 'worker_helpers.py', 'progress_page.html')
        missing = [name for name in required if not (folder / name).is_file()]
        checks['skill_files'] = {'ok': not missing, 'missing': missing}
        checks['storage'] = storage_check(Path(state))
        if checks['storage']['ok'] and checks['skill_files']['ok']:
            try:
                checks['service'] = service_check(Path(state), port)
                if checks['service']['ok'] and select_port:
                    from task_progress import configure_port
                    configure_port(state, checks['service']['port'])
                    checks['service']['selection_saved'] = True
            except (OSError, ValueError, RuntimeError) as exc:
                checks['service'] = {'ok': False, 'status': 'conflict', 'error': str(exc)}
        else:
            checks['service'] = {'ok': False, 'status': 'not_checked'}
    return {'ready': all(item['ok'] for item in checks.values()), 'checks': checks}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime-only', action='store_true')
    parser.add_argument('--state-dir', default=os.environ.get('TASK_PROGRESS_STATE_DIR'))
    parser.add_argument('--port', type=int)
    parser.add_argument('--select-port', action='store_true', help='Save a verified user choice without starting a server')
    args = parser.parse_args()
    state = args.state_dir
    if not state and os.name == 'nt':
        state = 'D:/Codex/维护/统一任务进度/运行数据'
    if not state and not args.runtime_only:
        parser.error('--state-dir is required on this platform')
    if args.select_port and args.port is None:
        parser.error('--select-port requires an explicit --port')
    report = check_environment(state, runtime_only=args.runtime_only, port=args.port, select_port=args.select_port)
    print(json.dumps(report, ensure_ascii=True, indent=2))
    return 0 if report['ready'] else 1


if __name__ == '__main__':
    sys.exit(main())
