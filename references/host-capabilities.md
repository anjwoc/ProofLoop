# Host capability modes

## Claude Code

- Declared mode: `NATIVE_MODEL_ROUTING`
- Roles: Opus planner, Haiku fast implementer, Sonnet recovery, Fable reviewer
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

## Antigravity

### Interactive workflow

- Mode: `ROLE_ROUTING_ONLY`
- The workflow separates planner, implementer, recovery, and reviewer contexts.
- It must not claim cross-model switching because a public enforceable per-role model binding and resolved-model trace are not assumed.

### External experimental role sessions

- Mode label: `EXTERNAL_MODEL_ROUTING_EXPERIMENTAL`
- Default requested roles:
  - planner/recovery/reviewer: `Gemini 3.1 Pro (High)`
  - fast implementer: `Gemini 3.5 Flash (Low)`
- `CLI_REQUESTED` proves only what ProofLoop asked the CLI to use. It does not prove the resolved model.
- Routing remains `UNPROVEN` unless the CLI output exposes an active model that the trace adapter can observe.

## Generic states

- `NATIVE_MODEL_ROUTING`: host can configure role-specific agents. Observation still requires trace evidence.
- `EXTERNAL_MODEL_ROUTING`: official CLI/API processes are launched per role and their evidence is captured.
- `ROLE_ROUTING_ONLY`: roles are separated, but cross-model routing is not claimed.
- `UNSUPPORTED`: the host cannot provide the required behavior and ProofLoop stops or degrades explicitly.
