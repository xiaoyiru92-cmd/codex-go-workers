"""Real Pi SDK against a local simulated Chat Completions server; no paid API."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = Path(__file__).resolve().parent


@unittest.skipUnless((HERE / 'node_modules').exists() and shutil.which('node'), 'Install npm dependencies first')
class CompatibleIntegration(unittest.TestCase):
    def test_tools_resume_credentials_and_keyless(self):
        requests = []
        failures = []
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                requests.append((self.path, self.headers.get('Authorization'), body))
                has_tool = any(m['role'] == 'tool' for m in body['messages'])
                if has_tool:
                    delta = {'content': 'FIXTURE_COMPLETE'}
                    finish = 'stop'
                else:
                    delta = {'tool_calls': [{'index': 0, 'id': 'call_fixture', 'type': 'function',
                        'function': {'name': 'read', 'arguments': json.dumps({'path': 'notes.txt'})}}]}
                    finish = 'tool_calls'
                chunk = {'id': 'chatcmpl-fixture', 'object': 'chat.completion.chunk', 'created': 1,
                    'model': body['model'], 'choices': [{'index': 0, 'delta': {'role': 'assistant', **delta}, 'finish_reason': None}]}
                terminal = {**chunk, 'choices': [{'index': 0, 'delta': {}, 'finish_reason': finish}],
                    'usage': {'prompt_tokens': 20, 'completion_tokens': 5, 'total_tokens': 25}}
                payload = ('data: ' + json.dumps(chunk) + '\n\ndata: ' + json.dumps(terminal) + '\n\ndata: [DONE]\n\n').encode()
                self.send_response(200)
                self.send_header('Content-Type', 'text/event-stream')
                self.send_header('Content-Length', str(len(payload)))
                self.end_headers()
                try:
                    self.wfile.write(payload)
                except Exception as e:
                    failures.append(type(e).__name__)

        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            with tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                (root / 'notes.txt').write_text('READ_TOOL_MARKER')
                config = json.loads((HERE / 'agents.json').read_text())
                config.pop('setupRequired', None)
                model = {'provider': 'openai-compatible', 'model': 'org/fixture',
                    'baseUrl': f'http://127.0.0.1:{server.server_port}/v1', 'api': 'openai-completions',
                    'contextWindow': 32768, 'maxTokens': 1024, 'apiKeyEnv': 'PI_AUDIT_TEST_KEY'}
                config['models'] = {'primary': model}
                for agent in config['agents'].values():
                    agent['model'] = 'primary'
                config_path = root / 'config.json'
                config_path.write_text(json.dumps(config))
                env = {**os.environ, 'PI_AUDIT_TEST_KEY': 'synthetic-test-key-not-real'}
                env.pop('CODEX_THREAD_ID', None)  # Fixture uses explicit thread binding, no desktop messages.
                jobs = []
                def cli(*args):
                    p = subprocess.run([sys.executable, str(HERE / 'pi.py'), '--config', str(config_path),
                        '--state-dir', str(root / 'state'), *args], env=env, capture_output=True, text=True, timeout=25)
                    self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
                    return json.loads(p.stdout)
                def done(job):
                    snapshot = cli('wait', job, '--thread', 'fixture-chat', '--timeout', '20')
                    self.assertEqual(snapshot['status'], 'ready', snapshot)
                    state = cli('status', job)
                    result = cli('result', job)
                    self.assertEqual(state['status'], 'completed', result.get('error'))
                    self.assertEqual(result['output'], 'FIXTURE_COMPLETE')
                    cli('ack', job, '--run', str(state['number']), '--verdict', 'accepted', '--note', 'Local simulated API fixture checked')
                    self.assertEqual(cli('inbox', job, '--thread', 'fixture-chat')['ready'], [])
                    return result
                try:
                    job = cli('start', '--agent', 'explorer', '--cwd', str(root), '--prompt', 'Read notes.txt then answer.', '--no-notify', '--thread', 'fixture-chat', '--timeout', '20')['jobId']
                    jobs.append(job)
                    first = done(job)
                    self.assertEqual(first['provider'], 'openai-compatible')
                    self.assertFalse(first['costKnown'])
                    self.assertTrue(all(u['cost'] is None for u in first['usage']))
                    self.assertEqual(first['activeTools'], ['read', 'grep', 'find', 'ls'])
                    self.assertEqual(len(requests), 2)
                    self.assertTrue(all(p == '/v1/chat/completions' and a == 'Bearer synthetic-test-key-not-real' for p, a, _ in requests))
                    self.assertTrue(any('READ_TOOL_MARKER' in str(m) for m in requests[-1][2]['messages'] if m['role'] == 'tool'))
                    self.assertEqual(requests[0][2]['max_tokens'], 1024)
                    # Resume must use the snapshotted endpoint, not a changed live config.
                    config['models']['primary']['baseUrl'] = 'http://127.0.0.1:1/v1'
                    config_path.write_text(json.dumps(config))
                    cli('resume', job, '--prompt', 'Recall the earlier result without tools.', '--no-notify', '--thread', 'fixture-chat')
                    resumed = done(job)
                    self.assertEqual(resumed['sessionId'], first['sessionId'])
                    self.assertGreater(resumed['restoredMessages'], 0)
                    self.assertEqual(len(requests), 3)
                    # A saved run must remain resumable with no live config at all.
                    config_path.unlink()
                    cli('resume', job, '--prompt', 'Recall once more without tools.', '--no-notify', '--thread', 'fixture-chat')
                    without_config = done(job)
                    self.assertEqual(without_config['sessionId'], first['sessionId'])
                    self.assertEqual(len(requests), 4)
                    # Check all persisted state/transcripts for the synthetic secret.
                    for f in (root / 'state').rglob('*'):
                        if f.is_file():
                            self.assertNotIn(b'synthetic-test-key-not-real', f.read_bytes(), str(f))
                    config['models']['primary']['baseUrl'] = f'http://127.0.0.1:{server.server_port}/v1'
                    config['models']['primary'].pop('apiKeyEnv')
                    config['models']['primary']['apiKeyNone'] = True
                    config_path.write_text(json.dumps(config))
                    keyless = cli('start', '--agent', 'explorer', '--cwd', str(root), '--prompt', 'Read notes.txt.', '--no-notify', '--thread', 'fixture-chat', '--timeout', '20')['jobId']
                    jobs.append(keyless)
                    done(keyless)
                    self.assertTrue(all(auth is None for _, auth, _ in requests[4:]))
                    self.assertFalse(failures)
                finally:
                    for job in jobs:
                        cli('cancel', job)
        finally:
            server.shutdown()
            server.server_close()


if __name__ == '__main__':
    unittest.main()
