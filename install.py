#!/usr/bin/env python3
"""Install the Codex-only skill and its pinned runtime without copying user state."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

HERE = Path(__file__).resolve().parent
RUNTIME = ('pi.py', 'presets.py', 'setup_config.py', 'handoff.py', 'queue_control.py', 'worker.mjs', 'connection.mjs', 'opencode.mjs', 'agents.json',
           'package.json', 'package-lock.json')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target', type=Path, default=Path.home() / '.codex/skills/codex-pi-subagents')
    parser.add_argument('--skip-deps', action='store_true', help='Copy files only; run npm ci in runtime/ before starting workers')
    args = parser.parse_args()
    target = args.target.expanduser().absolute()
    if os.path.lexists(target):
        parser.error('Target already exists; preserve your configuration and choose a new --target or move the existing folder first')
    npm = shutil.which('npm')
    if not args.skip_deps and not npm:
        parser.error('npm is required; install Node.js 22+ first')
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.codex-pi-install-', dir=target.parent) as temporary:
        staged = Path(temporary) / 'skill'
        shutil.copytree(HERE / 'skill', staged, ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '.DS_Store'))
        runtime = staged / 'runtime'
        runtime.mkdir()
        for name in RUNTIME:
            shutil.copy2(HERE / name, runtime / name)
        if not args.skip_deps:
            subprocess.run([npm, 'ci', '--ignore-scripts', '--no-audit', '--no-fund'], cwd=runtime, check=True)
        if os.path.lexists(target):
            parser.error('Target appeared during installation; refusing to replace it')
        staged.rename(target)
    print(json.dumps({'installed': str(target), 'dependenciesInstalled': not args.skip_deps,
                      'entryPoint': str(target / 'scripts/pi.py'), 'setupRequired': True,
                      'nextStep': 'Run python3 ' + str(target / 'scripts/pi.py') + ' setup to choose your API and models'}, ensure_ascii=False))


if __name__ == '__main__':
    main()
