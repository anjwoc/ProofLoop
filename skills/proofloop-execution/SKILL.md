---
name: proofloop-execution
description: Execute one approved ProofLoop task brief with a fresh fast implementer, TDD for behavior changes, deterministic command checks, a diff guard, and a strict change budget. Use only after planning or for a direct verified change.
---

# ProofLoop Execution

Execute exactly one task brief.

## Implementer handoff

Give the fresh fast implementer only:

- the task brief;
- relevant source and tests;
- current deterministic evidence;
- the last failed diff when retrying.

Do not pass the planner's full conversation or a previous implementer's speculation.

## Minimality rule

Use the task brief's selected simplicity rung. Reuse before adding. Do not add speculative abstractions, generic helpers, optional modes, unrelated refactors, new dependencies, or extra documentation. Stop changing code as soon as acceptance and required checks pass.

Safety, validation, security, data integrity, concurrency correctness, accessibility, and required tests are never removed to meet a size budget. If the approved budget is genuinely insufficient, return to the planner instead of silently expanding it.

## Behavior changes

Use TDD:

1. write or identify a test that fails for the missing behavior;
2. confirm the failure;
3. make the minimum production change;
4. run required checks;
5. refactor only while checks stay green and the change becomes smaller or clearer.

## Deterministic checks

Run:

```bash
$HOME/.proofloop/bin/proofloop-core run-checks \
  --task <task.json> \
  --repo . \
  --output <run-dir>/checks

$HOME/.proofloop/bin/proofloop-core diff-guard \
  --task <task.json> \
  --repo . \
  --baseline <baseline-sha> \
  --output <run-dir>/diff-guard.json
```

The diff guard enforces scope, test integrity, changed-file count, added-line count, new-file count, and dependency-change policy. The implementer's summary cannot replace these commands.

Then record the attempt:

```bash
$HOME/.proofloop/bin/proofloop-core record-attempt \
  --task <task.json> \
  --run-dir <run-dir> \
  --role implementer_fast
```

Read `<run-dir>/next-action.json`; do not choose the next action from intuition.

## Result

- Both gates pass: send diff and evidence to review.
- A gate fails: use `proofloop-repair`.
- Contract, safety, or legitimate budget conflict: stop implementation and return to the deep planner.
