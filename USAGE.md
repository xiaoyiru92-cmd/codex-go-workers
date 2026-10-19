# Local Codex–Pi bridge

A small local bridge for Codex Desktop to delegate work to Pi. Codex remains the
orchestrator; Pi uses the API and model explicitly selected by the user (OpenAI-compatible Chat Completions or OpenCode Go). Each
job has one plain process supervisor and one Pi SDK worker. There is no resident
service and no extra model controller.

## Current setup

- macOS, Python 3, Node.js 22 or later.
- Only for Go: OpenCode v2 Desktop running locally, with an active OpenCode login and Go models.
- Run `python3 pi.py setup` before first use; new installations have no selected provider or model.
- Codex Desktop running and signed in, with a bundled CLI that supports `queue`.
- Install dependencies in this directory with `npm ci --ignore-scripts --no-audit --no-fund`.
- Pi SDK is pinned to `@earendil-works/pi-coding-agent@1.3.0`.

When Go is selected, the bridge discovers the local server owned by OpenCode Desktop, exports only the
OpenCode integration into process memory, selects its active OAuth login, and
reads the enabled model's endpoint and workspace header from that same server.
It does not use the legacy `auth.json` key or copy credentials to Pi storage.
For an unusual local setup, set `OPENCODE_V2_SERVER` and `OPENCODE_V2_CLI` explicitly.
An expired access token produces a clear failure; automatic OAuth refresh is not
implemented. OpenCode must renew the login.

## Commands

Invoke `python3 /absolute/path/to/codex-pi/pi.py`. These examples assume this
directory is the shell's working directory.

```bash
python3 pi.py start --cwd /absolute/project --prompt-file /absolute/task.txt
python3 pi.py setup
python3 pi.py agents
python3 pi.py inbox
python3 pi.py wait pi_JOB_ID --timeout 30
python3 pi.py models
python3 pi.py start --agent explorer --cwd /absolute/project --prompt-file /absolute/search.txt
python3 pi.py start --agent fixer --model deepseek --cwd /absolute/other/project --prompt-file /absolute/task.txt
python3 pi.py list
python3 pi.py status pi_JOB_ID
python3 pi.py send pi_JOB_ID --text 'Focus on the parser before touching the UI.'
python3 pi.py send pi_JOB_ID --mode followUp --text 'When done, check the documentation.'
python3 pi.py result pi_JOB_ID
python3 pi.py resume pi_JOB_ID --prompt 'Fix the remaining failing test.'
python3 pi.py cancel pi_JOB_ID
python3 pi.py recover
```

Use the actual `pi_` job ID printed by `start`. Notifications bind to the calling
chat's `CODEX_THREAD_ID`; outside Codex, supply `--thread UUID` or `--no-notify`.
The default agent is `fixer`. `agents.json` defines role prompts, tool sets,
model aliases, and the default concurrency limit. First-run setup asks for a
provider and model IDs; it does not silently pick Muse, DeepSeek or a paid API.
For a compatible endpoint, give its base URL (normally ending in `/v1`), a model
ID, context/output limits, and one of `apiKeyEnv`, `apiKeyFile`, or local-only
`apiKeyNone: true`. No key value belongs in this JSON. Use `setup` in a Terminal
or supply the chosen non-secret settings through Codex; non-interactive first
use returns `setupRequired` and creates no job. Existing Go configs remain valid.
An optional secondary model serves explorer/quick. More endpoint/model aliases
can be added to `models` and assigned individually in `agents`.
`--model` accepts a configured alias or raw model ID on the role's existing
provider. It never silently changes providers. Use global `--config /absolute/agents.json`
before the command for another configuration. The Go model IDs in
`examples/opencode-go.json` are explicit test examples, not defaults.

Presets retain their tool sets and instructions; model mappings are user-selected in the JSON file.
`agents` returns a compact Pi-only directory; `agents --full` includes role prompts.
Pi presets and GPT native Codex roles are independent configurations. This bridge
does not generate, import or synchronize native GPT role files. The parent selects
the execution channel and passes the task, without expanding Pi role templates.
Librarian is local document analysis; no web or browser tool is injected.
The resolved role, prompt, model and tools are saved in each run. Resume keeps
the original snapshot even if configuration changes. Start a new job to change
roles or models.

The default fixer tools are `read,write,edit,bash,grep,find,ls`; project `AGENTS.md` files are loaded.
Pi extensions, automatic skills and prompt-template discovery are disabled.
For an inspection task, use `--agent explorer`, or `--tools read,grep,find,ls`
to narrow another role's tools. Overrides cannot expand a preset's tools.
Pi supports SDK custom tools; this bridge currently enables the named built-in
tools only, without inheriting Codex's connectors or browser capabilities.
Tools run with the local account's permissions; this bridge is not an OS sandbox.
The working directory selects project context and relative paths, not a filesystem
security boundary.

Limits default to 600 seconds, 24 model requests and 2,048 output tokens per
request. Override these with `--timeout`, `--max-requests` and
`--max-output-tokens`. Pi retries a transient failed model request once, within
the same deadline and request limit. It does not restart the whole task.

The default worker limit is twenty, configurable through `defaults.maxWorkers`
or per invocation with `--max-workers`. Simultaneous jobs with the same write-capable working directory are
rejected. Use separate working directories/worktrees for concurrent edits. The
guard does not detect every possible overlap through absolute paths, symlinks or
nested projects. Jobs that exceed the limit are rejected, not held in a scheduler.

`steer` is delivered at Pi's next assistant/tool boundary. `followUp` waits for
current pending work to finish. Both require a running session; use `resume`
after it ends. `send --id STRING` allows retrying the same command ID without
reapplying it while that worker is alive. Do not carry that ID to a different run.

## Asynchronous completion handoff

A `queue` submission is not an immediate steer into a running Codex turn.
Dispatch independent work, finish the parent's independent work, then **end the
current turn** when the remaining work depends on a worker. The worker's enabled
queue callback can then wake the idle parent for acceptance and continuation.
Do not keep the turn active with waits, polling or filler reasoning. A commentary
message is not a turn yield. Verify that outstanding jobs have notifications
enabled and are bound to this chat before yielding. Yielding is not task completion.

While doing independent work, `inbox` provides a local check for pending results.
`wait JOB_ID... --timeout 30` remains available for bounded diagnostics (maximum
60 seconds), but is not the default orchestration loop. Both commands surface
failed/cancelled results, filter by source thread, and suppress runs after `ack`.
Waiting does not cancel jobs. No host-level immediate interruption is claimed.

## Persistent state

By default, state lives next to this package in `.codex-pi/jobs/`. Use the global
`--state-dir /absolute/path` option, before the command, to choose another store.
Each job has a persistent Pi session and numbered runs. Each run has separate
request, progress, event log, result, notification and acceptance files. `status`
returns the run directory and recent event; `result` returns model output and
per-run usage. `resume` starts a new worker process using the saved session.

Successful work and failed work both produce a result and, when enabled, a
`codex queue` notification. Codex reads the result, checks the actual artifacts,
then records the decision:

```bash
python3 pi.py ack pi_JOB_ID --run 1 --verdict accepted --note 'Checked the artifact and relevant tests.'
```

Use `rejected` if the deliverable does not pass. An already accepted notification
must not cause repeated task execution. Acknowledging the run is separate from
the worker's completion and the queue's submission.

`notify pi_JOB_ID --run 1` submits a pending notification without rerunning Pi.
Already queued or acknowledged notifications are not submitted again. If a queue
command times out, fails ambiguously, or the supervisor disappears during
submission, the state is `uncertain`/`submitting`. Automatic recovery does not
resend it. Inspect the chat before explicitly using `notify ... --retry`, since
delivery may already have occurred. This is not an exactly-once transport claim.

## Failure and recovery

- Cancellation requests Pi abort and gives it a short grace period before forced
  process cleanup. Existing files and session history remain.
- The supervisor enforces the deadline even during startup and detects worker
  exit without a result.
- `recover` recognizes a lost supervisor, terminates a surviving identified
  worker, retains its session, and marks unfinished work interrupted. It can also
  submit pending completion notifications. It never automatically replays tools.
- Inspect partial artifacts before resuming interrupted work. Recovery is an
  explicit command; no login service, reboot hook or background scanner is installed.
- Sudden OS/process death, orphaned detached commands, provider behavior, and
  changes to OpenCode's login/export API remain operational boundaries.

## Verification

`python3 verify.py` explicitly selects the Go example configuration and exercises real Muse project tools, AGENTS context, external
steering, queued follow-up, disk-session restoration, cancellation of a running
shell, parallel jobs in separate directories, worker failure and supervisor
recovery. It uses disposable fixtures and suppresses real chat notifications.
Notification state guards use a local queue stub. A separate final job verifies
the actual Codex Desktop queue callback. Reports name these boundaries explicitly.

`python3 verify_presets.py` separately tests real Muse/DeepSeek routing,
simultaneous jobs under the configured default limit, role-specific tools,
custom prompts, and a DeepSeek disk resume that retains its role/model snapshot.

## Codex-only skill

The installed skill lives at `~/.codex/skills/codex-pi-subagents`, with a dedicated
runtime and dependencies. Its guarded entry point is
`python3 ~/.codex/skills/codex-pi-subagents/scripts/pi.py`.
The wrapper requires the calling Codex host's `CODEX_THREAD_ID`; it does not
accept a manually supplied `--thread` as a substitute for host identity.
The skill proactively delegates independent work to Go workers in parallel.
Its default state directory is `~/.codex/pi-subagents`.

OpenCode, OMO and Pi workers must skip this skill even if they discover its text.
It does not change OpenCode's role files, routing, plugins or configuration.
This is a workflow guard, not a security boundary against a forged environment.
