# ProofLoop Minimum Completion Scope

Status: `EXECUTION TARGET`

This document narrows the current hardening work to the smallest set of changes required for ProofLoop to behave as intended in real use.

The target is not “perfect architecture.” The target is:

> A user request is compiled once, every role receives the same authoritative contract, execution policy is resolved once, no model or test adapter can manufacture success, and the final verdict is backed by parent-owned evidence.

## Completion decision

ProofLoop is usable as intended when the six items below are complete.

Everything outside these six items is follow-up work and must not delay the first trustworthy release.

---

## MUST-1. Replace the dual compiler path with one mandatory prompt contract

### Current problem

`prompt_contract.py` already compiles the request, templates, execution brief, and role projection. However, `orchestrator.py` still contains the older T2/T3-only compiler path.

This leaves two sources of truth:

- legacy compiler policy: active only for T2/T3
- new prompt contract: intended to be active for T0-T3

### Required change

In `proofloop_core/engine/orchestrator.py`:

1. Remove the legacy `compiler_active = tier in {T2, T3}` branch.
2. Remove direct construction of `compiler-policy.json` and direct reconciliation in the orchestrator.
3. After strategy, grounding, and baseline are available, call only `ensure_active_prompt_contract(self)`.
4. Before every role invocation, require `compile_role_ir()` to succeed.
5. Reject any invocation that has no active `prompt-compilation.json`, `execution-brief.json`, and final prompt projection.

### Files

- `proofloop_core/engine/orchestrator.py`
- `proofloop_core/contracts/prompt_contract.py`
- `proofloop_core/engine/roles.py`
- `proofloop_core/engine/task_executor.py`

### Completion evidence

- T0, T1, T2, and T3 all produce `prompt-compilation.json`.
- No role builds an independent `PromptIR` or raw prompt contract.
- Exactly one active execution brief exists.
- The final sent prompt hash matches the stored projection and host receipt.

### Result

The user's original request, refined intent, selected templates, scope, constraints, and role instructions remain one continuous contract.

---

## MUST-2. Wire one resolved run policy through the complete runtime

### Current problem

`default-run-policy.json` and `run_policy.py` exist, but the CLI and orchestrator still contain operational numeric defaults. Skill token budgets and live-evidence limits are also hardcoded separately.

The policy file therefore documents values but does not yet control the complete run.

### Required change

Resolve the policy once at the CLI or programmatic entrypoint and pass the same immutable `ResolvedRunPolicy` through:

```text
CLI / API
  -> ResolvedRunPolicy
  -> InvocationContext
  -> ProofLoopOrchestrator
  -> RoleInvocation / host runner
  -> skills
  -> evidence sealing and validation
```

Specific changes:

1. Add `--policy-file` to `orchestrate`, `goal`, and `run`.
2. Change CLI operational defaults to `None`; only explicit CLI values become overrides.
3. Pass `ResolvedRunPolicy` and `InvocationContext` into the orchestrator.
4. Call `start_run(..., policy=..., invocation_context=...)` explicitly.
5. Read role timeout and token budget from `roles.<role>`.
6. Move T0-T3 skill budgets into the policy schema.
7. Read evidence file, byte, and chunk limits from the resolved policy.
8. Remove duplicated timeout, cycle, replan, retention, relay, hook, and evidence limits from runtime code.

### Files

- `proofloop_core/ui/cli.py`
- `proofloop_core/engine/orchestrator.py`
- `proofloop_core/contracts/run_policy.py`
- `proofloop_core/contracts/run_state.py`
- `proofloop_core/runtimes/adapters.py`
- `proofloop_core/runtimes/host_runner.py`
- `proofloop_core/engine/skills.py`
- `proofloop_core/assurance/live_evidence.py`
- `proofloop_core/config/default-run-policy.json`

### Completion evidence

- `python scripts/validate_no_hidden_policy.py` returns `NO_HIDDEN_OPERATIONAL_POLICY`.
- Changing one policy value changes the corresponding runtime behavior.
- `run-policy.json` hash equals `run-provenance.json.policyHash`.
- Unknown policy keys and undeclared CLI overrides fail before run creation.

### Result

There is one visible place to control execution limits. Hidden defaults can no longer silently change the pipeline.

---

## MUST-3. Preserve the Ponytail contract through every serialization boundary

### Current problem

`TaskBrief` parses:

- `simplicity.evidenceRefs`
- `simplicity.permittedNewArtifacts`

but `task_to_dict()` and aggregate-task construction do not preserve both fields.

The contract can therefore be valid in memory and weaker after writing and reloading it.

### Required change

1. Include `evidenceRefs` and `permittedNewArtifacts` in `task_to_dict()`.
2. Union and preserve both fields in `aggregate_task()`.
3. Make task round-trip equality part of the contract.
4. Reject a task if a new file or dependency is not explicitly permitted.
5. Keep `semanticApproval` separate from `SCOPE_COMPLIANT`.

### Files

- `proofloop_core/engine/orchestrator.py`
- `proofloop_core/contracts/task_brief.py`
- `proofloop_core/assurance/diff_guard.py`

### Completion evidence

```text
TaskBrief
  -> task_to_dict
  -> JSON
  -> load_task_brief
  -> same evidenceRefs and permittedNewArtifacts
```

A task that permits one new file must allow only that file, not every new file.

### Result

Ponytail remains an executable contract rather than a planner-only suggestion.

---

## MUST-4. Bind the final verdict to policy, provenance, prompt, checks, diff, and receipts

### Current problem

The host adapter validates receipts during invocation, but the final live-evidence bundle currently seals mainly checks, diff, logs, and the verification plan.

The final verdict does not yet revalidate the full chain.

### Required change

The parent-owned evidence bundle must include or hash-bind:

- `run-policy.json`
- `run-provenance.json`
- `request-envelope.json`
- `intent-contract.json`
- `prompt-compilation.json`
- final `prompt-projections/*.json`
- validated `invocations/*/receipt.json`
- stdout/stderr transcripts
- verification plan
- check results
- diff-guard result
- review result when semantic claims are required

Validation must reject:

- policy hash mismatch
- source or runtime revision mismatch
- stale or copied prompt projection
- copied receipt from another run
- changed transcript
- missing role result
- exit code 0 without a parent-captured artifact
- an adapter/model supplied authority claim

### Files

- `proofloop_core/assurance/live_evidence.py`
- `proofloop_core/contracts/host_receipt.py`
- `proofloop_core/context/proof_graph.py`
- `proofloop_core/assurance/truth.py`
- `proofloop_core/runtimes/adapters.py`

### Completion evidence

The following attacks all produce `FAILED` or `BLOCKED`:

1. Copy a valid receipt into another run.
2. Modify stdout after receipt sealing.
3. Change the final prompt projection.
4. Replace `run-policy.json` after run creation.
5. Return `evidenceOrigin=PARENT_HOST_RECEIPT` from a fake adapter.
6. Exit successfully without the required result artifact.

### Result

Truth is based on a continuous parent-owned evidence chain, not on a model's payload or a single passing test file.

---

## MUST-5. Do not let ACP sessions claim the same authority as observed CLI processes

### Current problem

Legacy CLI receipts contain an actual child PID and executable. ACP receipts may fall back to the parent PID and use ProofLoop's own Python file as the executable path.

That proves a parent-handled session, not necessarily an independently observed external host process.

### Minimum release decision

For the first trustworthy release:

1. Legacy CLI execution may close `HOST_EXECUTION` and `MODEL_ROUTING` after receipt validation.
2. ACP execution may prove only session mechanics unless it supplies an actual child/process identity and observable runtime identity.
3. ACP receipts must not use the parent PID as evidence of a child host process.
4. Truth must remain `LOCAL_DETERMINISTIC` or `PARTIAL` for ACP-only runs that cannot prove host execution.

A later release may add a dedicated `PARENT_ACP_SESSION_RECEIPT` origin and stronger ACP process/session attestation.

### Files

- `proofloop_core/contracts/host_receipt.py`
- `proofloop_core/contracts/evidence_policy.py`
- `proofloop_core/runtimes/adapters.py`
- `proofloop_core/assurance/truth.py`

### Completion evidence

- Fake or parent-PID ACP receipt cannot close `HOST_EXECUTION`.
- A validated legacy Codex/AGY CLI receipt can close the claim.
- `AUTHENTICATED_HOST` is emitted only when the required host obligation is actually closed.

### Result

ProofLoop does not overstate what it observed.

---

## MUST-6. Prove one real end-to-end path and keep every other claim narrow

### Required acceptance runs

The first usable release requires only these real runs:

1. One authenticated Codex CLI run.
2. One authenticated AGY CLI run, when AGY support is advertised as production-ready.
3. One forced deterministic failure followed by recovery or block.
4. One forged-authority attack.
5. One copied or modified receipt attack.

Each run must retain:

- source commit and tree
- runtime bundle hash
- effective policy and hash
- prompt compilation and final projections
- host receipts and transcripts
- check and diff evidence
- Truth report with explicit claim scope

### Release rule

Release is allowed only when:

```text
focused integrity suite       PASS
full deterministic suite      PASS
prompt validator              PASS
hidden-policy validator       PASS
document command validator    PASS
package validator             PASS
Codex live acceptance         PASS
AGY live acceptance           PASS or AGY marked experimental
adversarial acceptance        PASS
```

A deterministic test adapter may prove local mechanics only. It must never be reported as real Codex, AGY, host execution, or model-routing evidence.

### Result

The release claim matches the evidence actually collected.

---

# What is already sufficiently implemented

These areas do not need redesign before the first trustworthy release:

- source-linked request and intent hashes
- existing-template selection and merge
- common `compile_role_ir()` use by explorer, planner, reviewer, and implementer
- adapter authority-key stripping
- parent-captured role result artifacts
- legacy CLI child PID and transcript receipt creation
- copied receipt and changed transcript rejection
- claim-aware evidence eligibility
- table-driven repair decisions with stable rule IDs
- identical same-role failure blocking
- diff-based new-file, dependency, scope, assertion, and test-disable guards

They may need integration fixes, but not a new framework.

---

# Explicitly out of scope for this completion

Do not add these while completing the six MUST items:

- a second prompt-template registry
- a new generic workflow DSL
- a new dependency-injection framework
- a replacement ProofGraph
- a replacement TaskBrief schema
- a replacement host adapter abstraction
- additional UI or dashboard redesign
- large benchmark infrastructure changes
- support for every possible host transport
- automatic semantic approval from file counts or test success

---

# Exact implementation order

```text
Wave 1: MUST-3 Ponytail persistence
Wave 2: MUST-1 single prompt compiler path
Wave 3: MUST-2 resolved policy wiring
Wave 4: MUST-4 final evidence-chain binding
Wave 5: MUST-5 ACP claim restriction
Wave 6: MUST-6 real acceptance and cleanup
```

The order is intentional:

- fix contract loss before relying on the contract
- remove dual compiler before binding prompts
- resolve policy before sealing provenance
- finish evidence binding before live acceptance
- restrict unsupported authority before release

---

# Definition of usable as intended

ProofLoop is considered usable as intended only when all statements below are true:

- The exact user request enters one mandatory compilation path.
- All T0-T3 roles receive projections from the same active execution brief.
- No role can bypass the prompt contract.
- One resolved policy controls all execution-affecting limits.
- No operational value is silently duplicated in CLI, orchestrator, skill, adapter, or evidence code.
- Task scope and Ponytail permissions survive serialization and aggregation.
- A model or test adapter cannot grant itself evidence authority.
- Exit code 0 is insufficient without a valid parent-captured result and receipt.
- The final Truth report revalidates the complete evidence chain.
- `AUTHENTICATED_HOST` means an actual supported host execution was observed.
- Simulation tests are reported only as local deterministic mechanics.

Until all statements are true, the correct release status is `NOT PROVEN`.
