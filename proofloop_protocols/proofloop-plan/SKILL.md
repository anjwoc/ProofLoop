---
name: proofloop-plan
description: Convert an approved ProofLoop intent and design into bounded tracer-bullet task briefs with exact paths, interfaces, checks, proof seams, budgets, dependencies, and escalation conditions. Use internally for T2 or T3 work and replanning after validated design changes.
---

# ProofLoop Plan

## Core principle

Make every task independently executable and verifiable inside one context. A plan that leaves discovery to the implementer is not executable.

## Authority boundary

- Read the intent, selected design, repository evidence, and proof graph.
- Inspect targeted files and commands without mutating source.
- Write only plan and task-brief artifacts.
- Do not invent scope, close behavior obligations, or use planning to authorize risky actions.

## Preconditions

Confirm that the plan has:

- stable acceptance criteria
- a selected design or a justified direct path
- known repository entry points and tests
- explicit protected paths and risk surfaces

Escalate rather than planning around a missing product or architecture decision.

## Procedure

1. Map every acceptance criterion to at least one task and later check.
2. Divide work into end-to-end tracer bullets, not horizontal layer batches.
3. Keep each task small enough to implement and verify in one agent context.
4. Name exact create/modify/test paths and protected paths.
5. State required interfaces, signatures, schemas, or observable behavior.
6. Select the lowest solution rung that can satisfy the task.
7. Specify focused checks as argv, then the necessary regression scope.
8. Attach proof obligations and evidence expectations to the task.
9. Set change, token, time, invocation, and retry budgets.
10. Order dependencies and mark genuinely independent work only when artifacts do not conflict.
11. Define stop and escalation conditions before implementation begins.
12. Review coverage, placeholder text, and cross-task consistency.

## Task brief requirements

Every task must state:

- goal and linked criterion IDs
- allowed and protected paths
- exact files to create, modify, or test
- interfaces and observable behavior
- selected minimum-solution rung
- prerequisite artifacts or tasks
- focused and regression checks
- proof obligations and required authority
- change and execution budgets
- escalation conditions

Use one to four tasks by default. Add tasks only when they create a real proof seam or isolate conflicting change surfaces.

## Checks

Verify commands exist or are derivable from repository configuration. Store commands as argv arrays without shell interpolation. Do not use placeholders such as `<test command>`, “run relevant tests,” or “update as needed.”

If a required verifier does not exist, plan its smallest safe addition or mark the obligation unverified; do not pretend an unavailable check will run.

## Scope and sequencing

Prefer this sequence:

1. establish or identify the failing/acceptance check
2. implement the smallest vertical behavior slice
3. integrate at the real boundary
4. run focused checks
5. run proportionate regression checks

Do not schedule dependent integration before its contract exists. Do not split tightly coupled edits merely to create more tasks.

## Stop and escalate

Return `PLAN_NOT_EXECUTABLE` or `SCOPE_UNKNOWN` when:

- exact target paths cannot be located
- a command or verifier cannot be established
- one task exceeds the allowed context or change budget
- requirements have no task coverage
- the design and repository interfaces disagree
- implementation would require protected-path mutation

## Anti-patterns

- Do not write “add validation” without the rule, location, and expected failure.
- Do not repeat the design document instead of producing actions.
- Do not put all implementation into one catch-all task.
- Do not create a task per file when the behavior is one vertical slice.
- Do not prescribe speculative cleanup after acceptance is met.
- Do not weaken tests or increase budgets as a default recovery strategy.

## Example

Weak step: “Update API and tests.”

Executable task:

- modify `routes/report.py` and `services/export.py`
- preserve the existing JSON route
- add `GET /reports/{id}/export.csv`
- test active-filter propagation in `tests/api/test_report_export.py`
- run `python -m pytest tests/api/test_report_export.py -q`
- stop if export-column policy remains unknown

## Completion checklist

- [ ] Every criterion maps to a task and check.
- [ ] Every task names exact paths and interfaces.
- [ ] Commands exist and contain no placeholders.
- [ ] Dependencies and proof seams are explicit.
- [ ] Mutation, token, time, and retry budgets are bounded.
- [ ] Protected paths and escalation conditions are recorded.
- [ ] Cross-task names and signatures are consistent.
- [ ] No speculative work remains after the requested outcome.
