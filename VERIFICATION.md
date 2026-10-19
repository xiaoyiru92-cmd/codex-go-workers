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
