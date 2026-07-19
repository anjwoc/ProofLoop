---
name: code-review
description: Review an actual base-to-head change for intent alignment, correctness, regressions, security, simplicity, and evidence quality.
---

# Code Review

## Core principle

Review the real diff and executable evidence, not the implementation narrative; report only findings that are actionable, scoped, and supported.

## Authority boundary

This pack is read-only. It may identify findings, missing evidence, and safer reductions. It may not edit source, reinterpret the user request, or mark the run proven. Severity must reflect concrete impact and likelihood, not stylistic preference.

## Inputs

Read the immutable request, intent contract, task briefs, base-to-head diff, repository fingerprint, check artifacts, proof graph revisions, and relevant surrounding code. Ignore summaries when they conflict with artifacts.

## Procedure

1. Restate the authorized behavior change and explicit non-goals in one short internal frame.
2. Enumerate changed files and identify the contract each file can affect.
3. Trace new/changed data and control flow through callers, errors, state, and cleanup.
4. Check every acceptance criterion for implementation and fresh evidence coverage.
5. Search for regression surfaces: compatibility, authorization, persistence, concurrency, retries, cancellation, resource cleanup, and observability.
6. Compare the solution to established repository patterns and identify avoidable new abstractions or duplication.
7. Inspect tests for false positives, over-mocking, assertion weakening, missing negative cases, and stale execution.
8. Classify each candidate as fact, inference, or unknown; verify facts against exact code/artifacts.
9. Remove speculative or preference-only comments that do not change correctness, safety, maintainability, or authorized scope.
10. Return findings ordered by severity, then a concise evidence-gap and residual-risk summary.

## Finding contract

Each finding contains a severity, exact file and tight line range, triggering scenario, observed mechanism, consequence, and smallest credible correction. `P0/P1` requires a clear high-impact path. `P2` is a real bounded defect. `P3` is low-impact but actionable. Missing proof is labeled as an evidence gap, not automatically a product bug.

## Review dimensions

- Intent: requested behavior is present without unauthorized expansion.
- Correctness: success, boundary, error, and state transitions are coherent.
- Security: trust boundaries, validation, authorization, secrets, and injection paths.
- Reliability: retries, idempotency, concurrency, cleanup, timeout, cancellation.
- Compatibility: API/schema/config/data behavior for existing callers.
- Simplicity: no unnecessary abstraction, dependency, or broad refactor.
- Evidence: tests/checks are relevant, fresh, and sufficiently independent.

## Stop and escalate

Return `UNREVIEWABLE` when the diff, base revision, intent, or required evidence is missing/stale. Escalate an intent conflict rather than choosing a product interpretation. If a suspected issue depends on unavailable runtime facts, report the exact unknown and a verification method instead of asserting a defect.

## Anti-patterns

- Do not review only files named in the summary.
- Do not request unrelated refactors under “clean code.”
- Do not label theoretical possibilities as high severity without a reachable scenario.
- Do not trust a new test merely because it passes.
- Do not repeat formatter/linter output as manual findings.
- Do not approve because the diff is small or reject because it is large.

## Worked example

If a new retry wraps a non-idempotent write, trace whether the retry can occur after a committed side effect. A finding is valid when the call path, failure timing, duplicate consequence, and missing idempotency control are shown. “Retries can be risky” is not a finding.

If a helper name differs from personal preference but follows nearby code and has no correctness impact, omit the comment.

## Resource routing

Use common review guidance and load domain-specific reference slices selected for the change surface. Review the base-to-head diff plus targeted surrounding code; do not load the entire repository by default. Request fresh evidence only for a concrete gap.

## Completion checklist

- All changed files and acceptance criteria were covered.
- Findings cite reachable behavior and exact evidence.
- Severity reflects impact and likelihood.
- False-positive and overbuild checks were performed.
- Evidence gaps and residual risks are separate from defects.
- No source mutation or final proof claim occurred.
