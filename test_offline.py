"""Offline packaging and preset checks. No accounts, model calls or chat messages."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from presets import load_config, resolve

HERE = Path(__file__).resolve().parent


class OfflineChecks(unittest.TestCase):
    def cli(self, *args):
        p = subprocess.run([sys.executable, str(HERE / 'pi.py'), *args], capture_output=True, text=True, check=True)
        return json.loads(p.stdout)

    def test_directory_excludes_prompts(self):
        compact, full = self.cli('agents'), self.cli('agents', '--full')
        self.assertEqual(compact.keys(), full.keys())
        self.assertTrue(all('prompt' not in a for a in compact.values()))
        self.assertTrue(all(a['prompt'] for a in full.values()))

    def test_readonly_role_cannot_add_shell(self):
        config = load_config(HERE / 'agents.json')
        with self.assertRaises(ValueError):
            resolve(config, 'explorer', tools='read,bash')

    def test_model_selection(self):
        config = load_config(HERE / 'agents.json')
        self.assertEqual(resolve(config, 'fixer')['model'], 'muse-spark-1.3-contributor')
        self.assertEqual(resolve(config, 'quick')['model'], 'deepseek-v4.1-flash')
        with self.assertRaises(ValueError):
            resolve(config, 'fixer', model_name='openai/gpt-6.1-sol')

    def test_install_is_self_contained_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / 'installed'
            command = [sys.executable, str(HERE / 'install.py'), '--target', str(target), '--skip-deps']
            subprocess.run(command, check=True, capture_output=True)
            for name in ['SKILL.md', 'scripts/pi.py', 'agents/openai.yaml', 'runtime/pi.py',
                         'runtime/presets.py', 'runtime/agents.json', 'runtime/package-lock.json']:
                self.assertTrue((target / name).is_file(), name)
            self.assertFalse((target / 'runtime/node_modules').exists())
            before = (target / 'runtime/agents.json').read_bytes()
            self.assertNotEqual(subprocess.run(command, capture_output=True).returncode, 0)
            self.assertEqual((target / 'runtime/agents.json').read_bytes(), before)

    def test_installed_skill_rejects_non_codex_caller(self):
        env = dict(os.environ)
        env.pop('CODEX_THREAD_ID', None)
        p = subprocess.run([sys.executable, str(HERE / 'skill/scripts/pi.py'), 'models'],
                           env=env, capture_output=True, text=True)
        self.assertEqual(p.returncode, 2)
        self.assertIn('Codex-only', p.stdout)


if __name__ == '__main__':
    unittest.main()
