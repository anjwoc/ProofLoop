# Antigravity Role-Only Routing Design

## Problem

ProofLoop invokes Antigravity roles with `agy --model <model> -p <prompt>`. The installed `agy 1.0.3` does not define `--model`, so the planner exits with code 2 before processing the prompt. ProofLoop also reports `EXTERNAL_MODEL_ROUTING` and a requested Gemini model even though the CLI cannot accept that request.

## Evidence

- The failed invocation artifact contains `agy --model "Gemini 3.1 Pro (High)" -p ...`.
- `agy --help` exposes print, prompt, sandbox, and permission flags but no model flag.
- The Go reference at `/Users/jcjeong/lab/local-deepwiki/agent/internal/runner/antigravity.go` invokes Antigravity without a model argument. Its Gemini runner, by contrast, owns explicit `--model` handling.

## Decision

Treat Antigravity CLI execution as `ROLE_ROUTING_ONLY`:

1. Do not promote Antigravity capability to `EXTERNAL_MODEL_ROUTING` merely because `agy` exists.
2. Select Antigravity role configuration from `roles`, not `externalRoles`.
3. Invoke `agy -p <prompt>` with the existing opt-in permission bypass flag when configured.
4. Record `requestedModel` as `current-session-model` and `modelEvidence` as `UNAVAILABLE` unless structured host output proves a model.
5. Mark Antigravity trace summaries `ROLE_ROUTING_ONLY`, so truth evaluation does not claim or require cross-model routing.
6. Publish the same role-only contract from the adapter build, installer result, and doctor output; do not advertise inactive external model routing.
7. Remove the unsupported Antigravity `externalMode` and `externalRoles` configuration so future code cannot accidentally reactivate it.

Codex and Claude Code retain their existing external model arguments and evidence behavior.

## Alternatives Rejected

- Always fail when model selection is unavailable: honest but makes supported role-only Antigravity execution unusable.
- Parse `agy --help` and conditionally enable `--model`: adds a speculative capability not present in the installed CLI or reference implementation.
- Route Antigravity through the separate Gemini CLI: changes the selected host and its permission/session behavior.

## Verification

- A fake `agy` that rejects `--model` must complete a role invocation.
- Invocation artifacts must contain no model flag and must report role-only/unavailable model evidence.
- Built and installed capability metadata must report `ROLE_ROUTING_ONLY` with `crossModelRouting: false`.
- Antigravity CLI orchestration must complete with `PROVEN` based on checks, diff, and review without a model-routing claim.
- Full deterministic and orchestration tests must remain green.
