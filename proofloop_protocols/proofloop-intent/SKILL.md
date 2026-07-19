---
name: proofloop-intent
description: Compile an original ProofLoop request into explicit objectives, observable acceptance criteria, constraints, non-goals, authorization boundaries, risks, and unknowns without expanding authority. Use internally before execution or whenever recovery exposes an intent conflict.
---

# ProofLoop Intent

## Core principle

Preserve the request before interpreting it. Refine ambiguity into explicit structure, never into new permission.

## Authority boundary

- Read the immutable request artifact and repository facts needed to identify targets.
- Write only the intent artifact assigned by Core.
- Do not edit source, choose an architecture, authorize external effects, or declare the request complete.
- Treat deployment, destructive actions, credential use, external writes, and scope expansion as unauthorized unless the original request explicitly permits them.

## Inputs

Read the smallest useful fields from:

- `request.json`: original text, hash, run identity
- repository preflight: named targets and detectable constraints
- existing intent artifact only when revising after a conflict

If the original text and stored hash disagree, stop with `REQUEST_INTEGRITY_FAILURE`.

## Procedure

1. Copy the original request hash into the contract without rewriting it.
2. State one objective as an outcome, not an implementation method.
3. Derive acceptance criteria that an independent verifier can observe.
4. Separate explicit constraints from inferred repository constraints.
5. Record non-goals that prevent plausible scope expansion.
6. Define the authorization boundary from the original request only.
7. List target paths or surfaces as candidates when exact paths are not proven.
8. Classify uncertainty as an assumption, open question, or missing authority.
9. Record risk signals without changing the requested outcome.
10. Link every refined statement to the original text or a repository fact.

## Acceptance criteria

Write each criterion with:

- a stable ID
- an observable statement
- the expected evidence type
- an explicit verifier when known

Prefer “command exits 0 and output contains X” over “works correctly.” Prefer “existing API response remains compatible” over “is robust.” Do not invent numeric thresholds the user did not request unless an existing repository policy supplies them; identify that policy as provenance.

## Unknowns and assumptions

Use `UNKNOWN` when a decision changes product behavior, authorization, data safety, or public compatibility. Use an assumption only when a conventional default is reversible, local, and inside existing authority.

An assumption never closes a proof obligation. Mark how Core can confirm or falsify it.

## Stop and escalate

Return a structured escalation when:

- acceptance cannot be made observable
- two plausible interpretations produce materially different outcomes
- repository facts contradict the request
- required external access or mutation is not authorized
- the requested target cannot be distinguished from protected scope

Use `AUTHORIZATION_AMBIGUOUS`, `ACCEPTANCE_UNKNOWN`, or `INTENT_CONFLICT`; do not guess past these conditions.

## Artifact contract

Produce the fields Core requires, including:

- `originalRequestHash`
- `objective`
- `acceptanceCriteria`
- `constraints`
- `nonGoals`
- `authorizationBoundary`
- `riskSignals`
- `targets`
- `assumptions`
- `unknowns`

Label repository-derived statements with their source path or artifact. Keep facts, interpretations, and unknowns distinct.

## Anti-patterns

- Do not turn “investigate” into permission to fix.
- Do not turn “implement” into permission to deploy.
- Do not make the request easier by deleting difficult acceptance criteria.
- Do not hide uncertainty in confident prose.
- Do not copy implementation ideas into the objective as mandatory design.
- Do not replace the original request with the refined prompt.

## Example

Request: “Add CSV export to the report page.”

Good refinement:

- objective: a user can download the current report as CSV
- criterion: exported rows match the active report filters
- constraint: preserve existing page behavior
- unknown: whether hidden columns belong in the export
- non-goal: redesigning the report page

Bad refinement: “Introduce a background export service, upload files to object storage, and email a link.” None of those permissions or architectural requirements came from the request.

## Completion checklist

- [ ] The original request hash is preserved.
- [ ] Every criterion is independently observable.
- [ ] Constraints, non-goals, assumptions, and unknowns are separated.
- [ ] No authority was added by interpretation.
- [ ] Risk signals and candidate targets are recorded.
- [ ] Conflicts that require the user are escalated instead of guessed.
- [ ] The artifact does not claim runtime correctness or `PROVEN`.
