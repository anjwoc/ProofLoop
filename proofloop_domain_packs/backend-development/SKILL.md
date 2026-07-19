---
name: backend-development
description: Apply repository-specific backend change discipline while preserving public contracts, persistence semantics, and failure behavior.
---

# Backend Development

## Core principle

Change the narrowest backend seam that satisfies the intent while preserving every observable contract not explicitly authorized to change.

## Authority boundary

You may inspect and edit only paths authorized by the active task brief. You may propose checks and produce implementation evidence. You may not broaden an API, weaken authentication, alter stored data semantics, or close your own proof obligations. Only Core-owned checks, diff guards, and reviewers can close them.

## Required inputs

Read the immutable request, intent contract, task brief, repository fingerprint, selected reference slices, and current proof graph. Treat framework references as conditional advice, not repository facts. If the fingerprint and source disagree, source wins and the mismatch must be reported.

## Procedure

1. Identify the external contract: route, command, event, schema, persistence boundary, or service method.
2. Trace one concrete request from entry point to response or durable side effect.
3. Record existing validation, authorization, transaction, retry, timeout, and error-mapping behavior.
4. Map each acceptance criterion to one change seam and at least one observable check.
5. Reuse the repository's handler, service, repository, serializer, and migration conventions.
6. Choose the smallest compatible change. Do not add a layer merely because a reference architecture contains it.
7. Add or update a failing test first when behavior changes and an executable test seam exists.
8. Implement one vertical slice before expanding edge cases.
9. Verify success, invalid input, unauthorized access when applicable, and one downstream failure path.
10. Inspect the final diff for accidental public fields, schema drift, hidden writes, and logging of sensitive values.

## Contract checklist

- Inputs are parsed and validated at the existing boundary.
- Authorization is enforced before protected reads or writes.
- Errors preserve the repository's status/code/message contract.
- Persistence changes define transaction and rollback behavior.
- Retries do not duplicate non-idempotent effects.
- New fields have explicit optionality and compatibility behavior.
- Observability does not expose credentials, tokens, or personal data.
- Tests exercise behavior rather than only implementation calls.

## Stop and escalate

Return `NEEDS_CONTEXT` when the active route, schema, transaction owner, or verifier cannot be located. Return `BLOCKED` when satisfying the request requires an unauthorized migration, public contract change, dependency change, or security-policy decision. After repeated identical failures, report the fingerprint and competing root-cause hypotheses; do not keep patching symptoms.

## Anti-patterns

- Do not infer framework conventions from filenames alone.
- Do not create generic repositories, services, or DTOs for a one-seam change.
- Do not make a required field optional only to satisfy a failing test.
- Do not catch every exception and return success-shaped data.
- Do not alter production code solely to make a mock easier.
- Do not claim compatibility without checking existing callers and serialized output.

## Artifact contract

Report the selected entry point, affected contracts, invariants, changed paths, tests run, unresolved risks, and reference slice IDs. Mark statements as `FACT`, `INFERENCE`, or `UNKNOWN`. A passing model-authored test is supporting evidence, never final proof.

## Worked boundary example

For “add an optional filter to an existing list endpoint,” first locate the current query parser and response serializer. Extend the existing query path, keep the unfiltered response byte-compatible where practical, add tests for absent, valid, and invalid filter values, and inspect generated database access. Do not introduce a new query abstraction unless the repository already uses it or the existing seam cannot express the criterion.

For “change the account identifier format” without migration authority, stop. The request crosses public and persistent contracts and requires an explicit compatibility decision.

## Resource routing

Read `references/common.md` for all backend tasks. Read a framework adapter only when Core selected it from the repository fingerprint. Use recovery guidance only after a fresh failing check. Never load Django, Spring, or Ghost guidance merely because the request says “backend.”

## Completion checklist

- Every acceptance criterion maps to a changed seam and fresh evidence.
- The default/previous behavior remains covered unless explicitly removed.
- Security, persistence, and error invariants were considered where relevant.
- No protected or unrelated path changed.
- The report names evidence paths and remaining unknowns without claiming `PROVEN`.
