# ProofLoop Execution Visibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stream one authoritative ProofLoop event sequence to `events.jsonl`, host UIs, and `watch` while preserving deterministic truth artifacts and existing quiet CLI behavior.

**Architecture:** Add a thread-safe `EventEmitter` with pluggable human/JSONL/quiet renderers, then route host and check subprocesses through one concurrent `ProcessRunner`. Host parsers normalize only trusted signals; the orchestrator emits state/repair/review/truth events from real results, and `watch` replays the persisted stream.

**Tech Stack:** Python 3.11+ standard library (`argparse`, `dataclasses`, `json`, `queue`, `subprocess`, `threading`, `unittest`); no new runtime dependencies.

## Global Constraints

- Web dashboard, HTTP, WebSocket, and SSE are out of scope.
- `events.jsonl` schema version is exactly `"1"`.
- Requested and observed models remain separate and use `HOST_RESOLVED`, `HOST_OUTPUT`, `CLI_REQUESTED_ONLY`, `CONFIG_ONLY`, or `UNAVAILABLE` evidence.
- Existing truth/check/diff/invocation/trace artifacts and default final JSON CLI behavior remain compatible.
- Host prose never overrides deterministic process, check, review, or truth evidence.
- Use CodeGraph for repository exploration; after every source/test edit batch run `codegraph sync .` before further structural exploration.
- Follow red-green-refactor: every production behavior begins with a test observed failing for the intended reason.

---

## File Map

- Create `proofloop_core/events.py`: event persistence, sequence recovery, corruption handling, renderer dispatch.
- Create `proofloop_core/renderers/{__init__,human,jsonl,quiet}.py`: renderer protocol/selection and output policies.
- Create `proofloop_core/process_runner.py`: concurrent streaming subprocess execution.
- Create `proofloop_core/output_parsers/{__init__,base,codex,antigravity,claude}.py`: normalized host evidence.
- Create `proofloop_core/watch.py`: event replay/follow/filter.
- Modify `proofloop_core/host_runner.py`: use `ProcessRunner`, parsers, emitter, and preserve invocation artifacts.
- Modify `proofloop_core/adapters.py`: carry the emitter and invocation context to `host_runner`.
- Modify `proofloop_core/checks.py`: stream deterministic checks and emit check events.
- Modify `proofloop_core/orchestrator.py`: create emitter and map all real state paths to events.
- Modify `proofloop_core/cli.py`: output options, quiet compatibility, and `watch` command.
- Modify `skills/proofloop/SKILL.md` and `proofloop_core/hosts.py`: public human-streaming host entry commands.
- Modify deterministic/orchestration tests and add focused test modules listed below.

---

### Task 1: Event Store and Renderers

**Files:**
- Create: `proofloop_core/events.py`
- Create: `proofloop_core/renderers/__init__.py`
- Create: `proofloop_core/renderers/human.py`
- Create: `proofloop_core/renderers/jsonl.py`
- Create: `proofloop_core/renderers/quiet.py`
- Create: `tests/deterministic/test_events.py`
- Create: `tests/deterministic/test_renderers.py`

**Interfaces:**
- Produces: `EventEmitter(run_id, run_dir, stream, output_format, verbosity="info", color="auto")`.
- Produces: `EventEmitter.emit(event_type, *, phase, message, level="info", task_id=None, data=None) -> dict[str, Any]`.
- Produces: `build_renderer(output_format, stream, verbosity, color) -> Renderer`.

- [ ] **Step 1: Write failing event persistence tests**

```python
class FlushTrackingStream(io.StringIO):
    def __init__(self):
        super().__init__()
        self.flush_count = 0

    def flush(self) -> None:
        self.flush_count += 1
        super().flush()


def test_event_is_persisted_and_rendered_from_same_object(self) -> None:
    emitter = EventEmitter("run-1", root, stream, "jsonl")
    event = emitter.emit("run.started", phase="INIT", message="Run started.")
    stored = json.loads((root / "events.jsonl").read_text().strip())
    rendered = json.loads(stream.getvalue().strip())
    self.assertEqual(event, stored)
    self.assertEqual(stored, rendered)
    self.assertEqual(1, event["sequence"])
    self.assertEqual("evt-000001", event["eventId"])
    self.assertGreaterEqual(stream.flush_count, 1)
```

Add tests that 32 concurrent emits produce sequences `1..32`, restart continues at 33, an incomplete final fragment is moved to `events.corrupt-tail.log`, and a complete malformed JSON line raises `EventStoreCorruptError`.

- [ ] **Step 2: Run the event tests and verify RED**

Run: `python3 -m unittest tests.deterministic.test_events -v`

Expected: import failure for `proofloop_core.events`.

- [ ] **Step 3: Implement the event store and renderer protocol**

```python
class EventEmitter:
    def __init__(self, run_id: str, run_dir: Path, stream: TextIO,
                 output_format: str, verbosity: str = "info", color: str = "auto") -> None:
        self.run_id = run_id
        self.run_dir = Path(run_dir)
        self.path = self.run_dir / "events.jsonl"
        self.stream = stream
        self.renderer = build_renderer(output_format, stream, verbosity, color)
        self._lock = threading.RLock()
        self._sequence = self._recover_sequence()

    def emit(self, event_type: str, *, phase: str, message: str,
             level: str = "info", task_id: str | None = None,
             data: dict[str, Any] | None = None) -> dict[str, Any]:
        with self._lock:
            self._sequence += 1
            event = {
                "schemaVersion": "1",
                "eventId": f"evt-{self._sequence:06d}",
                "runId": self.run_id,
                "timestamp": datetime.now().astimezone().isoformat(timespec="milliseconds"),
                "sequence": self._sequence,
                "type": event_type,
                "level": level,
                "phase": phase,
                "message": message,
                "data": dict(data or {}),
            }
            if task_id is not None:
                event["taskId"] = task_id
            serialized = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(serialized + "\n")
                handle.flush()
            self.renderer.render(event)
            return event
```

`_recover_sequence()` validates each complete line, quarantines only an unterminated final fragment, and returns the last sequence. `JsonlRenderer` writes compact JSON plus newline; `QuietRenderer` does nothing.

- [ ] **Step 4: Write failing human renderer tests**

```python
def test_human_renderer_separates_requested_and_unobserved_model(self) -> None:
    renderer.render({
        "type": "role.model_observed", "phase": "EXECUTE", "level": "warning",
        "message": "Model observation unavailable.", "taskId": "TASK-001",
        "data": {"role": "implementer_fast", "requestedModel": "Gemini Flash",
                 "observedModel": None, "evidenceLevel": "CLI_REQUESTED_ONLY"},
    })
    text = stream.getvalue()
    self.assertIn("[ProofLoop][EXECUTE]", text)
    self.assertIn("requested: Gemini Flash", text)
    self.assertIn("observed: unavailable", text)
    self.assertIn("routing proof: UNPROVEN", text)
```

Add exact assertions for role start, check pass/fail, recovery, review fix, truth completion, verbosity filtering, and no ANSI sequences when color is `never`.

- [ ] **Step 5: Run renderer tests and verify RED**

Run: `python3 -m unittest tests.deterministic.test_renderers -v`

Expected: missing human renderer behavior.

- [ ] **Step 6: Implement human rendering and verify GREEN**

Implement event-specific formatters for the approved event families. Every line begins with `[ProofLoop][<PHASE>]`; unknown event types fall back to the event message. `info`, `verbose`, and `debug` use a numeric threshold; color policy uses `stream.isatty()` only for `auto`.

Run: `python3 -m unittest tests.deterministic.test_events tests.deterministic.test_renderers -v`

Expected: all Task 1 tests pass.

- [ ] **Step 7: Sync CodeGraph and commit**

```bash
codegraph sync .
git add proofloop_core/events.py proofloop_core/renderers tests/deterministic/test_events.py tests/deterministic/test_renderers.py
git commit -m "feat: add authoritative event stream renderers"
```

---

### Task 2: Streaming Process Runner

**Files:**
- Create: `proofloop_core/process_runner.py`
- Create: `tests/deterministic/test_process_runner.py`

**Interfaces:**
- Produces: immutable `ProcessResult(command, cwd, exit_code, timed_out, cancelled, duration_seconds, stdout_ref, stderr_ref)`.
- Produces: `ProcessRunner.run(command, *, cwd, stdout_path, stderr_path, env=None, timeout_seconds, on_line=None) -> ProcessResult`.

- [ ] **Step 1: Write failing streaming, deadlock, and timeout tests**

```python
def test_line_callback_runs_before_process_exits(self) -> None:
    arrivals: list[tuple[str, str, float]] = []
    started = time.monotonic()
    result = runner.run(
        [sys.executable, "-u", "-c", "import time; print('first', flush=True); time.sleep(.4); print('last', flush=True)"],
        cwd=root, stdout_path=root / "out.log", stderr_path=root / "err.log",
        timeout_seconds=3,
        on_line=lambda stream, line: arrivals.append((stream, line, time.monotonic() - started)),
    )
    self.assertEqual(0, result.exit_code)
    self.assertLess(arrivals[0][2], 0.3)
```

Add one fixture writing 2,000 lines to each stream and one sleeping process that must return `124`, set `timed_out`, and preserve pre-timeout output.

- [ ] **Step 2: Run and verify RED**

Run: `python3 -m unittest tests.deterministic.test_process_runner -v`

Expected: import failure for `proofloop_core.process_runner`.

- [ ] **Step 3: Implement concurrent pipe draining**

```python
@dataclass(frozen=True)
class ProcessResult:
    command: tuple[str, ...]
    cwd: str
    exit_code: int
    timed_out: bool
    cancelled: bool
    duration_seconds: float
    stdout_ref: str
    stderr_ref: str


def reader(name: str, pipe: TextIO, handle: TextIO) -> None:
    try:
        for line in iter(pipe.readline, ""):
            handle.write(line)
            handle.flush()
            messages.put((name, line))
    finally:
        messages.put((name, None))
```

The main loop waits at most 100 ms per queue poll, checks timeout using `time.monotonic()`, terminates then kills after a two-second grace period, drains until two sentinels, joins both threads, and maps timeout to exit code 124.

- [ ] **Step 4: Run tests and verify GREEN**

Run: `python3 -m unittest tests.deterministic.test_process_runner -v`

Expected: all tests pass with no warnings or leaked processes.

- [ ] **Step 5: Sync CodeGraph and commit**

```bash
codegraph sync .
git add proofloop_core/process_runner.py tests/deterministic/test_process_runner.py
git commit -m "feat: stream subprocess output without deadlocks"
```

---

### Task 3: Host Output Parsers and Host Runner Integration

**Files:**
- Create: `proofloop_core/output_parsers/__init__.py`
- Create: `proofloop_core/output_parsers/base.py`
- Create: `proofloop_core/output_parsers/codex.py`
- Create: `proofloop_core/output_parsers/antigravity.py`
- Create: `proofloop_core/output_parsers/claude.py`
- Modify: `proofloop_core/host_runner.py`
- Modify: `proofloop_core/adapters.py`
- Create: `tests/deterministic/test_output_parsers.py`
- Modify: `tests/deterministic/test_host_adapters.py`

**Interfaces:**
- Produces: `NormalizedHostEvent(event_type, message, data, level="info")`.
- Produces: `HostOutputParser.feed(stream, line) -> list[NormalizedHostEvent]`.
- Produces: `parser_for(host) -> HostOutputParser`.
- Extends: `RoleInvocation` with optional `emitter`, `phase`, `task_id`, and `attempt`.
- Extends: `invoke_role(..., emitter=None, phase="EXECUTE", task_id=None, attempt=None)` without breaking existing positional callers.

- [ ] **Step 1: Write failing parser contract tests**

```python
def test_codex_structured_model_is_observed(self) -> None:
    events = CodexOutputParser().feed("stdout", '{"type":"thread.started","model":"gpt-5.6-terra"}\n')
    self.assertEqual("role.model_observed", events[0].event_type)
    self.assertEqual("gpt-5.6-terra", events[0].data["observedModel"])
    self.assertEqual("HOST_OUTPUT", events[0].data["evidenceLevel"])

def test_free_form_success_sentence_is_ignored(self) -> None:
    self.assertEqual([], ClaudeOutputParser().feed("stdout", "All tests passed.\n"))
```

Add fixtures for host errors, rate limits, permission requests, and unavailable Antigravity model evidence.

- [ ] **Step 2: Run parser tests and verify RED**

Run: `python3 -m unittest tests.deterministic.test_output_parsers -v`

Expected: missing parser package.

- [ ] **Step 3: Implement strict structured parsers**

```python
@dataclass(frozen=True)
class NormalizedHostEvent:
    event_type: str
    message: str
    data: dict[str, Any]
    level: str = "info"


class CodexOutputParser:
    def feed(self, stream: str, line: str) -> list[NormalizedHostEvent]:
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            return []
        model = detect_model(value) if isinstance(value, dict) else None
        if model:
            return [NormalizedHostEvent("role.model_observed", "Host model observed.",
                    {"observedModel": model, "evidenceLevel": "HOST_OUTPUT"})]
        return normalize_known_host_error(value)
```

Claude and Antigravity follow the same strict rule. Exact rate-limit/permission/error markers may emit warning/error events, but ordinary prose emits nothing.

- [ ] **Step 4: Write failing host runner streaming test**

Use a fake executable that emits one JSON model line, waits, then exits. Assert the emitter receives `role.model_observed`, raw logs contain both lines, invocation JSON retains existing keys, and `modelEvidence` becomes `HOST_OUTPUT`. Add an unobserved fake asserting `CLI_REQUESTED_ONLY`.

- [ ] **Step 5: Replace `subprocess.run(capture_output=True)` in host runner**

Call `ProcessRunner.run()` with raw artifact paths and a callback that feeds the selected parser. Merge role/request/invocation context into normalized data before emitting. De-duplicate model observations and emit one explicit requested-only observation after process exit when no model was found. Preserve the prior return keys and trace summary.

- [ ] **Step 6: Verify parser and adapter tests GREEN**

Run: `python3 -m unittest tests.deterministic.test_output_parsers tests.deterministic.test_host_adapters -v`

Expected: all tests pass, including existing positional `invoke-role` CLI tests.

- [ ] **Step 7: Sync CodeGraph and commit**

```bash
codegraph sync .
git add proofloop_core/output_parsers proofloop_core/host_runner.py proofloop_core/adapters.py tests/deterministic/test_output_parsers.py tests/deterministic/test_host_adapters.py
git commit -m "feat: parse streamed host execution evidence"
```

---

### Task 4: Stream Deterministic Checks

**Files:**
- Modify: `proofloop_core/checks.py`
- Modify: `proofloop_core/external_loop.py`
- Modify: `tests/deterministic/test_checks.py`
- Modify: `tests/orchestration/test_external_loop.py`

**Interfaces:**
- Extends: `run_checks(task, repository, output_dir, *, emitter=None, phase="VERIFY")`.
- Preserves: existing report schema and exit-code authority.

- [ ] **Step 1: Write failing check event tests**

```python
def test_check_streams_output_and_real_failure(self) -> None:
    emitter = RecordingEmitter()
    report = run_checks(task, root, root / "evidence", emitter=emitter)
    types = [event["type"] for event in emitter.events]
    self.assertEqual("check.started", types[0])
    self.assertIn("check.output", types)
    self.assertEqual("check.failed", types[-1])
    self.assertEqual(7, emitter.events[-1]["data"]["exitCode"])
```

Add a slow check assertion proving `check.output` reaches the emitter before function return.

- [ ] **Step 2: Run and verify RED**

Run: `python3 -m unittest tests.deterministic.test_checks -v`

Expected: `run_checks()` rejects the `emitter` keyword.

- [ ] **Step 3: Route checks through `ProcessRunner`**

Before each command emit `check.started` with command ID, command, and cwd. Emit every delivered line as `check.output` with stream and text. Build the unchanged report from `ProcessResult`; emit `check.completed` or `check.failed` after the report evidence exists.

Update `external_loop.run_external_loop()` to accept an optional emitter and pass it to `run_checks`; preserve all existing callers.

- [ ] **Step 4: Verify GREEN and regression**

Run: `python3 -m unittest tests.deterministic.test_checks tests.orchestration.test_external_loop -v`

Expected: new streaming tests and existing exit-code/repair tests pass.

- [ ] **Step 5: Sync CodeGraph and commit**

```bash
codegraph sync .
git add proofloop_core/checks.py proofloop_core/external_loop.py tests/deterministic/test_checks.py tests/orchestration/test_external_loop.py
git commit -m "feat: stream deterministic verification events"
```

---

### Task 5: Orchestrator Event Mapping

**Files:**
- Modify: `proofloop_core/orchestrator.py`
- Modify: `tests/orchestration/test_orchestrator.py`
- Modify: `tests/orchestration/test_orchestrate_cli.py`

**Interfaces:**
- Extends: `ProofLoopOrchestrator(..., stream=None, output_format="quiet", verbosity="info", color="auto")`.
- Extends: `orchestrate(..., stream=None, output_format="quiet", verbosity="info", color="auto")`.
- Produces: one standard event stream covering run/capability/strategy/context/role/task/check/diff/repair/review/truth/budget paths.

- [ ] **Step 1: Write failing normal-flow event assertions**

```python
result = orchestrate("codex", repo, "Implement value", adapter=adapter,
                     stream=io.StringIO(), output_format="jsonl")
events = [json.loads(line) for line in (Path(result["runDir"]) / "events.jsonl").read_text().splitlines()]
types = [event["type"] for event in events]
self.assertEqual("run.started", types[0])
self.assertIn("strategy.selected", types)
self.assertIn("task.created", types)
self.assertIn("role.started", types)
self.assertIn("check.completed", types)
self.assertIn("review.completed", types)
self.assertEqual("run.completed", types[-1])
```

Add recovery assertions for `progress.stalled` and `recovery.scheduled` with repeated fingerprint, review-repair assertions, model-unobserved assertions, and terminal blocked/failed assertions.

- [ ] **Step 2: Run selected orchestration tests and verify RED**

Run: `python3 -m unittest tests.orchestration.test_orchestrator -v`

Expected: `orchestrate()` rejects output arguments or no `events.jsonl` exists.

- [ ] **Step 3: Create and inject the emitter**

After `start_run()`, create `EventEmitter(started["runId"], run_dir, stream or sys.stdout, output_format, verbosity, color)`. Add `_emit()` to no-op only before emitter creation. Pass the emitter/context through every `RoleInvocation` and `run_checks()` call.

- [ ] **Step 4: Emit events from actual state and artifacts**

Add explicit emits at these evidence boundaries:

```python
self._emit("run.started", phase="INIT", message="ProofLoop run started.", data={"host": self.host})
self._emit("role.started", phase=phase, message=f"{role} started.", task_id=task_id,
           data={"role": role, "attempt": attempt, "requestedModel": requested_model,
                 "routingMode": self.capability.get("mode"), "invocationId": invocation_id})
self._emit("recovery.scheduled", phase="REPAIR", level="warning", task_id=task.task_id,
           message="Escalating implementation role.", data={"fromRole": role,
           "toRole": "implementer_recovery", "reasonCode": decision.get("reasonCode"),
           "reason": decision["reason"], "fingerprint": attempt["failureFingerprint"],
           "attempts": sequence})
```

Use actual review JSON and truth report for their events. Ensure `_finalize_terminal()` ends with `run.blocked` or `run.failed`; `_finalize_truth()` emits `truth.completed` then `run.completed`.

- [ ] **Step 5: Preserve legacy artifacts and verify GREEN**

Run: `python3 -m unittest tests.orchestration.test_orchestrator tests.orchestration.test_orchestrate_cli -v`

Expected: all old truth assertions and new event assertions pass.

- [ ] **Step 6: Sync CodeGraph and commit**

```bash
codegraph sync .
git add proofloop_core/orchestrator.py tests/orchestration/test_orchestrator.py tests/orchestration/test_orchestrate_cli.py
git commit -m "feat: emit orchestrator state and truth events"
```

---

### Task 6: CLI Output Modes and Watch

**Files:**
- Create: `proofloop_core/watch.py`
- Modify: `proofloop_core/cli.py`
- Create: `tests/deterministic/test_watch.py`
- Modify: `tests/orchestration/test_orchestrate_cli.py`

**Interfaces:**
- Produces: `watch_events(run_dir, *, stream, output_format="human", verbosity="info", color="auto", task_id=None, minimum_level=None, follow=True, poll_interval=0.1)`.
- CLI: `orchestrate --output-format --verbosity --color`.
- CLI: `watch (--run latest --repo . | --run-dir PATH) --format --verbosity --color --task --level --no-follow`.

- [ ] **Step 1: Write failing CLI format tests**

Run the fake-host CLI in each mode. Assert quiet stdout parses as the existing final JSON; JSONL stdout contains only schema-version-1 event objects and ends in `run.completed`; human stdout begins with `[ProofLoop]`, includes requested/observed model labels, and contains no pretty JSON result.

- [ ] **Step 2: Write failing watch tests**

```python
def test_watch_replays_filtered_complete_lines(self) -> None:
    watch_events(run_dir, stream=stream, output_format="jsonl", task_id="TASK-002",
                 minimum_level="warning", follow=False)
    events = [json.loads(line) for line in stream.getvalue().splitlines()]
    self.assertTrue(events)
    self.assertTrue(all(event.get("taskId") == "TASK-002" for event in events))
    self.assertTrue(all(event["level"] in {"warning", "error"} for event in events))
```

Add latest-run selection and an incomplete final line test.

- [ ] **Step 3: Run tests and verify RED**

Run: `python3 -m unittest tests.deterministic.test_watch tests.orchestration.test_orchestrate_cli -v`

Expected: missing watch module/options.

- [ ] **Step 4: Implement watch reader and CLI routing**

Use a byte/text buffer that emits only newline-terminated JSON objects. Resolve latest by sorted run directory name. Validate event schema, apply level/task filters, and sleep only while following. Construct a renderer directly so replay does not re-persist events.

In `cli.main`, print `_print(result)` for orchestrate only in quiet mode. JSONL/human rely entirely on renderer output. Preserve existing exit-code rules.

- [ ] **Step 5: Verify GREEN**

Run: `python3 -m unittest tests.deterministic.test_watch tests.orchestration.test_orchestrate_cli -v`

Expected: all format and watch tests pass.

- [ ] **Step 6: Sync CodeGraph and commit**

```bash
codegraph sync .
git add proofloop_core/watch.py proofloop_core/cli.py tests/deterministic/test_watch.py tests/orchestration/test_orchestrate_cli.py
git commit -m "feat: add live CLI formats and event watch"
```

---

### Task 7: Host Skill Integration and Full Verification

**Files:**
- Modify: `skills/proofloop/SKILL.md`
- Modify: `proofloop_core/hosts.py`
- Modify: `tests/deterministic/test_host_adapters.py`
- Modify: `tests/deterministic/test_package.py`
- Modify: `README.md`
- Modify: `README.ko.md`

**Interfaces:**
- Packaged entry skills invoke public `orchestrate --output-format human --verbosity info --color auto`.
- Antigravity generated workflow follows the same command contract.

- [ ] **Step 1: Write failing generated-package assertions**

```python
self.assertIn("--output-format human", text)
self.assertIn("--verbosity info", text)
self.assertIn("--color auto", text)
self.assertNotIn("invoke-role", text)
self.assertNotIn("tests passed", text.lower())
```

Apply assertions to generated Codex, Antigravity, and Claude entry files.

- [ ] **Step 2: Run and verify RED**

Run: `python3 -m unittest tests.deterministic.test_host_adapters tests.deterministic.test_package -v`

Expected: built entry skills lack one or more visibility flags.

- [ ] **Step 3: Update shared skill and generated workflow source**

Make the shared skill create/read a request file and invoke exactly the public orchestrate command with the installed host placeholder and human flags. Remove any instruction to narrate synthetic internal status. Update `antigravity_workflow()` to use the same flags.

- [ ] **Step 4: Document public usage**

Add concise examples for human, JSONL, quiet, and watch to both READMEs. State that requested-only model evidence is unproven and that raw logs remain under the run directory.

- [ ] **Step 5: Run focused package tests GREEN**

Run: `python3 -m unittest tests.deterministic.test_host_adapters tests.deterministic.test_package -v`

Expected: all generated adapter assertions pass.

- [ ] **Step 6: Run CodeGraph affected tests and full deterministic suite**

```bash
codegraph sync .
codegraph affected -p . proofloop_core/events.py proofloop_core/process_runner.py proofloop_core/host_runner.py proofloop_core/checks.py proofloop_core/orchestrator.py proofloop_core/cli.py
python3 -m unittest discover -s tests -v
python3 scripts/validate_package.py
git diff --check
```

Expected: every test passes, package validation exits 0, and `git diff --check` prints nothing.

- [ ] **Step 7: Commit completed integration**

```bash
git add skills/proofloop/SKILL.md proofloop_core/hosts.py tests/deterministic/test_host_adapters.py tests/deterministic/test_package.py README.md README.ko.md
git commit -m "feat: expose ProofLoop live execution visibility"
```

---

## Plan Self-Review Result

- Spec coverage: all approved CLI phases 1-7 are assigned to Tasks 1-7; dashboard/SSE remain excluded.
- Type consistency: emitter, runner, parser, orchestrator, and watch signatures are defined once and reused by later tasks.
- Compatibility: quiet default, existing return/report shapes, and truth artifacts have explicit regression tests.
- Placeholders: no deferred implementation or unspecified error-handling steps remain.
