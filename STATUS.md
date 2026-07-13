# ProofLoop v0.4.0-alpha status

## Implemented and locally proven

- One-command `proofloop-core orchestrate` kernel for mutation workflows.
- Strategy selection: direct, planned, and high-risk engineering.
- Automatic run creation, Git baseline, task materialization, and state ledger.
- Automatic planner, fast implementer, recovery implementer, and reviewer scheduling.
- Real command execution with exit-code-derived verdicts.
- Diff guard, test-integrity checks, change budgets, and dependency guard.
- Failure fingerprinting and bounded fast → fast → recovery escalation.
- Review repair and re-review loop.
- Claim evidence, hallucination, truth, and anti-bloat gates.
- Thin host-specific `proofloop` entry skills that call only `orchestrate`.
- Safe-by-default Antigravity permission behavior.

## Test evidence labels

- Automatic kernel tests: `SIMULATED_ORCHESTRATION`
- One-command fake Codex/Antigravity child-process tests: `SIMULATED_HOST_E2E`
- Deterministic check/diff/truth tests: local deterministic evidence

These prove the mechanics, not authenticated model execution.

## Still unproven

- Authenticated Codex planner → fast implementer → reviewer routing.
- Authenticated Codex failed checks → retry → recovery routing.
- Authenticated Antigravity requested model versus resolved model.
- Authenticated Antigravity repair loop.
- Claude external orchestrator live E2E.

## Deliberately not implemented

- Repository-analysis-only orchestration. It returns `BLOCKED / ANALYSIS_ORCHESTRATION_NOT_IMPLEMENTED` instead of producing an unverified analysis.

## Release verdict

```text
Overall release: FAIL
```

The release may become `PASS` only after at least one supported host has both an authenticated normal `PROVEN` run and an authenticated recovery `PROVEN` run.
