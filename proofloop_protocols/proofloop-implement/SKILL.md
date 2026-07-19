---
name: proofloop-implement
description: Implement one active ProofLoop task brief as the smallest authorized diff, using repository conventions, focused feedback, protected-path enforcement, and machine-readable attempt evidence. Use internally for initial and recovery implementation at every workload tier.
---

# ProofLoop Implement

## Core principle

Change only what the active task requires, then produce evidence. Passing by weakening the contract is failure.

## Authority boundary

- Read the active task brief, intent, selected design when present, repository context, and current failure evidence.
- Modify only allowed paths within the active worktree.
- Do not change protected tests, acceptance criteria, proof authority, budgets, or Core artifacts.
- Never declare `PROVEN`; report the attempt and let Core execute authoritative gates.

## Preflight

Before editing:

1. Restate the task goal and linked criteria internally.
2. Confirm allowed and protected paths.
3. Inspect the nearest existing implementation and tests.
4. Confirm the focused feedback command.
5. Select the task brief’s minimum-solution rung.
6. Check whether a current failure fingerprint requires a materially different recovery approach.

Return `NEEDS_CONTEXT` when required files, interfaces, or commands are missing.

## Procedure

1. Establish a red signal for changed behavior when practical and required by the task.
2. Make the smallest cohesive edit that can satisfy the criterion.
3. Follow repository-local names, boundaries, error handling, and test style.
4. Avoid new dependencies and abstractions unless the task explicitly justifies them.
5. Run the focused check assigned by the brief.
6. Inspect the actual diff for accidental files, generated noise, secrets, and scope expansion.
7. Run the assigned regression check when the focused signal passes.
8. Record changed paths, commands, outcomes, concerns, and remaining unknowns.

Do not retry the same edit against the same failure fingerprint. A new attempt must change the hypothesis, evidence, or implementation strategy.

## Test discipline

Use test-first behavior when a stable, focused test seam exists. For configuration, generation, or integration surfaces where another deterministic validator is stronger, use that validator as the red/green loop. Do not write a unit test that only mirrors implementation details to satisfy a ritual.

Never:

- delete or skip a failing test without explicit authorization
- broaden an assertion so incorrect behavior passes
- replace an external verifier with a model claim
- edit benchmark or protected evaluator files

## Status contract

Return exactly one semantic status:

- `DONE`: implementation and assigned checks completed
- `DONE_WITH_CONCERNS`: completed but a concrete risk or unknown remains
- `NEEDS_CONTEXT`: missing evidence or contract information prevents safe work
- `BLOCKED`: task cannot be completed within authority or budget

Describe concerns with evidence and impact. Do not label ordinary notes as blockers.

## Stop and escalate

Stop when:

- the necessary edit crosses allowed scope
- acceptance and repository behavior conflict
- a protected path must change
- the same fingerprint repeats without new evidence
- a dependency, migration, deployment, or destructive action lacks authority
- the task exceeds its change, token, time, or invocation budget

Use `SCOPE_VIOLATION`, `CHECK_FAILED`, `REPEATED_FINGERPRINT`, or the most specific contract status.

## Attempt artifact

Record:

- task and invocation identity
- selected solution rung
- hypothesis or implementation intent
- changed paths
- commands and exit outcomes
- failure fingerprint when present
- status and concerns
- evidence artifact references

Report facts from the real diff and command results. Do not summarize checks that were not run.

## Anti-patterns

- Do not refactor adjacent code “while here.”
- Do not add generic infrastructure for one local requirement.
- Do not copy a framework best practice over an established repository pattern without evidence.
- Do not edit generated output when the source generator owns it.
- Do not treat compilation alone as behavior proof when acceptance requires runtime behavior.
- Do not force success after the task becomes a design problem.

## Example

Task: ignore blank and comment-only lines in a LOC budget.

Good implementation: add focused cases for blank lines, full-line comments, inline code with comments, and the repository’s supported languages; change the existing counter at its current seam; run focused and guard regression tests.

Bad implementation: introduce a general parser framework, rewrite all budget logic, or skip the failing case because comments differ by language.

## Completion checklist

- [ ] Only the active task and allowed paths changed.
- [ ] The smallest sufficient solution rung was used.
- [ ] Focused feedback was observed after the change.
- [ ] Required regression checks were run.
- [ ] No test, verifier, or budget was weakened.
- [ ] The actual diff was inspected.
- [ ] Attempt evidence contains commands, paths, outcomes, and concerns.
- [ ] No `PROVEN` claim was made by the implementer.
