"""Synthetic state tests: no credentials, queues, real jobs or API calls."""
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest

from handoff import inbox, wait_for_results

JOB = 'pi_aaaaaaaaaaaaaaaa'
THREAD = 'source-chat'


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(value))
    tmp.replace(path)


class HandoffTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.store = Path(self.temporary.name)

    def run_fixture(self, status='completed', thread=THREAD, job=JOB, number=1):
        root = self.store / 'jobs' / job
        run = root / 'runs' / f'{number:04d}'
        write(root / 'job.json', {'currentRun': number})
        write(run / 'request.json', {'threadId': thread, 'jobId': job, 'number': number, 'runId': str(number)})
        if status != 'running':
            write(run / 'result.json', {'status': status, 'output': 'fixture result'})
        write(run / 'state.json', {'status': status})
        return run

    def test_completed_failed_and_cancelled_are_ready(self):
        for number, status in enumerate(['completed', 'failed', 'cancelled', 'timed_out', 'interrupted'], 1):
            self.run_fixture(status=status, number=number)
        ready = inbox(self.store, THREAD)['ready']
        self.assertEqual(len(ready), 5)
        self.assertEqual([r['number'] for r in ready], [1, 2, 3, 4, 5])

    def test_wait_returns_on_completion_without_queue(self):
        run = self.run_fixture('running')
        def finish():
            time.sleep(.1)
            write(run / 'result.json', {'status': 'completed', 'output': 'DIRECT_HANDOFF'})
            write(run / 'state.json', {'status': 'completed'})
        thread = threading.Thread(target=finish)
        thread.start()
        try:
            result = wait_for_results(self.store, THREAD, [JOB], timeout=2)
            self.assertEqual(result['status'], 'ready')
            self.assertEqual(result['ready'][0]['outputPreview'], 'DIRECT_HANDOFF')
        finally:
            thread.join()

    def test_timeout_does_not_cancel(self):
        run = self.run_fixture('running')
        write(run / 'progress.json', {'type': 'model_request'})
        result = wait_for_results(self.store, THREAD, timeout=.05)
        self.assertEqual(result['status'], 'waiting')
        self.assertEqual(result['active'][0]['progress'], 'model_request')
        self.assertFalse((run / 'cancel.request').exists())

    def test_acceptance_suppresses_both_verdicts(self):
        for number, verdict in enumerate(['accepted', 'rejected'], 1):
            run = self.run_fixture(number=number)
            write(run / 'acceptance.json', {'verdict': verdict})
        self.assertEqual(inbox(self.store, THREAD)['status'], 'idle')

    def test_foreign_and_unknown_jobs(self):
        self.run_fixture(thread='other-chat')
        self.assertEqual(inbox(self.store, THREAD)['ready'], [])
        for jobs in [[JOB], ['pi_bbbbbbbbbbbbbbbb'], ['../escape'], [JOB + '\n']]:
            with self.subTest(jobs=jobs), self.assertRaises(ValueError):
                wait_for_results(self.store, THREAD, jobs, timeout=0)

    def test_invalid_deadline(self):
        for timeout in [-1, 61, float('inf'), float('nan'), 'oops']:
            with self.subTest(timeout=timeout), self.assertRaises(ValueError):
                wait_for_results(self.store, THREAD, timeout=timeout)

    def test_old_unaccepted_run_is_not_lost(self):
        self.run_fixture(number=1)
        self.run_fixture('running', number=2)
        result = inbox(self.store, THREAD)
        self.assertEqual(result['ready'][0]['number'], 1)
        self.assertEqual(result['active'][0]['number'], 2)

    def test_terminal_missing_result_is_surfaced(self):
        run = self.run_fixture()
        (run / 'result.json').unlink()
        result = wait_for_results(self.store, THREAD, timeout=0)
        self.assertEqual(result['status'], 'ready')
        self.assertIn('Missing result', result['ready'][0]['error'])

    def test_corrupt_state_is_not_silently_ignored(self):
        run = self.run_fixture()
        (run / 'state.json').write_text('{broken')
        with self.assertRaisesRegex(ValueError, 'Corrupted'):
            inbox(self.store, THREAD)


if __name__ == '__main__':
    unittest.main()
