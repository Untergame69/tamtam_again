"""Fresh filesystem/process namespace and tool-free Hermes/Codex inference."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = Path('/home/Untergame/tamtam-origin/hermes-agent')

def command(home: Path, *, offline: bool = False) -> list[str]:
    if not shutil.which('bwrap'):
        raise RuntimeError('Bubblewrap unavailable; no unisolated fallback')
    args = ['bwrap', '--die-with-parent', '--unshare-user', '--unshare-pid',
            '--unshare-ipc', '--unshare-uts', '--new-session', '--cap-drop', 'ALL',
            '--clearenv', '--setenv', 'PATH', '/usr/bin:/bin',
            '--setenv', 'HERMES_HOME', '/agent-home', '--setenv', 'HERMES_SAFE_MODE', '1',
            '--setenv', 'HERMES_IGNORE_RULES', '1', '--setenv', 'HERMES_IGNORE_USER_CONFIG', '1',
            '--setenv', 'PYTHONDONTWRITEBYTECODE', '1']
    if offline:
        args += ['--unshare-net']
    for path in ['/usr', '/lib', '/lib64']:
        if Path(path).exists():
            args += ['--ro-bind', path, path]
    args += ['--proc', '/proc', '--dev', '/dev', '--tmpfs', '/tmp']
    interpreter_root = (RUNTIME/'venv/bin/python').resolve().parents[1]
    if not str(interpreter_root).startswith('/usr/'):
        args += ['--ro-bind', str(interpreter_root), str(interpreter_root)]
        import os
        link_root = Path(os.readlink(RUNTIME/'venv/bin/python')).parents[1]
        if link_root != interpreter_root:
            args += ['--ro-bind', str(interpreter_root), str(link_root)]
    # Only DNS/TLS system configuration; no host home or application configs.
    for path in ['/etc/resolv.conf', '/etc/hosts', '/etc/nsswitch.conf', '/etc/ssl/certs']:
        args += ['--ro-bind', path, path]
    # Explicit code allowlist. Never mount Hermes reports, skills, MCP, .git or .env.
    for file in sorted(RUNTIME.glob('*.py')):
        args += ['--ro-bind', str(file), str(file)]
    for name in ['agent', 'tools', 'hermes_cli', 'providers', 'cron', 'gateway', 'acp_adapter', 'plugins', 'venv']:
        path = RUNTIME/name
        args += ['--ro-bind', str(path), str(path)]
    args += ['--bind', str(home), '/agent-home',
             '--ro-bind', str(ROOT/'scripts/isolated-inference.py'), '/runner.py',
             '--chdir', '/tmp', '--', str(RUNTIME/'venv/bin/python'), '/runner.py']
    return args

class InferenceExecutionError(RuntimeError):
    def __init__(self,diagnostic):
        self.diagnostic=diagnostic
        super().__init__(diagnostic['code'])


def infer(request: dict[str, Any], *, timeout_seconds: int = 120, on_response=None) -> dict[str, Any]:
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix='tamtam-inference-') as directory:
        home = Path(directory)
        if not request.get('probe'):
            # Credentials belong to the trusted inference client, not model tools.
            # Fresh disposable auth state permits token refresh without changing host state.
            shutil.copyfile('/home/Untergame/.hermes/auth.json', home/'auth.json')
            (home/'auth.json').chmod(0o600)
        result = subprocess.run(command(home, offline=bool(request.get('probe'))),
                                input=json.dumps(request), capture_output=True, text=True,
                                timeout=timeout_seconds, check=False)
        try:
            response = json.loads(result.stdout)
        except ValueError:
            raise RuntimeError(f'Isolated inference failed (exit {result.returncode})') from None
        response['duration_ms'] = int((time.monotonic()-started)*1000)
        if on_response is not None:
            on_response(response)
        if result.returncode or response.get('failed'):
            raise InferenceExecutionError({'stage':'provider_execution','code':'isolated_inference_failed',
                'field':'failed','observed':{'failed':bool(response.get('failed')),
                    'error_type':response.get('error_type'),'missing_module':response.get('missing_module'),
                    'exit_code':result.returncode},'limit':'successful isolated provider response'})
        return response

def verify(model: str = 'gpt-6.1-sol', probe_paths: list[str] | None = None) -> dict[str, Any]:
    return infer({'probe': True, 'model': model, 'probe_paths': probe_paths or []})
