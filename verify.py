"""Integration checks in disposable fixtures. Does not submit real Codex messages."""
import datetime
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import uuid

HERE = Path(__file__).resolve().parent
ROOT = HERE
REPORT = ROOT / 'outputs/codex-pi-validation.json'
REPORT.parent.mkdir(parents=True, exist_ok=True)
if '--lifecycle' in sys.argv:
    report = json.loads(REPORT.read_text())
    TEST = Path(report['testDirectory'])
    STORE = Path(report['stateDirectory'])
    report.setdefault('earlierErrors', []).append(report.pop('error', '')[:1500])
    report['status'] = 'running'
else:
    TEST = ROOT / 'work' / ('codex-pi-validation-' + uuid.uuid4().hex[:8])
    STORE = TEST / 'state'
    TEST.mkdir(parents=True)
    report = {'startedAt': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'testDirectory': str(TEST),
              'stateDirectory': str(STORE), 'checks': {}, 'jobs': [], 'scope': 'Real Muse integration plus local notification-state tests; real queue callback is a separate final check.'}


def save():
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2))


def cli(*args, allow_error=False, env=None):
    result = subprocess.run([sys.executable, str(HERE / 'pi.py'), '--state-dir', str(STORE), *map(str, args)],
                            capture_output=True, text=True, timeout=45, env=env)
    data = json.loads(result.stdout)
    if result.returncode and not allow_error:
        raise RuntimeError(data)
    return data


def fixture(name):
    directory = TEST / name
    if directory.exists():
        directory = TEST / (name + '-' + uuid.uuid4().hex[:8])
    directory.mkdir()
    return directory


def start(cwd, prompt, *extra):
    state = cli('start', '--cwd', cwd, '--prompt', prompt, '--no-notify', '--timeout', 100, '--max-requests', 12, *extra)
    report['jobs'].append(state['jobId'])
    save()
    return state['jobId']


def wait(job, condition, timeout=110):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        state = cli('status', job)
        if condition(state):
            return state
        if state['status'] in {'failed', 'timed_out', 'interrupted'}:
            raise RuntimeError({'job': job, 'state': state, 'result': cli('result', job)})
        time.sleep(0.25)
    raise RuntimeError('Validation wait timed out: ' + job)


def done(job):
    return wait(job, lambda s: s['status'] in {'completed', 'cancelled'}, 110)


def checked(name, details):
    report['checks'][name] = {'status': 'passed', **details}
    save()
    print(json.dumps({'check': name, 'status': 'passed'}), flush=True)


def load(path):
    return json.loads(Path(path).read_text())


try:
    if '--lifecycle' not in sys.argv:
        cwd = fixture('normal')
        (cwd / 'AGENTS.md').write_text('Modify only calc.py and result.txt. Use Python for verification. Final responses must contain AGENTS_OK.\n')
        (cwd / 'calc.py').write_text('def total(values):\n    return sum(values) + 1\n')
        (cwd / 'check_calc.py').write_text('from calc import total\nassert total([7, 13, 22]) == 42\nprint("CHECK_OK")\n')
        marker = uuid.uuid4().hex
        prompt = (f'Remember this marker for a later turn: {marker}. Read AGENTS.md, calc.py and check_calc.py. '
                  'Before any edit, run exactly the shell command sleep 12 using bash and wait for it to finish. '
                  'Then fix calc.py, run python3 check_calc.py, and write result.txt containing initial. Report the checks.')
        job = start(cwd, prompt)
        wait(job, lambda s: s.get('progress', {}).get('type') == 'tool_execution_start' and s['progress'].get('tool') == 'bash')
        steer = cli('send', job, '--text', 'Change the required contents of result.txt to steered instead of initial. Keep the code fix and Python check.')
        follow = cli('send', job, '--mode', 'followUp', '--text', 'After completing the main task, append a new line FOLLOWUP_OK to result.txt.')
        assert steer['disposition'] == follow['disposition'] == 'queued'
        state = done(job)
        result = cli('result', job)
        assert state['status'] == 'completed', result
        subprocess.run([sys.executable, 'check_calc.py'], cwd=cwd, check=True, capture_output=True)
        assert 'steered' in (cwd / 'result.txt').read_text() and 'FOLLOWUP_OK' in (cwd / 'result.txt').read_text()
        assert 'AGENTS_OK' in result['output'] and str(cwd / 'AGENTS.md') in result['projectInstructions']
        checked('real_project_tools_steer_followup_and_agents', {'jobId': job, 'result': str(cwd / 'result.txt')})
        first_session = result['sessionId']
        cli('resume', job, '--prompt', 'Do not use any tools. Recall the marker from the earlier task and include it in your response.', '--no-notify')
        done(job)
        resumed = cli('result', job)
        assert resumed['sessionId'] == first_session and resumed['restoredMessages'] > 0 and marker in resumed['output']
        events = [json.loads(line) for line in (Path(cli('status', job)['runDirectory']) / 'events.jsonl').read_text().splitlines()]
        assert not any(e['type'] == 'tool_execution_start' for e in events)
        checked('disk_resume_in_new_process', {'jobId': job, 'sessionId': first_session})

    cwd = fixture('cancel')
    job = start(cwd, 'First use bash to run exactly: echo $$ > shell.pid; sleep 60 . Wait for the command before doing anything else. Do not edit other files.')
    wait(job, lambda s: (cwd / 'shell.pid').exists())
    blocked = cli('start', '--cwd', cwd, '--prompt', 'Do nothing', '--no-notify', '--max-workers', 2, allow_error=True)
    assert 'already has an active' in blocked.get('error', '')
    checked('shared_write_directory_guard', {'jobId': job})
    other_cwd = fixture('parallel')
    other = start(other_cwd, 'Reply with exactly PARALLEL_OK. Do not use tools.', '--tools', 'read', '--max-workers', 2)
    cli('cancel', job)
    assert done(job)['status'] == 'cancelled'
    assert cli('result', job)['status'] == 'cancelled'
    shell_pid = (cwd / 'shell.pid').read_text().strip()
    status = subprocess.run(['ps', '-p', shell_pid, '-o', 'stat='], capture_output=True, text=True).stdout.strip()
    assert not status or status.startswith('Z'), 'Cancelled shell remains alive'
    checked('real_tool_cancellation', {'jobId': job, 'shellTerminated': True})
    done(other)
    assert cli('result', other)['output'].strip() == 'PARALLEL_OK'
    checked('parallel_jobs_in_distinct_directories', {'jobs': [job, other]})

    cwd = fixture('timeout')
    job = start(cwd, 'Reply OK.', '--timeout', 0.05)
    end = time.monotonic() + 15
    while time.monotonic() < end:
        state = cli('status', job)
        if state['status'] == 'timed_out':
            break
        time.sleep(0.1)
    assert state['status'] == 'timed_out'
    assert cli('result', job)['status'] == 'timed_out'
    checked('supervisor_deadline', {'jobId': job, 'scope': 'Deadline during worker bootstrap'})

    cwd = fixture('crash')
    job = start(cwd, 'Reply OK.')
    state = wait(job, lambda s: bool(s.get('workerPid')))
    os.kill(state['workerPid'], signal.SIGKILL)
    end = time.monotonic() + 15
    while time.monotonic() < end:
        state = cli('status', job)
        if state['status'] == 'failed':
            break
        time.sleep(0.1)
    assert state['status'] == 'failed'
    checked('worker_process_failure', {'jobId': job})

    cwd = fixture('recover')
    job = start(cwd, 'First run bash command sleep 60 and wait. Then reply RECOVERY_OK.')
    state = wait(job, lambda s: (Path(s['runDirectory']) / 'session.json').exists() and s.get('progress', {}).get('tool') == 'bash')
    os.kill(state['supervisorPid'], signal.SIGKILL)
    time.sleep(0.1)
    recovered = cli('recover', job)
    assert recovered[0]['status'] == 'interrupted'
    assert (Path(state['runDirectory']) / 'session.json').exists()
    checked('lost_supervisor_recovery', {'jobId': job, 'workReplayed': False, 'sessionRetained': True})

    # Exercise queue de-duplication and uncertain-delivery handling without posting chat messages.
    run = Path(cli('status', other)['runDirectory'])
    request_path = run / 'request.json'
    request = load(request_path)
    request['notify'] = True
    request['threadId'] = os.environ.get('CODEX_THREAD_ID', '00000000-0000-0000-0000-000000000000')
    request_path.write_text(json.dumps(request))
    (run / 'notification.json').write_text(json.dumps({'status': 'pending'}))
    fake = TEST / 'fake-codex'
    fake.write_text('#!/usr/bin/env python3\nfrom pathlib import Path\np=Path(__file__).with_suffix(".count")\np.write_text(str(int(p.read_text())+1) if p.exists() else "1")\nprint("Queued message 00000000-0000-0000-0000-000000000001")\n')
    fake.chmod(0o700)
    env = {**os.environ, 'CODEX_PI_CODEX_CLI': str(fake)}
    assert cli('notify', other, env=env)['status'] == 'queued'
    assert cli('notify', other, env=env)['status'] == 'queued'
    assert fake.with_suffix('.count').read_text() == '1'
    cli('ack', other, '--verdict', 'accepted', '--note', 'Local notification-state test')
    assert cli('notify', other, env=env)['status'] == 'acknowledged'
    (run / 'notification.json').write_text(json.dumps({'status': 'submitting'}))
    assert cli('notify', other, env=env)['actionRequired']
    assert fake.with_suffix('.count').read_text() == '1'
    request['notify'] = False
    request_path.write_text(json.dumps(request))
    checked('notification_dedup_and_uncertain_delivery', {'scope': 'Local stub queue, not a real desktop wake'})
    report['status'] = 'passed'
except Exception as error:
    report['status'] = 'failed'
    report['error'] = str(error)[:4000]
    for job in report['jobs']:
        try:
            cli('cancel', job)
        except Exception:
            pass
    raise
finally:
    report['finishedAt'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    save()
