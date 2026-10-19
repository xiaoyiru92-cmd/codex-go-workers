"""Real Go model routing and concurrent preset/session checks; no chat messages."""
import datetime
import json
from pathlib import Path
import subprocess
import sys
import time
import uuid
from presets import load_config, resolve

HERE = Path(__file__).resolve().parent
ROOT = HERE
TEST = ROOT / 'work' / ('codex-pi-presets-' + uuid.uuid4().hex[:8])
STORE = TEST / 'state'
TEST.mkdir(parents=True)
REPORT = ROOT / 'outputs/codex-pi-presets-validation.json'
REPORT.parent.mkdir(parents=True, exist_ok=True)
report = {'status': 'running', 'startedAt': datetime.datetime.now(datetime.timezone.utc).isoformat(),
          'testDirectory': str(TEST), 'stateDirectory': str(STORE), 'jobs': [], 'checks': {}}


def save():
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')


def cli(*args, config=None):
    command = [sys.executable, str(HERE / 'pi.py'), '--state-dir', str(STORE)]
    if config:
        command += ['--config', str(config)]
    response = subprocess.run(command + list(map(str, args)), capture_output=True, text=True, timeout=45)
    value = json.loads(response.stdout)
    if response.returncode:
        raise RuntimeError(value)
    return value


def check(name, **facts):
    report['checks'][name] = {'status': 'passed', **facts}
    save()
    print(json.dumps({'check': name, 'status': 'passed'}), flush=True)


def done(job, timeout=120):
    until = time.monotonic() + timeout
    while time.monotonic() < until:
        state = cli('status', job)
        if state['status'] not in {'starting', 'running', 'stopping'}:
            result = cli('result', job)
            assert state['status'] == result['status'] == 'completed', {'state': state, 'result': result}
            return state, result
        time.sleep(.5)
    raise RuntimeError('Timed out waiting for ' + job)


def transcript(result):
    return [e['message'] for s in Path(result['sessionFile']).read_text().splitlines()
            if isinstance((e := json.loads(s)).get('message'), dict)]


try:
    config = load_config(HERE / 'agents.json')
    assert resolve(config, 'explorer')['model'] == 'deepseek-v4.1-flash'
    assert resolve(config, model_name='muse-spark-1.3-contributor')['model'] == 'muse-spark-1.3-contributor'
    for agent, tools in [('explorer', 'bash'), ('reviewer', 'write')]:
        try:
            resolve(config, agent, tools=tools)
        except ValueError:
            pass
        else:
            raise AssertionError('Expanded tools escaped a preset')
    check('preset_resolution_and_tool_restrictions')
    muse = TEST / 'muse'; muse.mkdir()
    (muse / 'AGENTS.md').write_text('Change only calc.py. Include AGENTS_OK in your final answer.\n')
    (muse / 'calc.py').write_text('def total(values):\n    return sum(values) + 1\n')
    ds = TEST / 'deepseek'; ds.mkdir()
    marker = 'MEMORY_' + uuid.uuid4().hex
    (ds / 'notes.txt').write_text('The project marker is ' + marker + '.\nFunction location: src/engine.py:17\n')
    custom = TEST / 'agents.json'
    config['agents']['explorer']['prompt'] += ' End your final answer with PRESET_OK.'
    custom.write_text(json.dumps(config))
    first = cli('start', '--agent', 'fixer', '--cwd', muse, '--prompt',
                'First run bash sleep 15, then inspect AGENTS.md and calc.py. Fix total so total([7,13,22]) equals 42. Verify it with Python, without creating other files. Report the check result.',
                '--no-notify', '--timeout', 140)
    report['jobs'].append(first['jobId']); save()
    second = cli('start', '--agent', 'explorer', '--cwd', ds, '--prompt',
                 'Use a read or grep tool to inspect notes.txt. Remember the project marker for later, and report it together with the function location. Do not change files.',
                 '--no-notify', '--timeout', 140, config=custom)
    report['jobs'].append(second['jobId']); save()
    ms, mr = done(first['jobId']); ds_state, dr = done(second['jobId'])
    parse = datetime.datetime.fromisoformat
    assert max(parse(ms['startedAt']), parse(ds_state['startedAt'])) < min(parse(ms['finishedAt']), parse(ds_state['finishedAt']))
    check('real_default_concurrency', jobs=report['jobs'], defaultLimit=config['defaults']['maxWorkers'])
    assert mr['model'] == 'muse-spark-1.3-contributor' and mr['agent'] == 'fixer'
    assert 'AGENTS_OK' in mr['output'] and '42' in mr['output']
    verified = subprocess.run([sys.executable, '-c', 'from calc import total; assert total([7,13,22])==42'], cwd=muse)
    assert verified.returncode == 0
    check('real_muse_fixer', jobId=first['jobId'], model=mr['model'], tools=mr['activeTools'])
    assert dr['model'] == 'deepseek-v4.1-flash' and dr['agent'] == 'explorer'
    assert marker in dr['output'] and 'src/engine.py:17' in dr['output'] and 'PRESET_OK' in dr['output']
    assert set(dr['activeTools']) == {'read', 'grep', 'find', 'ls'}
    messages = transcript(dr)
    assert any(m.get('role') == 'toolResult' and m.get('toolName') in {'read', 'grep'} and not m.get('isError') for m in messages)
    assert all(m.get('provider') == 'opencode-go' for m in messages if m.get('role') == 'assistant')
    check('real_deepseek_explorer_and_custom_prompt', jobId=second['jobId'], model=dr['model'], tools=dr['activeTools'])
    # Config edits affect new tasks; this run must resume its original role/model snapshot.
    config['agents']['explorer']['model'] = 'muse'; custom.write_text(json.dumps(config))
    cli('resume', second['jobId'], '--prompt', 'Without calling any tools, recall the project marker you read earlier. Output the marker and the required role suffix.', '--no-notify', config=custom)
    resumed, rr = done(second['jobId'])
    assert rr['model'] == dr['model'] and rr['sessionId'] == dr['sessionId'] and rr['workerPid'] != dr['workerPid']
    assert marker in rr['output'] and 'PRESET_OK' in rr['output'] and rr['restoredMessages'] > 0
    events = [json.loads(s) for s in (Path(resumed['runDirectory']) / 'events.jsonl').read_text().splitlines()]
    assert not any(e['type'] == 'tool_execution_start' for e in events)
    check('real_deepseek_disk_resume_and_role_snapshot', sessionId=rr['sessionId'], restoredMessages=rr['restoredMessages'])
    report['status'] = 'passed'
except Exception as error:
    report.update(status='failed', error=str(error)[:3000])
    raise
finally:
    report['finishedAt'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    save()
