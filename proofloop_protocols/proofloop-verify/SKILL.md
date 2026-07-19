---
name: proofloop-verify
description: Close ProofLoop acceptance, regression, scope, and integrity obligations with fresh authoritative evidence tied to the current revision. Use internally after implementation, after every repair, before completion claims, and whenever evidence may be stale or incomplete.
---

# ProofLoop Verify

## Core principle

Match every claim to fresh evidence of sufficient authority. Missing or stale evidence is not a pass.

## Authority boundary

- Read intent criteria, proof obligations, task checks, current revisions, actual diff, attempt and review artifacts.
- Propose exact verifier commands and interpret their results.
- Let the parent process execute commands, capture raw output, enforce timeouts, and store authoritative artifacts.
- Do not edit source, change acceptance, weaken checks, or emit the final `PROVEN` verdict.

## Evidence authority

Use the minimum authority required by each obligation:

- deterministic check: build, test, schema, static validator, runtime probe
- diff guard: path, budget, dependency, protected-test integrity
- external observation: rendered UI, service behavior, integration result
- model review: intent alignment, design consistency, simplicity

A model claim cannot close a deterministic or diff-guard obligation. More model confidence does not raise authority.

## Procedure

1. List every open criterion and invariant with required authority and current revision.
2. Map each obligation to the cheapest verifier that can falsify it.
3. Validate command existence, argv safety, working directory, timeout, and required environment.
4. Ask the parent process to run focused checks on the current worktree.
5. Run proportionate regression checks after focused checks pass.
6. Inspect the real base-to-head diff and diff-guard artifact.
7. Confirm artifact invocation, source revision, obligation revision, and verifier hash.
8. Record PASS, FAIL, CONTRADICTED, or UNVERIFIABLE per obligation.
9. Compare final claims with the evidence ledger and surface every gap.
10. Return evidence for Core to evaluate at the Truth Gate.

## Freshness rules

Evidence is stale when any relevant input changes:

- source diff or head revision
- task or acceptance criterion
- proof-obligation revision
- verifier command, code, configuration, or hash
- environment fact required by the check

After a repair, rerun affected checks. Do not reuse an earlier green result merely because the command name is unchanged.

## Command safety

- Store and execute commands as argv arrays.
- Do not interpolate shell fragments from model output.
- Use the repository-defined command when available.
- Bound time and output while preserving raw logs.
- Distinguish timeout, cancellation, nonzero exit, harness failure, and environment failure.
- Never convert missing usage or missing test counts to zero.

## Negative evidence

For critical behavior, include a negative or failure-path check when practical:

- unauthorized input is rejected before mutation
- invalid schema fails validation
- retry does not duplicate persistent state
- stale artifact cannot close a revised obligation
- protected evaluator mutation is detected

Do not add low-value tests solely to increase counts.

## Scope and integrity

Inspect:

- allowed versus changed paths
- changed tests and whether assertions were weakened
- new dependencies and generated files
- change budgets
- benchmark/evaluator integrity
- untracked artifacts that affect execution

A passing test suite does not override a scope or integrity failure.

## Unverifiable outcomes

Use `UNVERIFIABLE` when the required observation cannot be made with available authority. Explain the missing verifier, access, environment, or product decision. Do not downgrade the obligation or substitute a weaker check.

Classify harness and environment failures separately from product failures so the benchmark and recovery policy remain honest.

## Stop and escalate

Return a specific failure when:

- a check fails or times out
- evidence is stale or belongs to another invocation
- required verifier code or environment is unavailable
- protected paths or evaluators changed
- the diff exceeds scope or budget
- an obligation has no sufficient evidence

Use `CHECK_FAILED`, `SCOPE_VIOLATION`, `STALE_EVIDENCE`, `HARNESS_FAILURE`, `ENVIRONMENT_FAILURE`, or `CANNOT_VERIFY`.

## Artifact contract

Record for every check and obligation:

- criterion/obligation ID and revision
- verifier argv, working directory, timeout, and hash
- invocation and source revision
- exit status and bounded summary
- raw artifact reference
- authority and verdict
- freshness inputs
- unresolved gap or contradiction

## Anti-patterns

- Do not say “all tests pass” without the current command result.
- Do not rerun an unchanged check repeatedly for reassurance.
- Do not accept an implementer’s copied output as parent-owned evidence.
- Do not treat build success as proof of user behavior.
- Do not hide failing subtests behind an aggregate exit parser.
- Do not let review approval override a failed check.
- Do not claim success when a required observation is unavailable.

## Example

Claim: “The CLI model switch is visible to the user.”

Required evidence is not a prompt that asked the model to announce itself. Use structured host model evidence, a model-change event tied to the active session, and renderer output generated from that event. If the host exposes only the requested model, report it as unobserved rather than resolved.

## Completion checklist

- [ ] Every current obligation has sufficient evidence or an explicit gap.
- [ ] Focused and required regression checks ran on the current revision.
- [ ] Artifact freshness, ownership, authority, and hashes were checked.
- [ ] The real diff passed scope and integrity checks.
- [ ] Product, harness, environment, timeout, and cancellation outcomes are distinct.
- [ ] Negative paths were checked where risk requires them.
- [ ] No weaker evidence replaced a required authority.
- [ ] Only Core is left to compute the final Truth Gate verdict.
