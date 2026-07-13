---
name: proofloop-planning
description: Create a bounded, evidence-backed and minimal implementation plan for a non-trivial coding request. Use a deep planner before production edits. Produces small task briefs with exact scope, change budgets, required commands, prohibited changes, and escalation conditions.
---

# ProofLoop Planning

Use a deep planning model. Do not edit production files.

## Repository context

For repository-wide planning or analysis, run:

```bash
$HOME/.proofloop/bin/proofloop-core ensure-context --repo . --output <run-dir>/repository-context.json
```

A `BLOCKED` result stops broad planning. For a clearly bounded small edit, native scoped search may be used and this exception must be stated.

## Minimum-solution ladder

After understanding the actual flow, stop at the first rung that satisfies the request safely:

1. `SKIP_NOT_NEEDED`
2. `REUSE_EXISTING`
3. `STDLIB`
4. `PLATFORM_NATIVE`
5. `INSTALLED_DEPENDENCY`
6. `DIRECT_CHANGE`
7. `MINIMAL_NEW_CODE`

Record the selected rung, alternatives considered, and why earlier rungs were insufficient. Do not add a dependency, abstraction, configuration layer, generic framework, migration path, or documentation set unless acceptance criteria require it.

## Process

1. Restate requested behavior and identify assumptions.
2. Inspect only repository context needed to locate boundaries and conventions.
3. Identify invariants, failure modes, public contracts, and existing tests.
4. Select the minimum-solution rung.
5. Split work into independently verifiable task briefs.
6. Set a strict change budget for files, added lines, new files, and dependency changes.
7. Assign deterministic commands to each brief.
8. Mark conditions that require return to the planner.
9. List non-goals and deferred ideas; they are not implementation work.

## Required task brief

Create one JSON file per task using `references/task-brief.md`.

Each task must contain:

- `id`
- `objective`
- `allowedPaths`
- `protectedPaths`
- `requiredChecks`
- `changeBudget`
- `simplicity.selectedRung`
- `simplicity.rationale`
- `simplicity.considered`
- retry budgets
- invariants and escalation conditions in the human-readable plan

A fast implementer must be able to execute the brief without choosing architecture, public API, schema, dependency policy, or broader cleanup.

## Reject the plan when

- acceptance cannot be tested;
- scope or change budget is unbounded;
- the baseline is unknown;
- requirements conflict;
- an earlier simplicity rung was skipped without evidence;
- a risky contract decision is hidden inside an implementation task.
