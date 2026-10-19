"""Tests for first-run setup and validation. No model execution, no network."""
import json
import os
import tempfile
import shutil
import unittest
from pathlib import Path

import presets
import setup_config


def make_template(**over):
    cfg = {'schemaVersion': 1, 'defaults': {'agent': 'fixer', 'maxWorkers': 2},
           'models': {'primary': {'provider': 'opencode-go', 'model': 'x'}},
           'agents': {'fixer': {'model': 'primary', 'tools': ['read'], 'prompt': 'p'},
                      'explorer': {'model': 'primary', 'tools': ['read'], 'prompt': 'p'},
                      'quick': {'model': 'primary', 'tools': ['read'], 'prompt': 'p'}}}
    cfg.update(over)
    return cfg


TEMP_DIRS = []


def write_cfg(cfg):
    d = tempfile.mkdtemp()
    TEMP_DIRS.append(d)
    p = Path(d) / 'agents.json'
    p.write_text(json.dumps(cfg))
    return p


def fake_input(answers):
    it = iter(answers)
    return lambda prompt='': next(it)


class SetupTests(unittest.TestCase):
    def tearDown(self):
        while TEMP_DIRS:
            shutil.rmtree(TEMP_DIRS.pop())

    def test_reconfigure_backup_and_invalid_input(self):
        p = write_cfg(make_template())
        original = p.read_bytes()
        with self.assertRaises(ValueError):
            setup_config.configure(p, fake_input(['2', '']))
        self.assertEqual(p.read_bytes(), original)
        setup_config.configure(p, fake_input(['2', 'chosen-model', '']))
        backups = list(p.parent.glob('agents.json.backup-*'))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), original)
        self.assertEqual(backups[0].stat().st_mode & 0o777, 0o600)

    def test_go_both_models(self):
        p = write_cfg(make_template(setupRequired=True))
        out = setup_config.configure(str(p), fake_input(['2', 'main-id', 'ro-id']))
        data = json.loads(p.read_text())
        self.assertNotIn('setupRequired', data)
        self.assertTrue(data['configured'])
        self.assertEqual(data['models']['primary']['model'], 'main-id')
        self.assertEqual(data['models']['secondary']['model'], 'ro-id')
        self.assertEqual(data['agents']['explorer']['model'], 'secondary')
        self.assertEqual(data['agents']['quick']['model'], 'secondary')
        self.assertEqual(data['agents']['fixer']['model'], 'primary')
        self.assertEqual(oct(os.stat(p).st_mode & 0o777), '0o600')

    def test_custom_env_blank_secondary(self):
        p = write_cfg(make_template(setupRequired=True))
        out = setup_config.configure(str(p), fake_input(['1', 'https://api.example.com/v1', 'm1', '', '1', 'MY_KEY', '', '']))
        data = json.loads(p.read_text())
        self.assertEqual(data['models']['primary']['apiKeyEnv'], 'MY_KEY')
        self.assertEqual(data['models']['secondary']['model'], 'm1')
        self.assertEqual(data['models']['primary']['contextWindow'], 32768)
        self.assertEqual(data['models']['primary']['maxTokens'], 4096)
        r = presets.load_config(str(p))
        snap = presets.resolve(r, agent_name='fixer')
        self.assertIn('modelConfig', snap)
        self.assertEqual(snap['modelConfig']['apiKeyEnv'], 'MY_KEY')
        self.assertEqual(snap['provider'], 'openai-compatible')

    def test_cancel_preserves(self):
        p = write_cfg(make_template(setupRequired=True))
        before = p.read_bytes()

        def boom(prompt=''):
            raise KeyboardInterrupt
        with self.assertRaises(RuntimeError):
            setup_config.configure(str(p), boom)
        self.assertEqual(p.read_bytes(), before)

    def test_invalid_url_and_cred_injection(self):
        with self.assertRaises(ValueError):
            presets.load_config(str(write_cfg(make_template(models={'primary': {'provider': 'openai-compatible', 'model': 'm', 'baseUrl': 'https://user@h/v?q=1#f', 'api': 'openai-completions', 'contextWindow': 100, 'maxTokens': 10, 'apiKeyEnv': 'K'}}))))
        with self.assertRaises(ValueError):
            presets.load_config(str(write_cfg(make_template(models={'primary': {'provider': 'openai-compatible', 'model': 'm', 'baseUrl': 'https://h/v', 'api': 'openai-completions', 'contextWindow': 100, 'maxTokens': 10, 'apiKey': 'secret', 'apiKeyEnv': 'K'}}))))
        with self.assertRaises(ValueError):
            presets.load_config(str(write_cfg(make_template(models={'primary': {'provider': 'openai-compatible', 'model': 'm', 'baseUrl': 'http://example.com/v', 'api': 'openai-completions', 'contextWindow': 100, 'maxTokens': 10, 'apiKeyEnv': 'K'}}))))
        # setupRequired marker raises actionable error
        with self.assertRaisesRegex(ValueError, 'run setup'):
            presets.load_config(str(write_cfg(make_template(setupRequired=True))))
        # backwards compat: existing installation without marker loads
        cfg = make_template()
        presets.load_config(str(write_cfg(cfg)))

    def test_full_snapshot_roles(self):
        p = write_cfg(make_template(setupRequired=True))
        setup_config.configure(str(p), fake_input(['2', 'm', '']))
        r = presets.load_config(str(p))
        for agent in r['agents']:
            s = presets.resolve(r, agent_name=agent)
            self.assertIn('model', s)
            self.assertIn('provider', s)
        # compatible raw override derives endpoint/creds, allows slashes
        p2 = write_cfg(make_template(setupRequired=True))
        setup_config.configure(str(p2), fake_input(['1', 'http://127.0.0.1:8080/v1', 'm1', '', '3', '', '']))
        r2 = presets.load_config(str(p2))
        s2 = presets.resolve(r2, agent_name='fixer', model_name='org/m2')
        self.assertEqual(s2['model'], 'org/m2')
        self.assertEqual(s2['modelConfig']['baseUrl'], 'http://127.0.0.1:8080/v1')
        self.assertTrue(s2['modelConfig']['apiKeyNone'])


if __name__ == '__main__':
    unittest.main()
