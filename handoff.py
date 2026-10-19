"""Read-only result handoff for a running Codex turn; no model calls or queue."""
import json
import math
from pathlib import Path
import re
import time

TERMINAL = {'completed', 'failed', 'cancelled', 'timed_out', 'interrupted'}
JOB_ID = re.compile(r'pi_[0-9a-f]{16}')


def _read(path):
    try:
        value = json.loads(path.read_text())
    except FileNotFoundError:
        return None
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise ValueError(f'Corrupted state file: {path}') from error
    if not isinstance(value, dict):
        raise ValueError(f'Expected a JSON object: {path}')
    return value


def _scan(store, thread_id, job_ids=None):
    if not isinstance(thread_id, str) or not thread_id:
        raise ValueError('A source thread ID is required')
    jobs = Path(store) / 'jobs'
    if job_ids is not None:
        for job in job_ids:
            if not isinstance(job, str) or not JOB_ID.fullmatch(job):
                raise ValueError('Invalid job ID')
            if not (jobs / job / 'job.json').is_file():
                raise ValueError('Unknown job: ' + job)
        candidates = [jobs / job for job in sorted(set(job_ids))]
    else:
        candidates = sorted(p for p in jobs.glob('pi_*') if JOB_ID.fullmatch(p.name) and (p / 'job.json').is_file())
    ready, active = [], []
    for job in candidates:
        belongs = False
        for run in sorted((job / 'runs').glob('[0-9]*')):
            if not run.is_dir():
                continue
            request = _read(run / 'request.json')
            if not request or request.get('threadId') != thread_id:
                continue
            belongs = True
            accepted = _read(run / 'acceptance.json')
            if accepted is not None:
                if accepted.get('verdict') not in {'accepted', 'rejected'}:
                    raise ValueError(f'Invalid acceptance record: {run}')
                continue
            state = _read(run / 'state.json') or {'status': 'starting'}
            item = {'jobId': job.name, 'number': request.get('number'), 'runId': request.get('runId'),
                    'status': state.get('status', 'starting'), 'runDirectory': str(run)}
            if item['status'] in TERMINAL:
                result = _read(run / 'result.json')
                # Terminal state is authoritative; a missing result is an issue
                # to surface, never a reason to silently report an empty inbox.
                result = result if result is not None else {'error': 'Missing result.json; inspect this run before acceptance'}
                item.update(resultFile=str(run / 'result.json'),
                            outputPreview=str(result.get('output') or '')[:1200],
                            error=str(result.get('error') or state.get('error') or '')[:500])
                ready.append(item)
            else:
                progress = _read(run / 'progress.json') or {}
                item['progress'] = progress.get('type')
                active.append(item)
        if job_ids is not None and not belongs:
            raise ValueError('Job belongs to another source thread: ' + job.name)
    return ready, active


def inbox(store, thread_id, job_ids=None):
    ready, active = _scan(store, thread_id, job_ids)
    return {'status': 'ready' if ready else ('waiting' if active else 'idle'), 'ready': ready, 'active': active}


def wait_for_results(store, thread_id, job_ids=None, timeout=30):
    if not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or not 0 <= timeout <= 60:
        raise ValueError('Timeout must be finite and between 0 and 60 seconds')
    deadline = time.monotonic() + timeout
    while True:
        # One snapshot per iteration: separate ready/active scans can miss a
        # transition between scans and incorrectly return idle on completion.
        snapshot = inbox(store, thread_id, job_ids)
        if snapshot['ready'] or not snapshot['active'] or time.monotonic() >= deadline:
            return snapshot
        time.sleep(min(.2, max(0, deadline - time.monotonic())))
