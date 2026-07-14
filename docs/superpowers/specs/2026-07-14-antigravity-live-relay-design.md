# Antigravity Live Relay Design

## Problem

ProofLoop starts Antigravity roles with an inherited stdin and only renders host output that a structured parser recognizes. In an Antigravity agent tool call, the inherited stdin remains open, so `agy -p <prompt>` waits for EOF indefinitely. While it waits, ProofLoop emits no heartbeat and suppresses unstructured host output, making the coordinator appear frozen after `role.started`.

The failed run `20260714T025245-4de027e8` proved both symptoms: PID `81972` remained blocked in `read()`, and its invocation logs stayed empty while the event stream stopped at `planner_deep started`.

## Decisions

### Deterministic stdin ownership

- Make `ProcessRunner` own every child stdin.
- Connect stdin to `/dev/null` when no payload is provided.
- When a payload is provided, write it through a dedicated pipe writer and close the pipe to deliver EOF.
- Invoke Antigravity as `agy --prompt ""` and provide the complete role prompt through stdin. This follows the working Go reference at `/Users/jcjeong/lab/local-deepwiki/agent/internal/runner/antigravity.go` and avoids command-line length limits.

### Core live evidence

- Add an optional process heartbeat callback with a five-second production interval.
- Emit `role.progress` with role, attempt, invocation ID, PID, elapsed seconds, and log references.
- Emit bounded `role.output` events for non-empty Antigravity stdout/stderr lines while preserving the complete bytes in invocation log files.
- Render progress and host output at human `info` verbosity so the default `/proofloop` invocation is visibly alive.
- Do not expose the submitted prompt or synthesize activity that was not observed.

### Antigravity coordinator relay

- Generate an Antigravity-specific workflow that launches the orchestrator in a detached background process with stdin closed.
- Redirect the orchestrator stream to a per-run relay log and record its PID.
- Require the coordinator to poll only newly appended relay lines, present them to the user between tool calls, and continue until the process exits.
- Report the final truth status from the generated run without upgrading `UNPROVEN`, `FAILED`, or `BLOCKED`.

Codex and Claude Code retain their foreground entry-skill behavior. The shared process runner receives safer stdin defaults, but only Antigravity uses prompt-over-stdin and raw host-output relay.

## Event Contract

`role.progress` data:

```json
{
  "role": "planner_deep",
  "attempt": null,
  "invocationId": "01-antigravity-planner_deep",
  "processId": 12345,
  "elapsedSeconds": 5.0,
  "stdoutRef": ".../stdout.log",
  "stderrRef": ".../stderr.log"
}
```

`role.output` data adds `stream`, bounded `text`, and `truncated`. Complete output remains available through the referenced logs.

## Error Handling

- A heartbeat or output callback exception terminates the process through the existing callback-failure path.
- A broken stdin pipe after early child exit is non-fatal; other writer errors are surfaced.
- Timeout and cancellation retain exit codes 124 and 130 and continue to terminate the whole child process group.
- The relay workflow checks process liveness and always reads the final truth report after exit.

## Verification

- A process fixture must receive an exact stdin payload followed by EOF.
- A silent process must produce heartbeat callbacks before exit.
- A fake `agy` must receive `--prompt ""`, read the role prompt from stdin, and complete without hanging.
- Antigravity output and heartbeat events must render at `info` and flush immediately.
- The built Antigravity workflow must contain background launch, explicit stdin closure, per-run relay logging, incremental polling, and final truth reporting instructions.
- Existing timeout, cancellation, process-group, model-evidence, orchestration, packaging, and installer tests must remain green.
