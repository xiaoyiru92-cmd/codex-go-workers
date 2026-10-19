"""Bounded Codex queue cleanup through its app-server API, never its database.

Only pending messages bearing this run's exact completion marker are removed.
Already delivered messages are deliberately outside this module's scope.
"""
import json
import os
import selectors
import subprocess
import time


class QueueClient:
    def __init__(self, cli, cwd, timeout=10):
        self.cli, self.cwd, self.timeout = cli, cwd, timeout

    def __enter__(self):
        self.deadline = time.monotonic() + self.timeout
        self.buffer = b''
        self.sequence = 0
        self.process = subprocess.Popen([self.cli, 'app-server', '--stdio'], cwd=self.cwd,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        self.selector = selectors.DefaultSelector()
        self.selector.register(self.process.stdout, selectors.EVENT_READ)
        try:
            self.call('initialize', {'clientInfo': {'name': 'codex_pi_notifications',
                'title': 'Pi completion notifications', 'version': '0.1'},
                'capabilities': {'experimentalApi': True}})
            self._send({'method': 'initialized'})
        except BaseException:
            self.__exit__(None, None, None)
            raise
        return self

    def __exit__(self, *exc):
        self.selector.close()
        if self.process.poll() is None:
            self.process.terminate()
        try:
            self.process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait()
        self.process.stdin.close()
        self.process.stdout.close()

    def _send(self, message):
        self.process.stdin.write((json.dumps(message) + '\n').encode())
        self.process.stdin.flush()

    def call(self, method, params):
        self.sequence += 1
        self._send({'id': self.sequence, 'method': method, 'params': params})
        while True:
            while b'\n' in self.buffer:
                line, self.buffer = self.buffer.split(b'\n', 1)
                message = json.loads(line)
                if message.get('id') != self.sequence:
                    continue
                if 'error' in message:
                    # Do not persist arbitrary server text or other chat contents.
                    raise RuntimeError('Codex queue API rejected ' + method)
                return message['result']
            remaining = self.deadline - time.monotonic()
            if remaining <= 0 or not self.selector.select(remaining):
                raise TimeoutError('Codex queue API deadline exceeded')
            chunk = os.read(self.process.stdout.fileno(), 65536)
            if not chunk:
                raise RuntimeError('Codex queue API closed before replying')
            self.buffer += chunk
            if len(self.buffer) > 8 * 1024 * 1024:
                raise RuntimeError('Codex queue API response exceeds limit')


def retract(cli, run, request):
    """List before deleting: a saved message ID alone is not proof of ownership."""
    marker = '[CODEX_PI_RESULT ' + request['runId'] + '] '
    thread = request['threadId']
    matches, cursors = [], set()
    with QueueClient(cli, run) as client:
        params = {'threadId': thread, 'limit': 100}
        while True:
            page = client.call('thread/queue/list', params)
            for item in page['data']:
                inputs = item.get('input', [])
                if (len(inputs) == 1 and inputs[0].get('type') == 'text'
                        and inputs[0].get('text', '').startswith(marker)):
                    matches.append(item['id'])
            cursor = page.get('nextCursor')
            if cursor is None:
                break
            if cursor in cursors:
                raise RuntimeError('Codex queue API repeated its cursor')
            cursors.add(cursor)
            params['cursor'] = cursor
        removed = []
        for message_id in dict.fromkeys(matches):
            result = client.call('thread/queue/delete',
                {'threadId': thread, 'queuedSubmissionId': message_id})
            if result.get('deleted') is True:
                removed.append(message_id)
        return {'status': 'removed' if removed else 'not_pending',
                'removedMessageIds': removed}
