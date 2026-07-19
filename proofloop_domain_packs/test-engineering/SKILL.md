---
name: test-engineering
description: Design trustworthy tests that expose behavior regressions without weakening production contracts or overfitting implementation details.
---

# Test Engineering

## Core principle

A useful test fails for the intended defect, passes for the intended behavior, and remains stable when irrelevant implementation details change.

## Authority boundary

You may add or modify tests and authorized fixtures. Do not weaken assertions, skip checks, alter production behavior solely for mocks, or change global CI thresholds without explicit authorization. Tests submitted by the implementing model are evidence inputs; Core decides whether they are fresh, relevant, and sufficient.

## Inputs

Read the acceptance criteria, changed or target seams, repository fingerprint, existing test layers, fixtures, and check commands. Identify the cheapest test layer that can observe the contract without mocking away the behavior under test.

## Procedure

1. Translate each criterion into an observable behavior and a falsifiable failure.
2. Locate the closest existing test pattern and its fixture ownership.
3. Run or construct a red case that fails for the intended reason before implementation when feasible.
4. Choose unit, contract, integration, browser, or end-to-end scope based on the real boundary crossed.
5. Control nondeterminism explicitly: time, randomness, concurrency, network, filesystem, locale, and ordering.
6. Use representative inputs plus one meaningful boundary or negative case.
7. Avoid asserting private calls when a public outcome is stable and observable.
8. Run the focused test, then the smallest relevant regression suite.
9. Prove the test can detect the defect through red evidence, mutation, or an equivalent controlled check when risk warrants it.
10. Record runtime, flakes/retries, environment assumptions, and uncovered risks.

## Quality checklist

- Failure message identifies the broken contract.
- The test does not pass when the relevant assertion is removed or behavior is reverted.
- Fixtures do not accidentally pre-satisfy the condition under test.
- Mocks stop at external or expensive boundaries and preserve contract shape.
- Cleanup is deterministic and isolated.
- Parallel execution does not share mutable identifiers or ports unsafely.
- Snapshot/golden updates are reviewed for semantic changes.
- Coverage is treated as a locator, not proof of behavior.

## Stop and escalate

Return `NEEDS_CONTEXT` when no runnable test command, environment contract, or stable behavior seam can be found. Return `BLOCKED` if the requested success requires skipping, loosening, or deleting a legitimate assertion, or if the environment cannot supply a required external dependency and no authorized substitute exists.

## Anti-patterns

- Do not make a flaky test pass by adding arbitrary sleep or retries.
- Do not mock the method whose behavior the criterion requires.
- Do not update snapshots before understanding the diff.
- Do not assert only status/success when payload or side effect is the contract.
- Do not copy large fixtures when a focused builder already exists.
- Do not confuse one passing run with absence of flakiness.

## Artifact contract

Report criterion-to-test mapping, test layer rationale, red evidence when available, fresh commands/results, controlled nondeterminism, adapter/reference IDs, and remaining gaps. Include exact artifact paths. Distinguish environment failure from product failure.

## Worked example

For a duplicate-charge regression, write a test at the idempotency/persistence boundary that submits the same key twice and observes one durable effect. A mocked payment method call count alone is insufficient if transaction or retry behavior is the defect.

For an intermittent browser failure caused by an unknown external service, first isolate and fingerprint it. Do not add a blanket retry and call the defect fixed.

## Resource routing

Use common test guidance for every task. Load pytest, Jest, or JUnit guidance only when detected. Prefer repository commands and configuration over framework defaults. Invoke broader suites only when the change surface or proof authority requires them.

## Completion checklist

- Each new/changed test names the behavior it protects.
- Red/failure relevance was established where feasible.
- Focused and relevant regression runs are fresh.
- No test, threshold, or production seam was weakened.
- Nondeterminism and environmental dependencies are explicit.
