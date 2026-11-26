#!/usr/bin/python3
"""Fixed, read-only diagnostic commands for a specifically named Compute Engine VM.

Install root-owned at /usr/local/sbin/pokemoniv-readonly-diagnostics and allow
only that exact executable and its approved arguments through sudoers.
No user-provided paths, shell commands, environment values, or payloads are read.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from urllib.request import urlopen

CONTAINER = 'pokemoniv-web-1'
DOCKER = '/usr/bin/docker'
DATA = Path('/srv/pokemoniv/data')
ARCHIVE = DATA / 'pvpoke_archives'
CHECKS = ('health', 'storage', 'missing')


def docker(*args: str, timeout: int = 20) -> str:
    completed = subprocess.run(
        (DOCKER, *args), capture_output=True, text=True, timeout=timeout,
        check=False, env={'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8'},
    )
    if completed.returncode:
        raise RuntimeError('Docker diagnostic command failed')
    return completed.stdout.strip()


def health() -> None:
    status = docker('inspect', '--format', '{{.State.Status}}|{{.State.Health.Status}}|{{.Config.Image}}', CONTAINER)
    state, checks, image = status.split('|', 2)
    print(f'container_state={state}')
    print(f'container_health={checks}')
    print(f'image={image}')
    with urlopen('http://127.0.0.1:8787/health', timeout=8) as response:
        print(f'local_health_http={response.status}')
        if response.status != 200:
            raise RuntimeError('Health HTTP is not 200')
    if state != 'running' or checks != 'healthy':
        raise RuntimeError('Container is not healthy')


def storage() -> None:
    mounts = json.loads(docker('inspect', '--format', '{{json .Mounts}}', CONTAINER))
    sources = {item.get('Destination'): item.get('Source') for item in mounts}
    print('data_mount_correct=' + str(sources.get('/data') == str(DATA)).lower())
    print('work_mount_correct=' + str(sources.get('/home/appuser/pvpoke_automation_web') == '/srv/pokemoniv/work').lower())
    if not DATA.is_dir():
        raise RuntimeError('Persistent data directory is missing')
    fs = os.statvfs(DATA)
    print(f'data_free_mib={(fs.f_bavail * fs.f_frsize) // (1024 * 1024)}')
    for name in ('auth.sqlite3', 'matchups.sqlite3', 'team_builder.sqlite3', 'battle_analysis.sqlite3'):
        db = ARCHIVE / name
        print(f'{name}_exists={str(db.is_file()).lower()}')
        if db.is_file():
            print(f'{name}_bytes={db.stat().st_size}')
    if sources.get('/data') != str(DATA):
        raise RuntimeError('Persistent data mount has changed')


def missing() -> None:
    snippet = '''import json,os
from pathlib import Path
from urllib.request import urlopen
from pvpoke_batch_v2 import DATA
with urlopen("http://127.0.0.1:8765/api/catalog",timeout=12) as response:
    catalog=json.load(response)
print("catalog_ready="+str(catalog.get("ready") is True).lower())
print("catalog_species="+str(len(catalog.get("species",{}))))
print("catalog_error_present="+str(bool(catalog.get("error"))).lower())
print("game_data_present="+str((DATA/"gamemaster.json").is_file()).lower())
print("missing_enabled="+str(os.getenv("PVP_MISSING_ANALYSIS_ENABLED")=="1").lower())
print("battle_api_enabled="+str(os.getenv("PVP_BATTLE_API_ENABLED")=="1").lower())
print("sandbox_enabled="+str(os.getenv("PVP_SANDBOX_ENABLED")=="1").lower())'''
    print(docker('exec', '--user', '10001', '--env', 'HOME=/home/appuser',
                 '--workdir', '/app', CONTAINER, 'python', '-c', snippet))
    print('battle_analysis_db_present=' + str((ARCHIVE / 'battle_analysis.sqlite3').is_file()).lower())


def main() -> int:
    parser = argparse.ArgumentParser(description='Fixed, read-only Pokémon IV VM checks')
    parser.add_argument('check', choices=CHECKS)
    args = parser.parse_args()
    if os.geteuid() != 0:
        print('Must run as root via restricted sudoers rule', file=sys.stderr)
        return 2
    try:
        {'health': health, 'storage': storage, 'missing': missing}[args.check]()
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
        print('diagnostic_failed=' + type(exc).__name__, file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
