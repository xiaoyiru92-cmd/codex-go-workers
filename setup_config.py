"""Interactive first-run setup for agent configuration. No network or model calls."""
import json
import os
import tempfile
from pathlib import Path

import presets

SECONDARY_AGENTS = {'explorer', 'quick'}


def _ask(input_fn, prompt):
    try:
        v = input_fn(prompt)
    except (KeyboardInterrupt, EOFError):
        raise RuntimeError('Setup cancelled; existing configuration left unchanged')
    if v is None:
        raise RuntimeError('Setup cancelled; existing configuration left unchanged')
    return str(v).strip()


def _require(input_fn, prompt, err):
    v = _ask(input_fn, prompt)
    if not v:
        raise ValueError(err)
    return v


def _positive_int(text, what):
    try:
        n = int(text)
    except ValueError:
        raise ValueError('%s must be a positive integer' % what)
    if type(n) is not int or n <= 0:
        raise ValueError('%s must be a positive integer' % what)
    return n


def configure(config_path, input_fn=input):
    path = Path(config_path).expanduser()
    try:
        raw = path.read_text()
    except FileNotFoundError:
        raise ValueError('Configuration template not found: %s' % path)
    try:
        base = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError('Existing configuration is not valid JSON: %s' % e)
    if not isinstance(base, dict):
        raise ValueError('Existing configuration must be a JSON object')
    needs_setup = base.get('setupRequired') is True

    try:
        choice = _require(input_fn, 'Choose provider [1 OpenAI-compatible / 2 OpenCode Go]: ', 'A choice of 1 or 2 is required')
        if choice not in ('1', '2'):
            raise ValueError('Choose 1 for OpenAI-compatible or 2 for OpenCode Go')
        if choice == '2':
            primary = _require(input_fn, 'Primary model ID (required): ', 'Primary model ID is required')
            secondary_in = _ask(input_fn, 'Secondary model ID for explorer/quick [blank reuses primary]: ')
            secondary = secondary_in or primary
            models = {
                'primary': {'provider': 'opencode-go', 'model': primary},
                'secondary': {'provider': 'opencode-go', 'model': secondary},
            }
        else:
            base_url = _require(input_fn, 'Custom endpoint base URL (required): ', 'Custom endpoint URL is required')
            primary = _require(input_fn, 'Primary model ID (required): ', 'Primary model ID is required')
            secondary_in = _ask(input_fn, 'Secondary model ID for explorer/quick [blank reuses primary]: ')
            secondary = secondary_in or primary
            cred = _require(input_fn, 'Credential source [1 env var name / 2 absolute secret file path / 3 no key, loopback only]: ', 'A credential source choice of 1, 2, or 3 is required')
            if cred not in ('1', '2', '3'):
                raise ValueError('Choose 1, 2, or 3 for the credential source')
            cred_fields = {}
            if cred == '1':
                env_name = _require(input_fn, 'Environment variable name holding the key (only the name, never the key itself): ', 'Environment variable name is required')
                cred_fields['apiKeyEnv'] = env_name
            elif cred == '2':
                fpath = _require(input_fn, 'Absolute path to existing secret file: ', 'Secret file path is required')
                if not fpath.startswith('/'):
                    raise ValueError('Secret file path must be absolute')
                if not os.path.exists(fpath):
                    raise ValueError('Secret file does not exist: %s' % fpath)
                cred_fields['apiKeyFile'] = fpath
            else:
                cred_fields['apiKeyNone'] = True
            cw_text = _ask(input_fn, 'Context window (user-set limit, not a discovered capability) [32768]: ')
            mt_text = _ask(input_fn, 'Output cap maxTokens (user-set limit, not a discovered capability) [4096]: ')
            cw = _positive_int(cw_text or '32768', 'contextWindow')
            mt = _positive_int(mt_text or '4096', 'maxTokens')
            models = {
                'primary': {'provider': 'openai-compatible', 'model': primary, 'baseUrl': base_url, 'api': 'openai-completions', 'contextWindow': cw, 'maxTokens': mt, **cred_fields},
                'secondary': {'provider': 'openai-compatible', 'model': secondary, 'baseUrl': base_url, 'api': 'openai-completions', 'contextWindow': cw, 'maxTokens': mt, **cred_fields},
            }

        new_cfg = dict(base)
        new_cfg['models'] = models
        agents = new_cfg.get('agents')
        if not isinstance(agents, dict) or not agents:
            raise ValueError('Template has no agents to map; refusing to overwrite')
        for aname, a in agents.items():
            if isinstance(a, dict):
                a['model'] = 'secondary' if aname in SECONDARY_AGENTS and 'secondary' in models else 'primary'
        new_cfg.pop('setupRequired', None)
        new_cfg['configured'] = True

        # Validate before saving (load from temp file to reuse load_config).
        with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False) as tf:
            json.dump(new_cfg, tf, indent=2)
            tmp = tf.name
        try:
            presets.load_config(tmp)
        finally:
            try:
                os.unlink(tmp)
            except OSError:
                pass

        # Backup on explicit reconfigure (existing configured file), not initial setupRequired file.
        if path.exists() and not needs_setup:
            with tempfile.NamedTemporaryFile('w', prefix=path.name + '.backup-', dir=path.parent, delete=False) as backup:
                backup.write(raw)
        # Atomic save with mode 0600.
        fd, tmpname = tempfile.mkstemp(dir=str(path.parent if path.parent.as_posix() else '.'), suffix='.tmp')
        try:
            with os.fdopen(fd, 'w') as f:
                json.dump(new_cfg, f, indent=2)
            os.chmod(tmpname, 0o600)
            os.replace(tmpname, path)
        except BaseException:
            try:
                os.unlink(tmpname)
            except OSError:
                pass
            raise
        return new_cfg
    except (KeyboardInterrupt, EOFError):
        raise RuntimeError('Setup cancelled; existing configuration left unchanged')
