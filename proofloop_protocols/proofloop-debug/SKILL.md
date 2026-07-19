---
name: proofloop-debug
description: Diagnose a reproducible ProofLoop failure by building the cheapest reliable red loop, normalizing its fingerprint, locating the first causal divergence, testing one falsifiable hypothesis at a time, and proposing a materially different repair. Use internally after failed checks, repeated fingerprints, or inconsistent runtime evidence.
---

# ProofLoop Debug

## Core principle

Find the cause before changing the symptom. Every repair attempt must be justified by new evidence or a falsifiable hypothesis.

## Authority boundary

- Read attempts, check artifacts, bounded logs, diff guard results, repository context, and relevant source.
- Reproduce and inspect within the assigned access mode.
- Write only the diagnosis artifact unless Core separately grants an implementation task.
- Do not erase attempts, mutate protected evidence, or declare a repair successful.

## Phase 1: Establish the red loop

1. Run the smallest command that reproduces the authoritative failure.
2. Confirm it fails for the expected reason rather than environment noise.
3. Normalize volatile paths, timestamps, IDs, and ordering into a stable fingerprint.
4. Record exact argv, exit code, bounded output, environment facts, and affected criterion.

If reproduction is intermittent, measure the pattern and isolate nondeterminism before proposing a fix. Do not convert a flaky failure into a pass by retrying until green.

## Phase 2: Locate the first divergence

Trace backward from the observed failure:

- compare expected and actual state at component boundaries
- identify the first point where they differ
- inspect callers, data transformation, configuration, and lifecycle ownership
- compare a working nearby path or previous attempt when available
- distinguish product, harness, and environment failures

Prefer boundary evidence over stack-trace proximity. The line that throws is not necessarily the cause.

## Phase 3: Form and test a hypothesis

Write one hypothesis in this form:

> Because fact X differs at boundary Y, condition Z causes the observed fingerprint. If true, probe P will produce result R.

Run the cheapest probe that can falsify it. Change one variable at a time. Record a rejected hypothesis as useful evidence so recovery does not repeat it.

## Phase 4: Propose the repair

Propose the narrowest root-cause repair and its regression proof. Explain how it differs from failed attempts. Include rollback and affected scope when the repair touches persistent state, public contracts, concurrency, or orchestration.

After three failed, independent hypotheses, raise `DESIGN_CONFLICT` or request a deeper explorer. Do not produce a fourth cosmetic variation.

## Failure classification

Use stable categories:

- `PRODUCT_LOGIC`
- `CONTRACT_MISMATCH`
- `STATE_OR_ORDERING`
- `CONCURRENCY_OR_TIMING`
- `DEPENDENCY_OR_VERSION`
- `HARNESS_ARTIFACT`
- `PERMISSION_OR_SANDBOX`
- `ENVIRONMENT`
- `UNKNOWN`

Classification guides recovery; it is not proof of cause. Include direct evidence.

## Stop and escalate

Stop when:

- the failure cannot be reproduced within the observation budget
- logs or artifacts are stale, missing, or belong to another invocation
- the fix requires unauthorized scope or a product decision
- three materially different hypotheses fail
- the repository architecture contradicts the current design
- environment failure prevents meaningful diagnosis

Use `NO_PROGRESS`, `DESIGN_CONFLICT`, `BUDGET_EXHAUSTED`, or a specific host/environment error.

## Diagnosis artifact

Record:

- failing criterion and check
- normalized fingerprint
- reproduction command and evidence
- failure classification
- first divergence
- causal chain
- tested and rejected hypotheses
- selected hypothesis and falsifying probe
- proposed repair and why it differs
- regression check
- unknowns and escalation status

## Anti-patterns

- Do not patch the first suspicious line without a causal chain.
- Do not infer cause from one log message alone.
- Do not add sleeps or retries before proving a timing problem.
- Do not catch and ignore an exception to make the check green.
- Do not repeat the same repair with different wording.
- Do not blame the environment until repository and harness evidence support that classification.

## Example

Failure: a read-only explorer produces correct stdout but `exploration.json` is missing.

Bad diagnosis: “The model ignored instructions; retry with a stronger prompt.”

Better diagnosis: parent artifact ownership and sandbox mode disagree. Reproduce with a read-only invocation, confirm the result envelope contains valid JSON, and propose parent-process materialization instead of granting source write access.

## Completion checklist

- [ ] The red loop reproduces the authoritative failure.
- [ ] The fingerprint is stable and linked to the active invocation.
- [ ] The first divergence and causal chain use evidence.
- [ ] At least one hypothesis is falsifiable.
- [ ] Rejected hypotheses are recorded.
- [ ] The proposed repair differs materially from failed attempts.
- [ ] Regression evidence and escalation conditions are explicit.
- [ ] No success claim replaces fresh verification.
