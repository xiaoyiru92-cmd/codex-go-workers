"""Notification lifecycle and wire-protocol regressions; no live chat writes."""
import json
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch

import pi
import queue_control
from handoff import inbox


class NotificationChecks(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.store = Path(self.temporary.name)
        self.job = self.store / 'jobs/pi_0000000000000001'
        self.run = self.job / 'runs/0001'
        self.request = {'jobId': self.job.name, 'runId': 'run-one', 'number': 1,
            'threadId': 'thread-one', 'notify': True, 'store': str(self.store),
            'cwd': str(self.store / 'removed-workspace')}
        pi.write(self.job / 'job.json', {'currentRun': 1})
        pi.write(self.run / 'request.json', self.request)
        pi.write(self.run / 'state.json', {'status': 'completed'})
        pi.write(self.run / 'result.json', {'output': 'finished'})
        pi.write(self.run / 'notification.json', {'status': 'pending'})

    def ack(self, verdict='accepted'):
        return pi.acknowledge(self.run, verdict, 'checked', 'thread-one')

    def test_accepted_before_submission_never_queues_even_on_retry(self):
        for verdict in ('accepted', 'rejected'):
            with self.subTest(verdict=verdict), patch.object(pi.subprocess, 'run') as submit:
                self.ack(verdict)
                for retry in (False, True):
                    result = pi.notify(self.run, retry=retry)
                    self.assertEqual(result['retraction']['status'], 'not_submitted')
                submit.assert_not_called()
                self.assertEqual(inbox(self.store, 'thread-one')['ready'], [])

    def test_unaccepted_result_queues_once_and_stays_available(self):
        result = subprocess.CompletedProcess([], 0, 'Queued message 1111-2222\n', '')
        with patch.object(pi, 'codex_cli', return_value='codex'), patch.object(pi.subprocess, 'run', return_value=result) as submit:
            pi.notify(self.run)
            pi.notify(self.run)
            pi.notify(self.run, retry=True)
            submit.assert_called_once()
            self.assertEqual(submit.call_args.kwargs['cwd'], self.run)
        self.assertEqual(pi.read(self.run / 'notification.json')['status'], 'queued')
        self.assertEqual(len(inbox(self.store, 'thread-one')['ready']), 1)
        self.assertIsNone(pi.read(self.run / 'acceptance.json'))

    def test_acceptance_retracts_queued_or_uncertain_or_crashed_submission(self):
        for status in ('queued', 'uncertain', 'submitting', 'acknowledged'):
            with self.subTest(status=status):
                pi.write(self.run / 'notification.json', {'status': status})
                with patch('queue_control.retract', return_value={'status': 'removed', 'removedMessageIds': ['owned']}) as retract:
                    result = self.ack()
                    self.assertEqual(result['notification']['retraction']['status'], 'removed')
                    retract.assert_called_once()
                    pi.notify(self.run, retry=True)
                    self.ack()
                    retract.assert_called_once()

    def test_cleanup_failure_preserves_acceptance_and_can_be_retried(self):
        pi.write(self.run / 'notification.json', {'status': 'queued'})
        with patch('queue_control.retract', side_effect=TimeoutError('private server text')):
            result = self.ack()
        self.assertEqual(result['notification']['retraction']['status'], 'failed')
        self.assertNotIn('private server text', json.dumps(result))
        self.assertEqual(pi.read(self.run / 'acceptance.json')['verdict'], 'accepted')
        self.assertEqual(inbox(self.store, 'thread-one')['ready'], [])
        with patch('queue_control.retract', return_value={'status': 'not_pending', 'removedMessageIds': []}) as retract, patch.object(pi.subprocess, 'run') as submit:
            pi.notify(self.run, retry=True)
            retract.assert_called_once()
            submit.assert_not_called()

    def test_cross_thread_or_invalid_acceptance_never_deletes(self):
        with patch('queue_control.retract') as retract:
            with self.assertRaises(ValueError):
                pi.acknowledge(self.run, 'accepted', 'wrong thread', 'thread-two')
            for record in ({'verdict': 'unknown'}, {'verdict': 'accepted', 'threadId': 'thread-two'}):
                pi.write(self.run / 'acceptance.json', record)
                with self.assertRaises(ValueError):
                    pi.notify(self.run)
            retract.assert_not_called()

    def test_ack_waits_for_inflight_submission_then_removes_it(self):
        entered, release, ack_started, ack_finished = (threading.Event() for _ in range(4))
        failures = []
        def submit(*args, **kwargs):
            entered.set()
            if not release.wait(3):
                raise RuntimeError('test did not release submit')
            return subprocess.CompletedProcess([], 0, 'Queued message 1111-2222\n', '')
        def invoke(function):
            try:
                function()
            except BaseException as error:
                failures.append(error)
        def acknowledge():
            ack_started.set()
            self.ack()
            ack_finished.set()
        with patch.object(pi, 'codex_cli', return_value='codex'), patch.object(pi.subprocess, 'run', side_effect=submit), patch('queue_control.retract', return_value={'status': 'removed', 'removedMessageIds': ['1111-2222']}) as retract:
            sender = threading.Thread(target=invoke, args=(lambda: pi.notify(self.run),))
            receiver = threading.Thread(target=invoke, args=(acknowledge,))
            sender.start()
            try:
                self.assertTrue(entered.wait(3))
                receiver.start()
                self.assertTrue(ack_started.wait(3))
                self.assertFalse(ack_finished.wait(.05))
            finally:
                release.set()
                sender.join(4)
                if receiver.ident is not None:
                    receiver.join(4)
            self.assertFalse(sender.is_alive() or receiver.is_alive())
            self.assertEqual(failures, [])
            retract.assert_called_once()
            self.assertEqual(pi.read(self.run / 'notification.json')['retraction']['status'], 'removed')


class QueueOwnershipChecks(unittest.TestCase):
    def test_paginated_lookup_removes_only_exact_run_marker(self):
        owned = {'id': 'owned', 'input': [{'type': 'text', 'text': '[CODEX_PI_RESULT run-one] completed'}]}
        foreign = {'id': 'foreign', 'input': [{'type': 'text', 'text': '[CODEX_PI_RESULT run-two] completed'}]}
        quoted = {'id': 'quoted', 'input': [{'type': 'text', 'text': 'User quoted [CODEX_PI_RESULT run-one] completed'}]}
        with patch.object(queue_control, 'QueueClient') as factory:
            client = factory.return_value.__enter__.return_value
            client.call.side_effect = [
                {'data': [foreign, quoted], 'nextCursor': 'page-two'},
                {'data': [owned], 'nextCursor': None}, {'deleted': True}]
            result = queue_control.retract('codex', Path('/tmp'), {'threadId': 'thread-one', 'runId': 'run-one'})
            self.assertEqual(result['removedMessageIds'], ['owned'])
            client.call.assert_called_with('thread/queue/delete', {'threadId': 'thread-one', 'queuedSubmissionId': 'owned'})

    def test_already_consumed_does_not_claim_retraction(self):
        with patch.object(queue_control, 'QueueClient') as factory:
            client = factory.return_value.__enter__.return_value
            client.call.side_effect = [{'data': [{'id': 'owned', 'input': [{'type': 'text', 'text': '[CODEX_PI_RESULT run-one] done'}]}], 'nextCursor': None}, {'deleted': False}]
            result = queue_control.retract('codex', Path('/tmp'), {'threadId': 'thread-one', 'runId': 'run-one'})
            self.assertEqual(result, {'status': 'not_pending', 'removedMessageIds': []})


class QueueWireChecks(unittest.TestCase):
    def test_real_subprocess_initializes_filters_events_and_cleans_up(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            stub = root / 'codex'
            stub.write_text('''#!/usr/bin/env python3
import json,sys
assert sys.argv[1:]==['app-server','--stdio']
for line in sys.stdin:
 m=json.loads(line)
 if 'id' not in m: continue
 print(json.dumps({'method':'unrelated/notification','params':{}}),flush=True)
 result={'data':[], 'nextCursor':None} if m['method']=='thread/queue/list' else {}
 print(json.dumps({'id':m['id'],'result':result}),flush=True)
''')
            stub.chmod(0o700)
            with queue_control.QueueClient(str(stub), root) as client:
                result = client.call('thread/queue/list', {'threadId': 'fixture'})
                self.assertEqual(result['data'], [])
            self.assertIsNotNone(client.process.poll())

    def test_hung_or_closed_transport_is_bounded(self):
        for body, error in [('import time; time.sleep(10)', TimeoutError), ('pass', RuntimeError)]:
            with self.subTest(body=body), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                stub = root / 'codex'
                stub.write_text('#!/usr/bin/env python3\n' + body + '\n')
                stub.chmod(0o700)
                client = queue_control.QueueClient(str(stub), root, timeout=.2 if error is TimeoutError else 2)
                with self.assertRaises(error):
                    with client:
                        pass
                self.assertIsNotNone(client.process.poll())


if __name__ == '__main__':
    unittest.main()
