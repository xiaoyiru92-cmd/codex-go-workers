#!/usr/bin/env python3
"""Codex-only skill entry point. The underlying Pi bridge remains independent."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys

thread = os.environ.get('CODEX_THREAD_ID', '')
if not re.fullmatch(r'[0-9a-f-]{36}', thread):
    print(json.dumps({'error': 'Codex-only skill: no host CODEX_THREAD_ID. OpenCode/OMO/Pi must skip this skill and retain their original workflow. Do not fabricate a thread ID.'}))
    sys.exit(2)

try:
    listing = subprocess.run(['ps', '-axo', 'pid=,ppid=,comm='], capture_output=True, text=True, check=True)
    processes = {}
    for line in listing.stdout.splitlines():
        parts = line.strip().split(None, 2)
        if len(parts) == 3:
            processes[int(parts[0])] = (int(parts[1]), Path(parts[2]).name.lower())
    ancestor = os.getppid()
    visited = set()
    while ancestor in processes and ancestor not in visited:
        visited.add(ancestor)
        ancestor, name = processes[ancestor]
        if name in {'opencode', 'opencode-cli'}:
            raise ValueError('OpenCode ancestor detected; even inherited CODEX_THREAD_ID does not authorize this skill')
except (OSError, ValueError, subprocess.SubprocessError):
    print(json.dumps({'error': 'Codex-only skill: OpenCode caller detected or caller inspection unavailable. Skip this skill and keep the OpenCode/OMO workflow unchanged.'}))
    sys.exit(2)

runtime = Path(__file__).resolve().parents[1] / 'runtime' / 'pi.py'
if not runtime.is_file():
    print(json.dumps({'error': 'Installed skill runtime is missing; do not substitute another application or modify OpenCode.'}))
    sys.exit(2)
os.environ.setdefault('CODEX_PI_STATE', str(Path.home() / '.codex/pi-subagents'))
os.execv(sys.executable, [sys.executable, str(runtime), *sys.argv[1:]])
