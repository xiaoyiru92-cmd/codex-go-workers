"""Resolve non-secret local agent/model presets into a per-run snapshot."""
import json
from pathlib import Path

TOOLS = {'read', 'write', 'edit', 'bash', 'grep', 'find', 'ls'}
THINKING = {'off', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max'}


def load_config(file):
    data = json.loads(Path(file).read_text())
    if data.get('schemaVersion') != 1:
        raise ValueError('Unsupported agent configuration version')
    if not isinstance(data.get('models'), dict) or not isinstance(data.get('agents'), dict):
        raise ValueError('Configuration needs models and agents objects')
    for name, model in data['models'].items():
        if model.get('provider') != 'opencode-go' or not isinstance(model.get('model'), str) or not model['model']:
            raise ValueError('Model entry must name an OpenCode Go model: ' + name)
    for name, agent in data['agents'].items():
        if agent.get('model') not in data['models']:
            raise ValueError('Unknown model alias for agent: ' + name)
        if not agent.get('tools') or not isinstance(agent['tools'], list) or not set(agent['tools']) <= TOOLS:
            raise ValueError('Invalid tool list for agent: ' + name)
        if not isinstance(agent.get('prompt', ''), str) or agent.get('thinking', 'off') not in THINKING:
            raise ValueError('Invalid prompt or thinking level for agent: ' + name)
    defaults = data.get('defaults', {})
    if defaults.get('agent') not in data['agents']:
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
    if model is None:
        # Keep the original --model MODEL_ID interface, restricted to Go.
        model_id = selection.removeprefix('opencode-go/')
        if '/' in model_id or not model_id:
            raise ValueError('Only configured aliases or OpenCode Go model IDs are supported')
        model = {'provider': 'opencode-go', 'model': model_id}
    selected_tools = tools.split(',') if tools is not None else list(agent['tools'])
    if not selected_tools or not set(selected_tools) <= set(agent['tools']):
        raise ValueError('Tool override must be a subset of the agent preset; edit the preset to expand its tools')
    return {'agent': name, 'agentPrompt': agent.get('prompt', ''), 'modelAlias': selection,
            'model': model['model'], 'provider': model['provider'], 'tools': selected_tools,
            'thinking': thinking or agent.get('thinking', 'off')}
