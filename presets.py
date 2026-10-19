"""Validate agent/model presets; enforce setup marker and credential hygiene."""
import json
import re
from pathlib import Path
from urllib.parse import urlsplit

TOOLS = {'read', 'write', 'edit', 'bash', 'grep', 'find', 'ls'}
THINKING = {'off', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max'}
ENV_RE = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')


def _is_loopback_host(host):
    if not host:
        return False
    return host.strip('[]').lower() in {'localhost', '127.0.0.1', '::1'}


def validate_model_entry(name, model):
    if not isinstance(model, dict):
        raise ValueError('Model entry must be an object: ' + str(name))
    if 'apiKey' in model:
        raise ValueError('Model %s must not contain an inline apiKey; use apiKeyEnv, apiKeyFile, or apiKeyNone' % name)
    provider = model.get('provider')
    if provider == 'opencode-go':
        if not isinstance(model.get('model'), str) or not model['model']:
            raise ValueError('Model entry must name an OpenCode Go model: ' + str(name))
        return
    if provider == 'openai-compatible':
        mid = model.get('model')
        if not isinstance(mid, str) or not mid:
            raise ValueError('Model %s needs a non-empty model id string' % name)
        base = model.get('baseUrl')
        if not isinstance(base, str) or not base:
            raise ValueError('Model %s needs a baseUrl string' % name)
        try:
            parts = urlsplit(base)
        except Exception:
            raise ValueError('Model %s has an invalid baseUrl' % name)
        if parts.scheme not in ('http', 'https'):
            raise ValueError('Model %s baseUrl must use http or https' % name)
        if not parts.hostname:
            raise ValueError('Model %s baseUrl needs a host' % name)
        if parts.username or parts.password:
            raise ValueError('Model %s baseUrl must not include userinfo' % name)
        if parts.query or parts.fragment:
            raise ValueError('Model %s baseUrl must not include query or fragment' % name)
        if parts.scheme == 'http' and not _is_loopback_host(parts.hostname):
            raise ValueError('Model %s uses plain http which is allowed only for loopback hosts' % name)
        if model.get('api') != 'openai-completions':
            raise ValueError('Model %s api must be "openai-completions" (only protocol this version)' % name)
        cw = model.get('contextWindow')
        mt = model.get('maxTokens')
        if type(cw) is not int or cw <= 0:
            raise ValueError('Model %s contextWindow must be a positive integer' % name)
        if type(mt) is not int or mt <= 0:
            raise ValueError('Model %s maxTokens must be a positive integer' % name)
        if mt > cw:
            raise ValueError('Model %s maxTokens must be <= contextWindow' % name)
        has_env = 'apiKeyEnv' in model
        has_file = 'apiKeyFile' in model
        has_none = 'apiKeyNone' in model
        if sum((bool(has_env), bool(has_file), bool(has_none))) != 1:
            raise ValueError('Model %s needs exactly one of apiKeyEnv, apiKeyFile, or apiKeyNone' % name)
        if has_env:
            v = model['apiKeyEnv']
            if not isinstance(v, str) or not ENV_RE.fullmatch(v):
                raise ValueError('Model %s apiKeyEnv must be a valid environment variable name' % name)
        if has_file:
            v = model['apiKeyFile']
            if not isinstance(v, str) or not v.startswith('/'):
                raise ValueError('Model %s apiKeyFile must be an absolute path' % name)
        if has_none:
            if model['apiKeyNone'] is not True:
                raise ValueError('Model %s apiKeyNone must be true' % name)
            if not _is_loopback_host(parts.hostname) or parts.scheme not in ('http', 'https'):
                raise ValueError('Model %s apiKeyNone is allowed only for loopback http/https endpoints' % name)
        return
    raise ValueError('Model %s has an unknown provider; expected opencode-go or openai-compatible' % name)


def load_config(file):
    data = json.loads(Path(file).read_text())
    if data.get('schemaVersion') != 1:
        raise ValueError('Unsupported agent configuration version')
    if data.get('setupRequired') is True:
        raise ValueError('Configuration is not set up yet: run setup with python3 pi.py setup to choose a provider and models')
    if not isinstance(data.get('models'), dict) or not data['models'] or not isinstance(data.get('agents'), dict) or not data['agents']:
        raise ValueError('Configuration needs models and agents objects')
    for name, model in data['models'].items():
        validate_model_entry(name, model)
    for name, agent in data['agents'].items():
        if not isinstance(agent, dict):
            raise ValueError('Invalid agent entry: ' + str(name))
        if agent.get('model') not in data['models']:
            raise ValueError('Unknown model alias for agent: ' + str(name))
        if not agent.get('tools') or not isinstance(agent['tools'], list) or not set(agent['tools']) <= TOOLS:
            raise ValueError('Invalid tool list for agent: ' + str(name))
        if not isinstance(agent.get('prompt', ''), str) or agent.get('thinking', 'off') not in THINKING:
            raise ValueError('Invalid prompt or thinking level for agent: ' + str(name))
        desc = agent.get('description', '')
        if not isinstance(desc, str):
            raise ValueError('Invalid description for agent: ' + str(name))
    defaults = data.get('defaults', {})
    if not isinstance(defaults, dict) or defaults.get('agent') not in data['agents']:
        raise ValueError('Unknown default agent')
    if type(defaults.get('maxWorkers')) is not int or defaults['maxWorkers'] < 1:
        raise ValueError('maxWorkers must be a positive integer')
    return data


def resolve(config, agent_name=None, model_name=None, tools=None, thinking=None):
    name = agent_name or config['defaults']['agent']
    if name not in config['agents']:
        raise ValueError('Unknown agent preset: ' + name)
    agent = config['agents'][name]
    selection = model_name or agent['model']
    model = config['models'].get(selection)
    base_entry = None
    if model is None:
        # Raw --model override.
        role_alias = agent['model']
        base_entry = config['models'].get(role_alias)
        if base_entry is None:
            raise ValueError('Unknown model alias for agent: ' + name)
        if base_entry.get('provider') == 'openai-compatible':
            # Compatible override: slash model IDs permitted; derive endpoint/creds from role model.
            if not isinstance(selection, str) or not selection:
                raise ValueError('Only configured aliases or model IDs are supported')
            model = dict(base_entry)
            model['model'] = selection.removeprefix('openai-compatible/')
            if not model['model']:
                raise ValueError('Only configured aliases or model IDs are supported')
        else:
            model_id = selection.removeprefix('opencode-go/')
            if '/' in model_id or not model_id:
                raise ValueError('Only configured aliases or OpenCode Go model IDs are supported')
            model = {'provider': 'opencode-go', 'model': model_id}
    out = {'agent': name, 'agentPrompt': agent.get('prompt', ''), 'modelAlias': selection,
           'model': model['model'], 'provider': model['provider'], 'tools': None,
           'thinking': thinking or agent.get('thinking', 'off')}
    selected_tools = tools.split(',') if tools is not None else list(agent['tools'])
    if not selected_tools or not set(selected_tools) <= set(agent['tools']):
        raise ValueError('Tool override must be a subset of the agent preset; edit the preset to expand its tools')
    out['tools'] = selected_tools
    if model.get('provider') == 'openai-compatible':
        out['modelConfig'] = {k: model[k] for k in ('provider', 'model', 'baseUrl', 'api', 'contextWindow', 'maxTokens') if k in model}
        if 'apiKeyEnv' in model:
            out['modelConfig']['apiKeyEnv'] = model['apiKeyEnv']
        if 'apiKeyFile' in model:
            out['modelConfig']['apiKeyFile'] = model['apiKeyFile']
        if 'apiKeyNone' in model:
            out['modelConfig']['apiKeyNone'] = model['apiKeyNone']
    return out
