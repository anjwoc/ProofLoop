# ProofLoop Truth and Anti-Deception Contract

This document is normative. When another ProofLoop document, prompt, test fixture, host adapter, or model response conflicts with this contract, this contract wins.

## 1. Completion is an evidence state

A role saying “done,” a process exiting zero, a JSON file matching a schema, or a mocked adapter returning `PASS` is not ProofLoop completion.

`PROVEN` is allowed only when the current run contains all authority required by the frozen contract:

1. immutable request and authorization boundary
2. acceptance criteria linked to bounded tasks
3. real source changes inside allowed paths
4. non-empty, current-revision authoritative checks
5. diff/protected-evaluator integrity
6. required review authority
7. closed proof obligations
8. fresh parent-owned evidence

A missing item is not inferred. It becomes `PARTIAL`, `FAILED`, `BLOCKED`, `NEEDS_INPUT`, `UNPROVEN`, or a ProofLoop system error according to the actual failure domain.

## 2. Evidence classes

| Class | Definition | What it may prove |
| --- | --- | --- |
| `STATIC_SOURCE` | Current branch source inspection with path/symbol evidence | Implementation presence and static contradiction only |
| `DETERMINISTIC_LOCAL` | Real command executed against the current revision with exit code and logs | The exact behavior exercised by that command |
| `SIMULATED_ADAPTER` | In-process fake adapter, fake executable, generated fixture, or mocked host stream | Orchestrator mechanics only |
| `CLI_HOST_RUN` | Parent run started by a supported host CLI | Invocation provenance, not authentication by itself |
| `AUTHENTICATED_HOST` | Real installed host, authenticated account, preserved transcript, matching source/runtime revision | Host integration and observed routing for that run |
| `MANUAL_VISUAL` | Recorded human observation of a rendered/runtime surface | The specific recorded visual scenario |

`SIMULATED_ADAPTER` evidence must never be described as authenticated host evidence. `CLI_HOST_RUN` must never be upgraded to authenticated merely because a supported host name is present.

## 3. Forbidden success shortcuts

The following are never sufficient to prove requested behavior:

- child process exit code `0`
- a role result envelope existing
- valid JSON shape
- package file presence
- compilation without required runtime behavior
- model self-identification
- requested model configuration without observed model evidence
- copied logs or copied truth reports
- empty check lists
- skipped proof stages
- a fake host named like a real host
- a fixture writing expected production artifacts
- reviewer prose replacing deterministic checks
- a test that only asserts its own stub or mock response

ProofLoop must preserve the distinction in artifacts and user-facing output.

## 4. Test integrity

A passing result is invalid when obtained by:

- deleting, skipping, weakening, or broadening a failing assertion
- replacing a repository-owned verifier with a model-proposed verifier
- modifying protected evaluator configuration after the baseline is frozen
- using a fake host to satisfy an authenticated-host scenario
- hardcoding expected output into production or test-only branches
- claiming a command was executed when only its argv was generated
- running a different scenario from the documented acceptance scenario

Every non-trivial changed rule leaves the smallest runnable regression check that fails when the rule is removed.

## 5. Host and model evidence

Host and model fields use separate meanings:

- `requestedModel`: requested configuration
- `observedModel`: model identified by structured host/session evidence
- `modelEvidence`: authority level of the observation
- `host`: controller/runtime host used by the parent run
- `evidenceOrigin`: how the parent run was invoked

`CLI_REQUESTED_ONLY`, `TEST`, `MOCK`, `SIMULATED`, missing model output, or a model name found only in prompt text is `UNPROVEN` routing evidence.

A live acceptance report must contain:

- source commit and installed runtime commit/hash
- host command and binary version
- authentication state without secrets
- run ID and parent run directory
- raw stdout/stderr references
- actual elapsed duration from a monotonic clock
- invocation host/model evidence
- Truth report and expected-output report

## 6. Timeout, retry, and budget honesty

Every effective bound must be visible before work begins or written to a run artifact:

- run deadline
- role deadline
- initial-output deadline
- check deadline
- fast/recovery attempt counts
- review repair count
- replan count
- goal cycles
- token budget
- file/line/dependency budget

A timeout is not an implementation failure unless the product command itself timed out. Provider, harness, environment, cancellation, and product failures remain separate.

A retry requires new evidence or a materially different hypothesis. Repeating the same prompt against the same fingerprint is token waste, not recovery.

## 7. Ponytail engineering contract

ProofLoop applies the Ponytail ladder only after reading the real affected flow:

1. does this need to exist?
2. is it already implemented in the repository?
3. can the standard library do it?
4. can the native platform do it?
5. can an already-installed dependency do it?
6. can one local line or guard do it?
7. otherwise write the minimum cohesive code

The ladder never removes:

- validation at trust boundaries
- security or authorization
- data-loss prevention
- required error handling
- accessibility basics
- explicitly requested behavior
- authoritative evidence

Deletion beats addition only when acceptance remains covered.

## 8. Role boundaries

### Coordinator

Launches one parent run and relays only observed events. It never synthesizes phase, progress, retry, review, or truth state.

### Planner

Freezes allowed paths, criteria links, executable verification, budgets, and escalation conditions. A plan without executable acceptance evidence is invalid.

### Implementer

Changes only allowed source. It cannot write Core evidence, decide checks passed, or issue `PROVEN`.

### Reviewer

Reads the immutable request, real diff, current checks, and proof graph. It cannot approve missing/stale inputs or override failed checks.

### Core

Owns command execution, diff integrity, evidence sealing, proof closure, and the final Truth verdict.

## 9. Fast-lane limitation

A deterministic fast lane may approve only facts its policy can actually derive. File count, added-line budget, and passing commands do not automatically prove semantic intent alignment or global minimality.

Until a bounded fast-lane policy explicitly maps every criterion to authoritative checks and documents its simplicity basis, its review must state that semantic review was not performed. It must not emit an unrestricted “independent review approved the change” claim.

## 10. Release acceptance

A release is not ready when any of these remains:

- deterministic development checks fail or were not run
- package validation fails
- documented test commands reference missing files
- documented live scenario differs from the actual fixture
- installed runtime does not match source revision
- authenticated Codex/AGY/Claude acceptance is missing
- simulated reports occupy authenticated report paths
- CI status is absent for a claimed release commit
- open P0 truth/evidence finding remains

## 11. Required final ledger

Every delivery records each gate as exactly one of:

- `PASSED`: command/observation exists and supports the claim
- `FAILED`: command/observation contradicts the claim
- `BLOCKED`: external condition prevented execution
- `UNEXECUTED`: no attempt was made

`BLOCKED` and `UNEXECUTED` are never rewritten as success in summaries.
