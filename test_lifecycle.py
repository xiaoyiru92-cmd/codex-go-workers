"""Deterministic lifecycle regressions; fake workers, no accounts or model calls."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

import pi

HERE = Path(__file__).resolve().parent


class LifecycleChecks(unittest.TestCase):
    def test_resume_uses_snapshot_when_live_config_is_unavailable(self):
        for current_config in [None, '{broken', '{"setupRequired": true}']:
            with self.subTest(current_config=current_config), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                store = root / 'state'
                job = store / 'jobs/pi_0000000000000001'
                run = job / 'runs/0001'
                session = root / 'saved.jsonl'
                session.write_text('{}\n')
                config = root / 'config.json'
                if current_config is not None:
                    config.write_text(current_config)
                pi.write(job / 'job.json', {'currentRun': 1})
                pi.write(run / 'state.json', {'status': 'completed', 'sessionFile': str(session)})
                pi.write(run / 'request.json', {'jobId': job.name, 'number': 1, 'cwd': str(root),
                    'tools': ['read'], 'notify': False, 'timeoutSeconds': 10, 'maxRequests': 2,
                    'maxOutputTokens': 100, 'model': 'saved-model', 'provider': 'opencode-go',
                    'agent': 'explorer', 'workerLimit': 3})
                args = pi.parser().parse_args(['--config', str(config), 'resume', job.name,
                    '--prompt', 'continue', '--no-notify'])
                with patch.object(pi.subprocess, 'Popen') as process:
                    process.return_value.pid = 12345678
                    result = pi.launch(store, args, resume=True)
                saved = pi.read(job / 'runs/0002/request.json')
                self.assertEqual(result['number'], 2)
                self.assertEqual(saved['sessionFile'], str(session))
                self.assertEqual(saved['model'], 'saved-model')
                self.assertEqual(saved['workerLimit'], 3)
                self.assertEqual(saved['tools'], ['read'])

    def test_explicit_zero_run_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            job = Path(temporary)
            pi.write(job / 'job.json', {'currentRun': 1})
            pi.write(job / 'runs/0001/request.json', {})
            with self.assertRaisesRegex(ValueError, 'Invalid run'):
                pi.run_path(job, 0)

    def test_nonfinite_deadline_is_rejected_before_launch(self):
        for value in ['nan', 'inf', '-inf']:
            with self.subTest(value=value), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                args = pi.parser().parse_args(['--config', str(HERE / 'examples/opencode-go.json'), 'start',
                    '--cwd', str(root), '--prompt', 'fixture', '--no-notify', '--timeout=' + value])
                with patch.object(pi.subprocess, 'Popen') as launch:
                    launch.return_value.pid = 12345678
                    with self.assertRaisesRegex(ValueError, 'finite'):
                        pi.launch(root / 'state', args)
                    launch.assert_not_called()
                self.assertFalse(list((root / 'state/jobs').glob('pi_*')))

    @unittest.skipUnless(shutil.which('node'), 'Node is required')
    def test_worker_exit_does_not_wait_for_descendant_pipe(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run = root / 'run'
            run.mkdir()
            # A background child holds stdout open after its worker exits.
            (root / 'worker.mjs').write_text("import fs from 'node:fs'; import {spawn} from 'node:child_process';\n"
                "const c=spawn(process.execPath,['-e','setTimeout(()=>{},10000)'],{stdio:'inherit'});\n"
                "fs.writeFileSync('descendant.pid',String(c.pid));process.exit(0);\n")
            pi.write(run / 'request.json', {'store': str(root), 'cwd': str(root), 'timeoutSeconds': .2,
                'jobId': 'fixture', 'runId': 'fixture', 'notify': False})
            pi.write(run / 'state.json', {'status': 'starting'})
            code = ('import sys; from pathlib import Path; sys.path.insert(0,sys.argv[1]); '
                    'import pi; pi.HERE=Path(sys.argv[2]); pi.supervise(Path(sys.argv[3]))')
            process = subprocess.Popen([sys.executable, '-c', code, str(HERE), str(root), str(run)],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                process.communicate(timeout=2)
                self.assertEqual(process.returncode, 0)
                self.assertEqual(pi.read(run / 'state.json')['status'], 'failed')
                self.assertIn('without a result', pi.read(run / 'result.json')['error'])
            finally:
                if process.poll() is None:
                    process.kill()
                    process.communicate()
                pid_file = root / 'descendant.pid'
                if pid_file.exists():
                    try:
                        os.kill(int(pid_file.read_text()), 9)
                    except ProcessLookupError:
                        pass

    @unittest.skipUnless(shutil.which('node'), 'Node is required')
    def test_event_write_failure_preserves_result(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run = root / 'run'
            run.mkdir()
            shutil.copy2(HERE / 'worker.mjs', root / 'worker.mjs')
            (root / 'connection.mjs').write_text("export async function readConfiguredConnection(){return {sensitive:[],source:{kind:'fixture'},baseUrl:'https://example.invalid',headers:{},access:'fixture'};}\n")
            package = root / 'node_modules/@earendil-works/pi-coding-agent'
            package.mkdir(parents=True)
            (package / 'package.json').write_text(json.dumps({'type': 'module', 'exports': './index.mjs'}))
            (package / 'index.mjs').write_text('''
export const ModelRuntime={create:async()=>({getModel:()=>({id:'fixture'}),registerProvider(){},async setRuntimeApiKey(){},streamSimple(){}})};
export const SettingsManager={inMemory:()=>({})};
export class DefaultResourceLoader { async reload(){} getAgentsFiles(){return {agentsFiles:[]};} }
export const SessionManager={create:()=>({})};
export async function createAgentSession(){
 const session={sessionId:'fixture',sessionFile:'fixture-session',messages:[],isStreaming:false,
 getActiveToolNames:()=>[],subscribe(fn){this.listener=fn;},dispose(){},
 async prompt(){this.listener({type:'agent_start'});await new Promise(r=>setTimeout(r,50));this.messages.push({role:'assistant',stopReason:'stop'});},
 getLastAssistantText:()=> 'FIXTURE_OUTPUT'};
 return {session};
}
''')
            # A deterministic EISDIR failure, even on machines running as root.
            (run / 'events.jsonl').mkdir()
            pi.write(run / 'request.json', {'runId': 'fixture', 'jobId': 'fixture', 'model': 'fixture',
                'cwd': str(root), 'jobDir': str(root), 'tools': [], 'prompt': 'fixture'})
            result = subprocess.run(['node', str(root / 'worker.mjs'), str(run)], capture_output=True,
                text=True, timeout=5)
            self.assertTrue((run / 'result.json').exists(), result.stderr)
            outcome = pi.read(run / 'result.json')
            self.assertEqual(outcome['status'], 'failed')
            self.assertIn('Event logging failed', outcome['error'])
            self.assertEqual(outcome['output'], 'FIXTURE_OUTPUT')
            self.assertEqual(outcome['sessionFile'], 'fixture-session')
            self.assertFalse(Path(pi.read(run / 'control.json')['socketPath']).exists())


if __name__ == '__main__':
    unittest.main()
