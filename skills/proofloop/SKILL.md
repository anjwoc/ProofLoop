---
name: proofloop
description: Use when the user invokes ProofLoop or requests non-trivial feature work, bug fixes, refactors, or risky code changes that should run through ProofLoop's automatic evidence-driven coding harness.
---

# ProofLoop Entry Skill

## Absolute first constraints

These rules apply before host selection, planning, implementation, tests, progress reporting, or completion:

1. Never invent or inject a fake host, model identity, command result, elapsed time, changed file, test outcome, or completion state.
2. `TEST`, `MOCK`, `FAKE`, `SIMULATED`, fixture-only, `CLI_REQUESTED_ONLY`, and missing evidence never prove authenticated or production behavior.
3. A zero exit code, generated JSON, schema-valid artifact, package-presence check, or model statement proves only that exact event. It does not prove the user's requested behavior.
4. Never weaken, delete, skip, replace, or rewrite a required test/evaluator to obtain a pass. Never write Core evidence manually.
5. When evidence cannot be observed, report `NEEDS_INPUT`, `BLOCKED`, `FAILED`, `PARTIAL`, `UNPROVEN`, or the system error exactly as the parent artifacts state. Absence is never success.
6. Follow Ponytail after understanding the real flow: skip YAGNI work, reuse existing code, prefer stdlib/native/already-installed capabilities, and otherwise make the minimum cohesive change. Never simplify away validation, security, authorization, data-loss prevention, error handling, accessibility, or an explicit requirement.
7. Non-trivial changed logic requires the smallest runnable regression check that would fail if the behavior breaks.

The coordinator never decides these facts itself. It relays the deterministic parent run and its inspectable artifacts.

This skill is a thin bootstrap. The deterministic orchestrator owns the workflow. The public entry command is `proofloop-core run`; internal role commands are never a user workflow.

## Required behavior

1. Resolve the repository root first with `git rev-parse --show-toplevel` and keep it in an absolute
   `repo_root` variable. Capture the user's complete request verbatim in
   `$repo_root/.proofloop/requests/`. Never leave the shell in `.proofloop/requests/` after writing
   that file; immediately `cd "$repo_root"` before the runtime command.
2. Determine the current host as exactly one of `claude-code`, `codex`, or `agy`.
3. Select exactly one mode from the invocation: `adaptive` by default, `goal` for explicit convergence requests, or `audit` for read-only analysis. Benchmark requests use the dedicated `benchmark` command with a suite.
4. Start one parent-owned ProofLoop run in the background. The host conversation
   must remain available to relay its observable event stream; never block one
   terminal call until the entire run completes. Use this launch block after
   writing the verbatim request file:

```bash
repo_root="$(git rev-parse --show-toplevel)" || exit 1
proofloop_home="${PROOFLOOP_HOME:-$HOME/.proofloop}"
proofloop_core="$proofloop_home/bin/proofloop-core"
test -x "$proofloop_core" || { printf 'ProofLoop runtime missing: %s\n' "$proofloop_core" >&2; exit 1; }
request_dir="$repo_root/.proofloop/requests"
mkdir -p "$request_dir"
request_file="$request_dir/request-$(date +%Y%m%dT%H%M%S).txt"
# Write the complete, verbatim user request to "$request_file" here.
cd "$repo_root" || exit 1
relay_dir="$repo_root/.proofloop/relay/$(date -u +%Y%m%dT%H%M%SZ)-$$"
mkdir -p "$relay_dir"
printf '1\n' > "$relay_dir/next-line"
nohup "$proofloop_core" run \
  --mode <adaptive-or-goal-or-audit> \
  --host <current-host> \
  --repo "$repo_root" \
  --request-file "$request_file" \
  --output-format human \
  --verbosity info \
  --color never \
  > "$relay_dir/output.log" 2>&1 < /dev/null &
printf '%s\n' "$!" > "$relay_dir/pid"
printf 'RELAY_DIR=%s\nPID=%s\nPROOFLOOP_CORE=%s\n' "$relay_dir" "$(cat "$relay_dir/pid")" "$proofloop_core"
```

5. Tell the user the run has started, including only the observed run PID, runtime path, and
   relay status. Then keep polling in separate terminal calls until it reports
   finished; do not make a single long-running `tail -f` or wait call and do
   not return control to the user while the relay is active. Retain the
   absolute `RELAY_DIR` and `PROOFLOOP_CORE` from the launch result and use exactly this command:

```bash
"$PROOFLOOP_CORE" relay --relay-dir "$RELAY_DIR" --wait-seconds 3
```

6. Relay every new `[ProofLoop]` line to the user between polls. These are the
   only progress facts that may be presented: current phase/role, requested
   and observed model evidence, checks, recovery decisions, review, budget,
   and Truth verdict. The relay command outputs every newly appended observable
   line exactly once. Do not expose provider private reasoning or raw provider
   transcripts, and do not invent progress. If the user requests the TUI screen or debug view (`TUI`), pass `--tui` to relay (`"$PROOFLOOP_CORE" relay --relay-dir "$RELAY_DIR" --tui`) or inspect a completed/running session directly via `"$PROOFLOOP_CORE" tui --run latest`.

7. When the relay finishes, extract the run ID from the first `ProofLoop run` line in
   `output.log`. Then run the full run report command and print its output verbatim to the user:

```bash
"$PROOFLOOP_CORE" report --run-dir "$repo_root/.proofloop/runs/<run-id>"
```

   The report includes: verdict, task type (strategy), host, duration, per-model token usage,
   model routing by role (requested vs. observed), invocation timeline with cost per step,
   and total token/cost summary.

   Read `run-outcome.json` before treating the run as terminal. If its status is `NEEDS_INPUT`,
   read and present every question in `input-request.json`, then wait for the user's answer; do
   not call it `BLOCKED` and do not claim a Truth verdict. Otherwise also read
   `expected-output-report.json` when it exists. `truth-report.json` is the authoritative terminal
   verdict for completed work; `run-error.json` instead identifies a ProofLoop system failure that
   must not be presented as a Truth verdict. Never upgrade an incomplete evidence contract to a
   successful user result.

For a benchmark invocation, preserve the user's suite, hosts, model, repetition, and policy options and run `proofloop-core benchmark` directly. Never substitute an ordinary coding run for a requested comparison.

8. Do not implement the task in the coordinator session while the command runs.
9. Do not synthesize planning, role, verification, retry, recovery, review, or truth status. Display the orchestrator stream as the system status source.

## Host invocation names

- Claude Code: `/proofloop <request>`
- Codex: select `proofloop` through `/skills` or invoke `$proofloop <request>`
- AGY CLI (Antigravity): `/proofloop <request>`

Internal role execution is an orchestrator implementation detail and must not be shown as a user step.
