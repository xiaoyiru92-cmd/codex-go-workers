# Verification boundaries

The initial implementation was exercised on one local macOS setup using OpenCode Desktop v2.0.32, Pi SDK 1.3.0 and a Codex Desktop bundled CLI supporting `queue`. This is not a compatibility guarantee for every installation or future release.

## Real-route checks completed during development

- Reused the active local OpenCode v2 login for Muse Spark 1.3 Contributor and DeepSeek V4.1 Flash on Go.
- Ran real project file tools and shell verification, project AGENTS instructions, external steering while a tool was active, and queued follow-up.
- Restored saved Pi sessions in a new process and recalled earlier context.
- Ran two real workers concurrently in distinct directories and checked role-specific tool restrictions.
- Cancelled a running shell, exercised startup deadlines, worker failure, and lost-supervisor recovery without replaying completed work.
- Delivered a completion through real `codex queue` to the same idle chat after its originating turn ended, then recorded acceptance.
- Confirmed that two concurrent submissions with the same steering instruction ID produced one command record.

## Offline checks

`python3 -m unittest -v test_offline.py` checks compact agent discovery, preset routing and tool restrictions, isolated installation, overwrite refusal, and the Codex-only entry guard. The earlier notification-state guard checks used a local queue stub; they do not independently prove desktop delivery.

## Not established

- Twenty simultaneous real model calls: 20 is the configured capacity, not a measured stress-test result.
- Long-term delivery reliability, reboot recovery, automatic OAuth refresh, exactly-once transport, or automatic replay after interruption.
- OS sandbox isolation or guaranteed cleanup of every detached descendant after abrupt OS/process death.
- Windows/Linux support, arbitrary OpenCode backends, WorkBuddy routes, or GPT authentication through Pi.
- Native GPT role preset installation. GPT agents remain a separate Codex concern.

Raw development sessions, account data, model transcripts, local paths and chat identifiers are deliberately not included. Repeat the relevant live tests on your own machine before relying on this workflow.

## Audit and first-run configuration update (2026-10-19)

The source audit reproduced and fixed four runtime/input defects:

- A worker's surviving descendant could hold its stdout pipe open, causing the supervisor to block on EOF after worker exit and stop enforcing its deadline. The supervisor now drains only buffered output with a bounded nonblocking read.
- Rejected event-log writes could terminate Node before final result/session metadata was saved. Event failures are now handled, reported explicitly, and permit best-effort result finalization. A completely unwritable disk can still prevent any file from being saved.
- An explicit run number of zero silently selected the current run. It is now rejected.
- NaN/infinite timeout values bypassed the deadline. They are now rejected before launch.

A real Go verification run also exposed a test-runner defect: parallel tool events
could replace a long-running bash start in `progress.json`, and the test falsely
timed out. The test now uses durable event history and reports terminal failure
without waiting out the timer. After that repair, all nine `verify.py` checks
passed on the real Go route: tools/AGENTS/steering/follow-up, disk resume, write
conflict, cancellation, parallel jobs, startup timeout, worker crash, lost
supervisor recovery, and notification deduplication. The last notification-state
check uses a stub, as before. Audit callback messages reached the originating chat, but the user had to steer some while the parent was busy. This does not prove automatic idle-turn wakeup.

New installations require an explicit API/model choice. Existing Go configuration
is preserved. Python checks cover both setup choices, cancellation and private
backups, installed first-run behavior, lifecycle regressions and direct handoff.
Node checks cover compatible-API URL/source validation and key-file handling.
The compatible-API integration test uses **real Pi SDK + a local simulated HTTP
server** to test streamed tool calls, model IDs, token caps, disk resume with the
saved endpoint, credential non-persistence in normal execution, keyless requests,
and `wait`/`ack` handoff. This does not validate any external custom provider.

`inbox`/`wait` state tests include failures/cancellation, cross-chat filtering,
old pending runs, acknowledgement deduplication and finite waits. A real Muse
read task also returned its result through `wait` with notifications disabled.
This proves direct retrieval, not asynchronous turn handoff. The default policy
now requires the parent to end its current turn when blocked on workers, and
resume through queue when idle. `wait` is diagnostic only. No host-level
preemption is claimed. A real yield-and-wake check then completed: the parent
turn ended at 15:49:29, the worker completed at 15:49:48, and its callback started
a new parent turn at 15:49:58 (Asia/Taipei, 2026-10-19). The worker executed the
15-second fixture and returned the expected marker. The visible turn history
contains the callback as the next turn input, with no additional human message
between the explicit yield and callback. This is one observed successful idle
handoff, not a guarantee of long-term delivery reliability.

Final automated checks: 27 Python tests and 11 Node tests passed. The Python
count includes the real-SDK/local simulated API test; it must not be described
as an external API availability test.

One real DeepSeek audit worker failed with a provider connection error after
multiple requests and delivered no usable final report. That run was rejected;
it is not counted as a successful audit or an all-provider availability result.

The user subsequently confirmed that expanding the completed-turn activity section restored visibility of the earlier messages. The queried history retained those messages. This incident was a collapsed-history presentation issue, not observed deletion. The handoff policy now requires a visible summary of confirmed user decisions, completed work, and pending continuation before yielding; it does not claim control over the host UI.

## Follow-up audit (2026-10-19)

Resume incorrectly depended on a readable, valid live config even though each
run contains its model/tool/session snapshot. This was reproduced with a missing
config and fixed: resume now uses the saved worker limit (legacy fallback 20),
with an explicit --max-workers override still supported. New jobs continue to
validate the current config. Regression tests cover missing, malformed and
setup-required configs. The real Pi SDK/local simulated API integration also
resumes successfully after deleting the config, retaining the same session.
This is local protocol verification, not a new external provider guarantee.
Five lifecycle tests and the expanded compatible integration test passed.

Three real read-only Go audit workers completed in parallel (two Muse, one
DeepSeek). Root accepted the verified source/install drift finding and rejected
unreproduced claims; model completion alone is not audit acceptance.

## Completion notification retraction (2026-10-19)

Two real Muse reviewer runs exercised both paths in the originating Codex chat:

- **Accepted while the parent was still active:** run 1 completed and submitted
  one notification. The live queue listed its ID, which matched the CLI receipt.
  The updated `ack` saved acceptance and returned `retraction.status=removed`.
  A second live queue read found no matching message. After the parent yielded,
  native chat-history inspection showed no run-1 callback turn.
- **Not accepted in advance:** run 2 used the updated installed runtime. The
  parent ended its turn at 16:20:04 Asia/Taipei. The worker completed at 16:20:07
  and submitted one notification; a new parent turn started at 16:20:08 with
  that exact run-2 callback as its input. There was no intervening human message.
  `acceptance.json` was absent on receipt. The message was already consumed from
  the queue, so subsequent acceptance correctly reported `not_pending`, not
  `removed`.

These were real Go workers and real Codex queue list/delete/delivery operations,
not mocked wake-ups. Local audit artifacts remain in ignored `work/` and the
run store; no credentials or chat transcript are published here. The installed
notification functions and queue transport were checked against this source;
unrelated newer installed lifecycle changes were preserved, not overwritten.

Ten new offline notification tests cover acceptance before submission, normal
single submission, concurrent submit/ack ordering, uncertain/lost submission
receipts, retry after cleanup failure, cross-chat rejection, exact marker
ownership, pagination, consumed messages, and bounded subprocess transport.
The related test selection passed 31 tests. Full Python discovery passed 37
tests and skipped one unchanged compatible-API integration test because this
checkout lacks npm dependencies; no new external compatible-provider test is
claimed. One initial EOF fixture failed because its 0.2-second deadline expired
during interpreter startup; only that fixture's startup allowance was changed
to two seconds. The transport timeout behavior itself was unchanged.

The code review found no blocking notification defect. Its two lifecycle
regression claims compared the checkout with newer installed files; the
supervisor/recovery code was unchanged by this diff, and those installed fixes
were retained. This is a bounded live verification, not an exactly-once promise:
delivery can win the race with acceptance, and unavailable queue APIs leave a
reported retryable cleanup failure. Already delivered history is never deleted.
