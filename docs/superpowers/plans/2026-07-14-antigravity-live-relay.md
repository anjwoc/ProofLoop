# Antigravity Live Relay Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent Antigravity stdin hangs and continuously expose observed role progress and output through the Antigravity coordinator.

**Architecture:** `ProcessRunner` owns child stdin and supplies a generic heartbeat callback. `host_runner` maps those primitives into bounded `role.progress` and `role.output` events, the human renderer displays them at info verbosity, and the generated Antigravity workflow runs the orchestrator in the background while relaying newly appended lines.

**Tech Stack:** Python standard library, subprocess pipes, threads, JSONL events, `unittest`, generated Markdown workflow

## Global Constraints

- Do not pass an Antigravity model flag.
- Invoke Antigravity with `--prompt ""` and deliver the prompt through stdin followed by EOF.
- Connect child stdin to `/dev/null` when no payload exists.
- Preserve complete raw logs while bounding event payload text.
- Never display the submitted prompt as progress.
- Preserve timeout 124, cancellation 130, process-group termination, and Codex/Claude behavior.
- Keep Antigravity `ROLE_ROUTING_ONLY` and do not claim cross-model routing.

---

### Task 1: Deterministic stdin and silent-process heartbeat

**Files:**
- Modify: `proofloop_core/process_runner.py:14-257`
- Test: `tests/deterministic/test_process_runner.py:15-247`

**Interfaces:**
- Consumes: `ProcessRunner.run(command, cwd, stdout_path, stderr_path, ...)`
- Produces: `stdin_data: str | bytes | None`, `on_heartbeat: Callable[[int, float], None] | None`, and `heartbeat_interval_seconds: float`

- [ ] **Step 1: Write failing stdin test**

Add a test that runs Python code which reads `sys.stdin.buffer.read()`, writes the received bytes to stdout, and calls `ProcessRunner.run(..., stdin_data=b"planner prompt")`. Assert exit code 0 and exact output `planner prompt`.

- [ ] **Step 2: Write failing heartbeat test**

Run a silent Python process for 0.15 seconds with `on_heartbeat` appending `(pid, elapsed)` and `heartbeat_interval_seconds=0.03`. Assert at least two callbacks, positive PID values, and increasing elapsed values.

- [ ] **Step 3: Verify RED**

Run:

```bash
python3 -m unittest \
  tests.deterministic.test_process_runner.ProcessRunnerTest.test_stdin_payload_is_closed_after_delivery \
  tests.deterministic.test_process_runner.ProcessRunnerTest.test_silent_process_emits_heartbeats -v
```

Expected: both tests error because the new keyword arguments do not exist.

- [ ] **Step 4: Implement stdin ownership**

Use `subprocess.DEVNULL` when `stdin_data is None`; otherwise use `subprocess.PIPE`, encode string input as UTF-8, write from a daemon thread, flush, and close the pipe. Ignore `BrokenPipeError` after early child exit and surface other writer errors after process completion.

- [ ] **Step 5: Implement heartbeat callback**

During the existing monitor loop, call `on_heartbeat(process.pid, elapsed_seconds)` at the configured interval while the process is alive. Route callback failures through the existing process termination behavior.

- [ ] **Step 6: Verify GREEN and regression safety**

Run:

```bash
python3 -m unittest tests.deterministic.test_process_runner -v
```

Expected: all process runner tests pass, including timeout and descendant cleanup.

### Task 2: Antigravity prompt delivery and live role events

**Files:**
- Modify: `proofloop_core/host_runner.py:38-215`
- Modify: `proofloop_core/renderers/human.py:26-190`
- Test: `tests/deterministic/test_host_adapters.py:172-347`
- Test: `tests/deterministic/test_renderers.py:31-194`

**Interfaces:**
- Consumes: Task 1 `stdin_data` and heartbeat callback
- Produces: `role.progress` and `role.output` JSONL events

- [ ] **Step 1: Write failing Antigravity stdin test**

Change the fake `agy` fixture to record `sys.argv[1:]` and `sys.stdin.read()`. Assert arguments contain `--prompt` followed by an empty string, exclude `-p` and `--model`, and stdin equals the supplied role prompt.

- [ ] **Step 2: Write failing event tests**

Use a fake Antigravity executable that prints `working on plan`, sleeps briefly, and exits. Invoke `invoke_role` with an `EventEmitter` and a short heartbeat interval. Assert at least one `role.output` event contains the observed line and at least one `role.progress` event contains a positive PID and elapsed time.

- [ ] **Step 3: Write failing renderer test**

Render `role.progress` and `role.output` at info verbosity. Assert the human stream includes the role name, `running`, elapsed seconds, PID, stream name, and bounded output text.

- [ ] **Step 4: Verify RED**

Run the new host adapter and renderer tests. Expected failures: old `-p` argument use, missing stdin payload, generic renderer output, and absent progress/output events.

- [ ] **Step 5: Implement Antigravity mapping**

Build `[agy, optional-permission-flag, "--prompt", ""]`, pass the message through `stdin_data`, emit heartbeat data with invocation/log references, and emit non-empty Antigravity output lines with at most 4,000 characters plus a `truncated` flag.

- [ ] **Step 6: Implement human rendering**

Format `role.progress` and `role.output` explicitly and keep both visible at info verbosity. Continue flushing after every event through `EventEmitter`.

- [ ] **Step 7: Verify GREEN**

Run:

```bash
python3 -m unittest \
  tests.deterministic.test_host_adapters \
  tests.deterministic.test_renderers -v
```

Expected: all adapter and renderer tests pass.

### Task 3: Antigravity background coordinator relay

**Files:**
- Modify: `proofloop_core/hosts.py:180-205`
- Test: `tests/deterministic/test_host_adapters.py:42-64`

**Interfaces:**
- Consumes: default human event stream containing `role.progress` and `role.output`
- Produces: generated Antigravity `/proofloop` workflow with per-run relay directory, PID file, output log, incremental polling, and exact truth reporting

- [ ] **Step 1: Write failing workflow contract test**

Assert the built workflow includes a detached background launch, `< /dev/null`, `output.log`, `pid`, incremental line polling, instructions to relay every new `[ProofLoop]` line between tool calls, a liveness check, and final `truth-report.json` handling. Assert the obsolete `Run exactly one bootstrap command` instruction is absent.

- [ ] **Step 2: Verify RED**

Run:

```bash
python3 -m unittest tests.deterministic.test_host_adapters.HostAdapterTest.test_antigravity_adapter_has_recognizable_frontmatter -v
```

Expected: workflow relay assertions fail.

- [ ] **Step 3: Implement the workflow recipe**

Generate commands that create `.proofloop/relay/<timestamp>`, launch `proofloop-core orchestrate` under `nohup` with stdin closed, save PID and output, then require bounded repeated polling of only unseen lines. The coordinator must show observed lines rather than invented summaries and report the exact final truth status.

- [ ] **Step 4: Verify GREEN and package generation**

Run:

```bash
python3 -m unittest tests.deterministic.test_host_adapters -v
python3 scripts/validate_package.py
```

Expected: adapter tests and package validation pass.

### Task 4: Full verification, installation, and publication

**Files:**
- Verify all files above
- Generated install targets under `$HOME/.proofloop`, `$HOME/.gemini`, `$HOME/.codex`, and Claude plugin storage

**Interfaces:**
- Consumes: completed Tasks 1-3
- Produces: installed and pushed ProofLoop runtime

- [ ] **Step 1: Run full verification**

```bash
codegraph sync .
python3 -m unittest discover -s tests -v
python3 scripts/validate_package.py
python3 -m compileall -q proofloop_core tests scripts
git diff --check
```

Expected: all tests pass, package validation reports PASS, compilation succeeds, and no whitespace errors exist.

- [ ] **Step 2: Reinstall all adapters**

```bash
python3 scripts/install.py --host all --scope user
```

Expected: Claude Code, Codex, and Antigravity installation results succeed.

- [ ] **Step 3: Verify installed behavior without a real model call**

Run the installed `proofloop-core invoke-role` against a fake `agy` that reads stdin, prints a line, and briefly sleeps. Assert exact prompt delivery, EOF completion, visible progress/output events, no `--model`, and `ROLE_ROUTING_ONLY` evidence.

- [ ] **Step 4: Commit and push main**

Stage only implementation, tests, and plan files. Preserve the user's existing `.gitignore` and `.proofloop/` artifacts. Commit with `fix: stream Antigravity role progress`, push `origin main`, and verify local and remote SHA equality.
