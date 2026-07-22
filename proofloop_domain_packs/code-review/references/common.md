# Code Review Proof Seams

Review base-to-head artifacts: the diff, intent, check outputs, and surrounding context. Findings require exact location, trigger, mechanism, consequence, and a bounded correction.

## Severity matrix

| Severity | Meaning | Example |
|---|---|---|
| **P0** | Production-breaking or data-loss path, reachable in normal use | Auth bypass, foreign key deleted without cascade, unhandled exception returns 200 |
| **P1** | High-impact, reachable under specific but credible conditions | Race condition in concurrent writes, silent rollback ignored, secret logged under load |
| **P2** | Real bounded defect — won't crash but incorrect behavior | Off-by-one in pagination, missing validation on one field, N+1 in a list endpoint |
| **P3** | Low-impact but actionable | Unused import left in, misleading variable name, test asserts return value not behavior |
| **Gap** | Missing evidence, not a product bug | No test for the error path, coverage unclear |
| **Opt** | Optional improvement, no correctness impact | Rename for clarity, extract helper |

**Rule**: `P0/P1` requires a fully reachable call path shown in the finding. If you can't show the path, it's `P2` or lower, or a `Gap`.

## Finding template

```
[P1] orders/service.py:47-52 — Retry duplicates non-idempotent charge

Trigger: Network timeout after charge is committed but before response returned.
Mechanism: `charge_card()` is called inside the retry loop without idempotency key.
Consequence: Customer charged twice; second charge not in order record.
Correction: Pass `idempotency_key=order.id` to `charge_card()`, or move charge
  outside the retry loop and retry only the response-recording step.
```

## What to check in every diff

### Intent alignment
- Does the change implement what the intent says and nothing more?
- Are there files changed that aren't mentioned in the task?

### Control and data flow
- Trace new/changed code from entry point to response or side effect
- Can the new code path be reached by an unauthenticated or low-privilege caller?
- Does error handling preserve the existing status/code/message contract?

### State and persistence
- Is there a transaction boundary? What rolls back on failure?
- Can a retry produce a duplicate non-idempotent effect?
- Does a schema change have a migration? Does it break existing callers?

### Tests
- Is there a test for the success path? For at least one failure path?
- Does the test actually fail when the behavior is reverted? (Not just "there is a test")
- Are mocks stopping at the correct boundary, or mocking the thing under test?

## What NOT to do

- Do not report "this could be slow" without showing the code path and load condition
- Do not reject code for stylistic preference that has no correctness impact
- Do not treat a small diff as safe or a large diff as suspicious
- Do not request a refactor that is unrelated to the change under review
- Do not re-run linter output as manual findings — it's already in CI
