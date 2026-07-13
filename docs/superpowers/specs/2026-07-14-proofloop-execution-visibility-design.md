# ProofLoop Execution Visibility Design

**Date:** 2026-07-14
**Status:** Approved
**Scope:** CLI phases 1-7 from the execution-visibility PRD; the web dashboard and SSE server are excluded.

## 1. Objective

Make a `/proofloop` or `$proofloop` run observable in the host agent UI without asking the user to open artifacts in another terminal. The visible stream must report the current phase, role, requested and observed models, attempt count, verification result, failure reason, routing decision, review result, and final truth state.

The orchestrator is the only authority allowed to create these status events. Host prose such as “tests passed” or “the recovery model is active” never changes ProofLoop state. Events must be based on actual orchestration state, process results, parsed host evidence, deterministic check reports, repair decisions, review artifacts, and truth artifacts.

## 2. Goals

- Persist every structured execution event to `.proofloop/runs/<run-id>/events.jsonl`.
- Render the exact same event object immediately to stdout in `human` or `jsonl` mode.
- Keep `requestedModel`, `observedModel`, and `evidenceLevel` distinct.
- Stream host and verification processes without stdout/stderr deadlocks.
- Preserve complete raw stdout and stderr artifacts while limiting default screen noise.
- Cover normal execution, retry, recovery, replan, review repair, failure, blocking, and truth completion.
- Support Codex, Antigravity, and Claude Code parsers without guessing from ambiguous prose.
- Add `watch` so a separate terminal can replay and follow the same event stream.
- Update packaged host entry skills to invoke `orchestrate --output-format human` instead of exposing internal role commands.
- Preserve existing truth, check, diff, invocation, and trace artifacts during the migration.

## 3. Non-goals

- No web dashboard, HTTP server, WebSocket, or SSE endpoint.
- No replacement of deterministic truth evaluation with event text.
- No inference of a resolved model from configuration alone.
- No attempt to display every host log line at the default verbosity.
- No removal of existing compatibility artifacts in this release.

## 4. Chosen Approach

Use a compatibility-preserving event backbone.

`EventEmitter` becomes the sole source for `events.jsonl` and all live UI output. The existing artifact graph remains available to the truth gate and existing consumers. Orchestrator decisions continue to be made from real values and artifacts, then generate standard events. This avoids a high-risk simultaneous rewrite of truth evaluation while satisfying the requirement that stored events and visible events are identical.

Rejected alternatives:

- A complete event-sourcing rewrite would make every legacy artifact a projection immediately. It is structurally pure but expands the blast radius to truth evaluation and all existing consumers.
- A wrapper around current stdout would be fast but could not reliably expose internal retry reasons, real exit codes, or routing evidence and would violate the orchestrator-authority rule.

## 5. Architecture

```text
proofloop-core CLI
  └── EventEmitter
      ├── EventStore → events.jsonl
      └── Renderer → human | jsonl | quiet
           ↑
ProofLoopOrchestrator
  ├── deterministic state and repair decisions
  ├── run_checks
  │   └── ProcessRunner
  └── ExternalCLIAdapter
      └── ProcessRunner
          ├── raw stdout/stderr artifacts
          └── HostOutputParser
              └── NormalizedHostEvent → EventEmitter

proofloop-core watch
  └── EventReader → Renderer
```

### 5.1 File boundaries

Create or expand focused modules with these responsibilities:

- `proofloop_core/events.py`: event schema construction, sequence recovery, thread-safe persistence, immediate rendering dispatch, and corrupt-tail handling.
- `proofloop_core/renderers/__init__.py`: renderer protocol and renderer selection.
- `proofloop_core/renderers/human.py`: human formatting, verbosity filtering, terminal color policy, and final summary.
- `proofloop_core/renderers/jsonl.py`: compact one-event-per-line serialization.
- `proofloop_core/renderers/quiet.py`: no intermediate rendering; final backward-compatible JSON result only.
- `proofloop_core/process_runner.py`: concurrent stdout/stderr readers, queue-driven delivery, raw logs, timeout, termination, and exit result.
- `proofloop_core/output_parsers/base.py`: `NormalizedHostEvent` and `HostOutputParser` protocol.
- `proofloop_core/output_parsers/codex.py`: Codex JSONL signals.
- `proofloop_core/output_parsers/antigravity.py`: known Antigravity structured or exact CLI signals.
- `proofloop_core/output_parsers/claude.py`: Claude stream JSON signals.
- `proofloop_core/watch.py`: run resolution, JSONL tailing, filtering, replay, and partial-line handling.
- `proofloop_core/host_runner.py`: command construction and conversion from `ProcessRunner` results into invocation and model-trace artifacts.
- `proofloop_core/checks.py`: deterministic check execution through `ProcessRunner` and check event emission.
- `proofloop_core/orchestrator.py`: map actual state transitions and artifacts to standard events.
- `proofloop_core/cli.py`: output/verbosity/color options and the `watch` command.
- `skills/proofloop/SKILL.md` and host package builders: use the public human-streaming orchestrate command.

Existing public call sites remain usable by making emitter/parser arguments optional where direct unit callers do not need live output.

## 6. Event Contract

Every event contains:

```json
{
  "schemaVersion": "1",
  "eventId": "evt-000014",
  "runId": "20260714T103122-acde1234",
  "timestamp": "2026-07-14T10:31:54.213+09:00",
  "sequence": 14,
  "type": "role.started",
  "level": "info",
  "phase": "EXECUTE",
  "taskId": "TASK-001",
  "message": "Fast implementer started.",
  "data": {}
}
```

`taskId` is optional; all other fields are required. `level` is one of `debug`, `info`, `warning`, or `error`. `phase` uses stable uppercase orchestration phases. `data` is always an object.

`EventEmitter.emit()` performs one locked operation:

1. Increment sequence.
2. Build a timezone-aware ISO 8601 timestamp and event ID.
3. Serialize the complete event.
4. Append it to `events.jsonl`, add a newline, and flush.
5. Pass the in-memory event object to the selected renderer.
6. Flush the output stream.

On restart, the emitter recovers the last valid sequence. An incomplete final fragment is copied to a corrupt-tail artifact and removed from the active JSONL before append. A malformed complete line in the middle or end of the stream raises an event-store corruption error rather than silently discarding evidence.

The event families and names are those listed in the PRD: run, capability, strategy, context, role, task, check/diff guard, repair/progress, review, truth/claim, and budget.

## 7. Rendering and CLI Semantics

`orchestrate` gains:

```text
--output-format human|jsonl|quiet
--verbosity info|verbose|debug
--color auto|always|never
```

For backward compatibility, `quiet` is the default for direct CLI callers and prints the existing final JSON result. Packaged host skills always pass `--output-format human --verbosity info --color auto`.

- `human`: renders prefixed status lines and a final summary; it never appends a separate machine JSON document.
- `jsonl`: renders every event as compact JSONL; it never appends a pretty final JSON document.
- `quiet`: stores all events but renders no intermediate event; after orchestration, the CLI prints the existing final result JSON.

Human verbosity:

- `info`: phase, role, requested/observed model, verification verdict, repair transition, review verdict/finding summary, and truth verdict.
- `verbose`: adds commands, changed-file/line counts, failed test names, review findings, and evidence level.
- `debug`: adds invocation IDs, artifact paths, host commands, raw state transitions, and check output lines.

Color is enabled only when policy permits it and the stream is a terminal. Snapshot tests use `never`.

## 8. Streaming Process Execution

`ProcessRunner.run()` starts `subprocess.Popen` with text pipes and line buffering. One daemon reader thread handles stdout and one handles stderr. Each reader writes every line to its raw artifact, flushes it, and places `(stream, line)` into a shared queue. Each reader places a distinct sentinel when it reaches EOF. The main loop drains the queue and invokes the line callback until both sentinels and process termination have been observed.

Timeout behavior:

1. Mark the result timed out.
2. Terminate the process or process group.
3. Wait for a bounded grace interval.
4. Kill if still running.
5. Drain both pipes and preserve exit evidence.
6. Report ProofLoop exit code `124` with `timedOut: true`.

The returned `ProcessResult` includes command, cwd, exit code, timeout/cancel flags, duration, and stdout/stderr references. It does not keep complete output in memory.

## 9. Host Output Parsing and Model Evidence

Parsers consume one `(stream, line)` pair and return zero or more normalized host events. They prefer host JSON fields and exact documented event markers. Unknown and ambiguous lines are written only to raw logs.

Evidence levels are:

- `HOST_RESOLVED`: an explicit host-resolved model field or hook trace.
- `HOST_OUTPUT`: a model field in trusted structured host output.
- `CLI_REQUESTED_ONLY`: only the command/configured request is known.
- `CONFIG_ONLY`: configuration is known but no matching invocation evidence exists.
- `UNAVAILABLE`: no usable evidence exists.

A free-form assistant sentence is never sufficient to produce `HOST_RESOLVED`, a check verdict, a review verdict, or a truth verdict. Parser exceptions do not abort the child process; they emit one `capability.degraded` event per invocation and lower evidence to `UNAVAILABLE`.

## 10. Orchestrator Event Flow

The orchestrator emits only after it possesses the corresponding state or evidence.

```text
run.started
  capability.detected|degraded
  strategy.selected
  context.started → context.ready|failed
  task.created...
  role.queued → role.started
    role.model_observed (including an explicit unobserved evidence level)
  role.completed|failed|cancelled
  task.started
    attempt.recorded
    check.started → check.output* → check.completed|failed
    diff_guard.completed|failed
    progress.detected|stalled
    retry.scheduled|recovery.scheduled|replan.scheduled
  task.completed|failed
  review.started → review.completed|fix_required|overbuilt
  claim.supported|unproven|contradicted
  truth.completed
run.completed|failed|blocked
```

Repair events are created from the actual `decide_next()` result and include reason code, fingerprint, attempt count, from/to role, requested-model change, and measured progress. Review events are created from the machine-readable review artifact. Truth events are created from the truth report. Host prose cannot override any of these values.

Legacy `transitions.jsonl`, `invocations.jsonl`, `attempts.jsonl`, check reports, diff reports, model traces, assurance reports, and truth reports remain available as compatibility and proof artifacts. They are not read by human or watch renderers.

## 11. Watch Command

Supported forms:

```text
proofloop-core watch --run latest --repo .
proofloop-core watch --run-dir .proofloop/runs/<run-id>
```

Options:

```text
--format human|jsonl
--verbosity info|verbose|debug
--task TASK-001
--level debug|info|warning|error
--color auto|always|never
--no-follow
```

The reader replays complete existing lines, then follows new lines unless `--no-follow` is given. It waits when the final line is incomplete. Filters are applied to parsed event objects before rendering and never alter the stored stream.

## 12. Host Skill and Package Integration

The shared ProofLoop entry skill and each specialized packaged copy invoke one public command:

```text
$HOME/.proofloop/bin/proofloop-core orchestrate \
  --host <installed-host> \
  --repo . \
  --request-file <request-file> \
  --output-format human \
  --verbosity info \
  --color auto
```

The skill does not narrate synthetic planner, implementation, verification, recovery, review, or truth status. It may explain user input or the final result, but system state lines come from the orchestrator stream. Internal `invoke-role` commands remain implementation details.

The Codex, Antigravity, and Claude package builders continue specializing the host placeholder and are tested against the final generated skill content.

## 13. Error Handling

- Event-store append or flush failure is fatal because ProofLoop cannot prove display/log consistency.
- A closed output consumer (`BrokenPipeError`) disables rendering while event persistence continues.
- Host nonzero exit, check nonzero exit, timeout, cancellation, parser degradation, and budget exhaustion use distinct event types and reason codes.
- A false host success sentence never overrides the real process or check exit code.
- Raw stdout and stderr are preserved even when parsing fails or a process times out.
- Renderer formatting errors cannot change orchestrator state or truth. They are surfaced as execution visibility failures.
- Watch reports malformed complete JSONL lines with line numbers and does not invent replacement events.

## 14. Testing Strategy

All behavior changes follow red-green-refactor TDD using the repository's `unittest` conventions.

### Event emitter

- Monotonic sequence and event IDs.
- Valid JSONL and required fields.
- Concurrent emit serialization.
- Immediate file and stream flush.
- Restart append and incomplete-tail recovery.
- Complete malformed-line rejection.

### Renderers

- Snapshot-like exact strings for normal, retry, recovery, review, failure, and final truth.
- `UNPROVEN` routing when no model is observed.
- Info/verbose/debug filtering.
- Color auto/always/never.
- Human, JSONL, and quiet streams do not mix formats.

### Process runner

- A fixture that prints at intervals proves lines arrive before process exit.
- Simultaneous large stdout/stderr proves no deadlock.
- Exit code preservation.
- Timeout terminate/kill and pipe drain.
- Raw log completeness.

### Host parsers

- Codex, Antigravity, and Claude structured fixtures.
- Model observation and evidence classification.
- Role start/completion, rate limit, permission request, and host error.
- Unknown prose produces no normalized state event.

### Orchestration and CLI

- Normal run: plan, execute, verify, review, truth proven.
- Fast retry followed by pass.
- Repeated fingerprint followed by recovery escalation.
- Review repair loop.
- Requested-only model produces an unproven routing verdict.
- Host text claiming tests passed cannot beat an actual check exit code of 1.
- Human, JSONL, and quiet CLI contracts.
- Watch latest/run-dir selection, filtering, replay, follow, and partial line.
- Built host adapters contain the public human-streaming command and do not expose internal progress narration.

Deterministic fake-host E2E is the required gate. Live host validation is optional because availability, credentials, and provider behavior are external to this repository.

## 15. Migration and Compatibility

- Existing APIs gain optional emitter or runner parameters rather than forcing unrelated direct callers to construct UI objects.
- Existing final JSON behavior remains available through the default quiet mode.
- Existing proof artifacts and truth calculations remain intact.
- New events use schema version `1`; schema changes require an explicit later version.
- The implementation may replace internal `subprocess.run(capture_output=True)` calls in `host_runner.py` and `checks.py`, but direct function return shapes remain compatible unless tests document an intentional addition.

## 16. Development Workflow Constraint

Repository exploration during implementation uses the existing CodeGraph index first (`codegraph query`, `explore`, `node`, `callers`, `callees`, `impact`, and `affected`). After every source or test edit batch, run `codegraph sync .` before further structural exploration. Use CodeGraph affected-test results to narrow fast checks, followed by the full deterministic suite before completion.

## 17. Acceptance Criteria

The feature is complete when:

1. A host skill run immediately displays `run.started` in human form.
2. Every role start and completion is visible in real time.
3. Requested and observed models and their evidence level remain distinct.
4. Verification start, relevant output, and actual result are streamed.
5. Retry, recovery, and replan reasons are visible and evidence-backed.
6. Review verdicts and repair loops are visible.
7. The final truth status is the last authoritative status.
8. Screen output and `events.jsonl` derive from the same event objects.
9. Host natural language cannot change deterministic state.
10. Users do not need to inspect internal role invocation commands.
11. All three host adapters use the public human-streaming orchestrate command.
12. `watch` replays and follows the same stored event stream.
13. Deterministic tests pass without requiring real provider credentials.

## 18. Implementation Order

1. Event schema, store, emitter, and format renderers.
2. Streaming process runner.
3. Deterministic check streaming.
4. Codex, Antigravity, and Claude parsers plus host runner integration.
5. Orchestrator event mapping for all state and repair paths.
6. CLI output modes and host skill/package integration.
7. Watch replay/follow command.
8. Full deterministic and simulated-host E2E verification.
