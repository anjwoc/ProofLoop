# ProofLoop v0.4.0-alpha Orchestrator Development Report

## Goal

Make `/proofloop` or the host-native equivalent start the complete loop without requiring the user or coordinator model to run internal role, attempt, or verification commands.

## Implemented

1. `proofloop-core orchestrate` creates and owns the run.
2. The kernel selects direct, planned, or high-risk mutation strategies.
3. Host adapters launch isolated planner, implementer, recovery, and reviewer processes.
4. The kernel, not the model, runs checks and diff guards.
5. Objective failure evidence drives retry, recovery, replan, or blocked decisions.
6. Review findings can cause one bounded recovery-and-re-review cycle.
7. The final truth report combines command, diff, review, model-trace, claim, and simplicity evidence.
8. Host entry skills contain only one bootstrap command.

## Failures found during implementation

- Python cache files created by tests were initially counted as new product files, causing false anti-bloat failures. The diff scanner now excludes ephemeral cache artifacts while retaining actual untracked source files.
- The old Antigravity live runner fabricated a role-only trace summary when none existed. That fallback was removed.
- Antigravity permission bypass was enabled by default. It is now disabled unless `PROOFLOOP_ANTIGRAVITY_BYPASS_PERMISSIONS=1` is explicitly set.
- Repository analysis did not have a proven output contract. It now blocks instead of falling back to a fabricated analysis.

## Local evidence

- 49 discovered tests.
- All 49 passed when executed by module groups.
- Automatic normal loop, fast retry/recovery, review repair, missing-plan rejection, and read-only-role mutation rejection passed.
- Real child-process fixtures passed for Codex normal, Codex recovery, and Antigravity normal paths.

## Evidence classification

```text
Automatic kernel: SIMULATED_PROVEN
Fake host processes: SIMULATED_HOST_E2E_PROVEN
Authenticated Codex/Antigravity execution: UNPROVEN
Overall release: FAIL
```

No simulated result is presented as authenticated live evidence.
