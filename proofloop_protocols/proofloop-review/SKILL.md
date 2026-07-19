---
name: proofloop-review
description: Independently review a T2 or T3 ProofLoop change against the immutable intent, actual base-to-head diff, repository conventions, deterministic evidence, regression risk, and simplicity. Use internally after checks pass, after recovery repairs, or when a high-risk plan or implementation needs adversarial alignment review.
---

# ProofLoop Review

## Core principle

Review the real change, not the implementer’s story. Separate intent correctness, engineering quality, and missing proof.

## Authority boundary

- Read the immutable request, intent, design/plan when present, actual diff, checks, diff guard, and proof graph.
- Inspect relevant callers and tests to validate findings.
- Write only the review artifact; do not edit source.
- Do not override failed deterministic checks or close obligations above model-review authority.

## Preconditions

Reject review input as `CANNOT_VERIFY` when:

- the base or head revision is unknown
- the diff is missing or does not match the reviewed worktree
- required check artifacts are stale or belong to another invocation
- protected-path integrity is unresolved

Do not compensate for missing evidence with deeper prose analysis.

## Pass 1: Intent and scope

1. Map every acceptance criterion to concrete diff behavior and evidence.
2. Identify criteria with no implementation or no verifier.
3. Check non-goals, authorization, allowed paths, and protected paths.
4. Detect behavior added without request support.
5. Confirm the implementation follows the selected design or explains a validated deviation.

## Pass 2: Correctness and regression

Inspect:

- boundary conditions and error paths
- state transitions, ordering, idempotency, cancellation, and retries when relevant
- public contracts and backward compatibility
- persistent data invariants and migration safety
- authorization and validation ordering
- tests that could pass while the real integration remains unwired

Use repository evidence for each finding. A hypothetical risk without a reachable path is not a defect.

## Pass 3: Simplicity and maintainability

Ask:

- Can any changed file, branch, abstraction, dependency, or configuration be deleted while preserving acceptance?
- Does the change duplicate an existing repository seam?
- Is complexity proportional to the current requirement?
- Did recovery leave dead code, compatibility shims, or redundant checks?

Mark `OVERBUILT` only with a concrete deletion or simplification candidate and explain why acceptance remains covered.

## Finding contract

Every actionable finding must contain:

- stable ID and severity
- exact path and narrow location
- observed fact
- impact on a criterion, invariant, or regression surface
- evidence or reproduction route
- smallest credible remediation
- confidence and remaining unknowns

Use severity by impact, not style preference:

- `CRITICAL`: security/data loss/authorization or system-wide failure
- `HIGH`: acceptance failure or likely regression in a core path
- `MEDIUM`: bounded correctness, maintainability, or missing-proof issue
- `LOW`: real but non-blocking improvement

## Verdicts

- `APPROVED`: no blocking finding; relevant model-review obligations have evidence
- `FIX_REQUIRED`: at least one concrete blocking finding
- `OVERBUILT`: acceptance may pass but unnecessary complexity must be removed
- `DESIGN_CONFLICT`: repair requires revisiting the selected design or intent
- `CANNOT_VERIFY`: authoritative review inputs are missing or stale

An approval is model evidence, not deterministic runtime proof.

## False-positive check

Before publishing a finding:

1. inspect the surrounding implementation and callers
2. search for an existing guard or test that contradicts it
3. distinguish fact from inference
4. ensure the suggested fix stays inside scope

Delete findings based only on personal style or imagined future requirements.

## Anti-patterns

- Do not trust summaries or commit messages over the diff.
- Do not approve because tests pass when wiring or acceptance is missing.
- Do not reject correct repository conventions in favor of generic best practices.
- Do not produce a long list of low-value style comments.
- Do not fix the code while reviewing it.
- Do not approve your own earlier design by default; reassess it against the diff.

## Example

Finding: “Cleanup is called after recovery exhaustion, but the cancellation terminal path still bypasses it.”

Strong evidence names the FSM transition, shows the bypassing branch, links the cleanup invariant, and suggests routing both terminal paths through the existing cleanup transition. Weak review merely says “consider edge cases.”

## Completion checklist

- [ ] The immutable intent and actual base-to-head diff were reviewed.
- [ ] Deterministic artifact freshness was checked.
- [ ] Acceptance, regression, and simplicity were separate passes.
- [ ] Every blocking finding has location, impact, evidence, and remediation.
- [ ] False positives and style-only findings were removed.
- [ ] Unknowns are explicit.
- [ ] The verdict does not overrule deterministic evidence.
- [ ] Re-review is required after any repair.
