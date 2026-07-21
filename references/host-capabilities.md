# Host capability modes

## Claude Code

- Declared mode: `NATIVE_MODEL_ROUTING`
- Roles: Opus planner/reviewer, Haiku fast implementer, Sonnet recovery
- Truth requirement: the host hook must capture the resolved model before cross-model routing is `OBSERVED`.

## Codex

- Declared mode: `NATIVE_MODEL_ROUTING`
- Roles:
  - `proofloop_planner_deep`: `gpt-5.6`, high reasoning, read-only
  - `proofloop_implementer_fast`: `gpt-5.6-terra`, medium reasoning, workspace-write
  - `proofloop_implementer_recovery`: `gpt-5.6`, high reasoning, workspace-write
  - `proofloop_reviewer_deep`: `gpt-5.6`, high reasoning, read-only
- Plugin hooks record `SubagentStop` agent type, transcript path, and the active/observed model when the host exposes it.
- Configuration alone is `CONFIGURED_UNPROVEN`; only trace evidence upgrades routing to observed.

## AGY CLI (Antigravity)

- Mode: `EXTERNAL_MODEL_ROUTING`
- Default requested roles:
  - explorer/fast implementer: `gemini-3.5-flash-medium`
  - planner/recovery/reviewer: `gemini-3.1-pro-high`
- The process boundary uses AGY's proven display labels (for example,
  `Gemini 3.5 Flash (Medium)`) while traces retain canonical routing IDs.
- `CLI_REQUESTED_ONLY` proves the exact CLI request, not the provider's resolved model.
  AGY 1.1.5 does not emit resolved-model metadata, so routing must remain
  `UNPROVEN` until the provider exposes it.
- A silent AGY invocation is terminated after 90 seconds without initial
  stdout/stderr (`PROOFLOOP_AGY_INITIAL_OUTPUT_TIMEOUT_SECONDS` can override
  this). It produces `HOST_INITIAL_OUTPUT_TIMEOUT` and a truthful `BLOCKED`
  terminal result rather than consuming the entire role budget.
- The installed AGY entry skill starts its authorized child roles with
  `PROOFLOOP_AGY_BYPASS_PERMISSIONS=1`, which produces Goalng-compatible
  `agy --dangerously-skip-permissions --prompt ... --model ...` calls. This is
  scoped to the detached ProofLoop child process, not a global AGY setting.

## Conversation relay

- Every host entry skill starts one parent-owned background run and repeatedly
  calls `proofloop-core relay --relay-dir <path> --wait-seconds 3` in the same
  conversation.
- The command prints every newly appended observable event exactly once:
  phase/role, requested and observed model evidence, agent tool or message
  events when the host exposes them, checks, recovery, review, budget, and
  the Truth verdict.
- A CLI subprocess cannot asynchronously append text to Codex, Claude Code,
  or AGY chat by itself. Repeated short host tool calls are therefore the
  portable way to deliver live logs without a separate TUI or web server.
- Private provider reasoning and raw provider transcripts are excluded from
  the relay and durable user-facing logs.

## Generic states

- `NATIVE_MODEL_ROUTING`: host can configure role-specific agents. Observation still requires trace evidence.
- `EXTERNAL_MODEL_ROUTING`: official CLI/API processes are launched per role and their evidence is captured.
- `ROLE_ROUTING_ONLY`: roles are separated, but cross-model routing is not claimed.
- `UNSUPPORTED`: the host cannot provide the required behavior and ProofLoop stops or degrades explicitly.
