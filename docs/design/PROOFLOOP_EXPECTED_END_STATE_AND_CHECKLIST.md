# ProofLoop Expected End State and Inspection Checklist

Status: `DESIGN_TARGET`  
Target branch: `codex/preserve-eb097dd-with-main`  
Implementation status at document creation: `UNEXECUTED`  
Authoritative implementation plan: `plans/proofloop-integrity-policy-hardening.md`

This document describes what ProofLoop must look like **after all planned changes are implemented**. It is not evidence that the behavior already exists. Every completion claim must be backed by the artifacts and commands listed below.

## 1. Final request-to-truth pipeline

```text
User request bytes
  │
  ├─> request-envelope.json
  │     exact bytes + request SHA-256 + explicit permissions/denials
  │
  ├─> intent-contract.json
  │     objective / criteria / constraints / non-goals / unknowns
  │     every derived statement linked to user spans or labelled provenance
  │
  ├─> prompt-compilation.json
  │     selected existing template IDs + versions
  │     strict merge result + conflicts + template-set SHA-256
  │
  ├─> execution-brief.json
  │     active for T0, T1, T2, T3
  │     grounded facts/inferences + authorization + approved/protected scope
  │
  ├─> prompt-projections/<invocation-id>.json
  │     one role-specific envelope + projection SHA-256
  │     no competing raw/refined goal blocks
  │
  ├─> host invocation receipt
  │     process/session/transcript/prompt/source/runtime binding
  │
  ├─> Core-owned checks + diff guard + review
  │
  └─> truth-report.json
        claim-by-claim status and evidence scope
```

### Required invariant

A role invocation cannot occur unless all artifacts from `request-envelope.json` through its role projection validate and their hashes form one continuous chain. A missing or invalid stage fails closed before mutation.

## 2. Expected normal behavior after implementation

### Example user request

```text
ProofLoop의 결제 처리 버그를 수정해줘.

1. 동일 요청이 동시에 들어와도 한 번만 결제되어야 한다.
2. 기존 public API는 변경하지 않는다.
3. 새 외부 의존성을 추가하지 않는다.
4. 관련 단위 테스트와 동시성 테스트를 실행한다.
5. 테스트하지 않은 내용을 성공했다고 말하지 않는다.
```

### Expected compiled artifacts

#### `request-envelope.json`

- Preserves the exact request text and byte hash.
- Records invocation source, explicit permissions, and explicit denials.
- Cannot be overwritten by a model or adapter.

#### `intent-contract.json`

Expected logical content:

- Objective: fix the payment-processing bug.
- Acceptance criteria:
  - concurrent identical requests produce one payment.
  - relevant unit and concurrency tests execute successfully.
  - unexecuted behavior is not claimed as successful.
- Constraints:
  - public API unchanged.
  - no new external dependency.
- Unknowns:
  - repository-specific implementation path, until grounded.
- Every statement contains source references to exact request lines/spans or an explicit repository/proof-policy provenance.

#### `prompt-compilation.json`

Expected content:

- Selected templates include the existing mutation, repository-surface, and risk templates appropriate to the request.
- Template versions and canonical template-set hash are recorded.
- Authority ceiling is the most restrictive selected value.
- Allowed scope is intersected or rejected; it is never widened by union.
- `must_do`, `must_not`, proof requirements, and stop conditions are conflict-checked.
- Any conflict produces `PROMPT_TEMPLATE_CONFLICT` before host invocation.

#### `execution-brief.json`

Expected content:

- `kind: EXECUTION_BRIEF` for every tier.
- User-explicit statements remain user-explicit.
- Repository facts have source file/symbol references.
- Model-only guesses remain hypotheses and cannot authorize mutation.
- Blocking unknowns remain open or cause `PROMPT_CONTRACT_UNRESOLVED`.
- Approved/protected paths are constrained by the request and repository evidence.

#### Role projection

Expected planner projection:

- objective
- all acceptance criteria
- constraints and non-goals
- scope candidates/approved/protected paths
- open questions and risk signals
- exact execution-brief and invocation binding hashes

Expected implementer projection:

- objective
- task-linked acceptance criteria
- allowed/protected scope
- Core-owned checks
- simplicity/change budget
- no unrelated exploratory context

### Expected role prompt

A final host prompt contains exactly one authoritative role envelope. It does not contain all three of the following as independent instruction blocks:

- raw user request
- free-form refined request
- execution brief role view

The raw request remains available as an authority reference artifact, not as a second competing goal.

### Expected final result

A successful local deterministic run may report:

```json
{
  "verdict": "PROVEN",
  "claimScope": "LOCAL_DETERMINISTIC",
  "claims": {
    "PROMPT_CONTRACT_APPLIED": "CLOSED",
    "PRODUCT_BEHAVIOR": "CLOSED",
    "SCOPE_INTEGRITY": "CLOSED",
    "HOST_EXECUTION": "NOT_REQUIRED",
    "MODEL_ROUTING": "NOT_REQUIRED"
  }
}
```

A live Codex/AGY acceptance may close host and routing claims only when valid parent-owned receipts bind the same prompt projection, transcript, run, source revision, and runtime revision.

## 3. Expected failure behavior

| Failure | Required result | Host invocation allowed? |
| --- | --- | --- |
| Request envelope hash mismatch | `REQUEST_ENVELOPE_INVALID` | No |
| Existing templates not selected for a required role | `PROMPT_TEMPLATE_SET_INCOMPLETE` | No |
| Contradictory must-do/must-not or authority rules | `PROMPT_TEMPLATE_CONFLICT` | No |
| Allowed scope becomes wider during merge | `PROMPT_SCOPE_WIDENING_REJECTED` | No |
| Model introduces an unreferenced criterion | `PROMPT_REFINEMENT_UNGROUNDED` | No |
| Blocking unknown remains unresolved | `PROMPT_CONTRACT_UNRESOLVED` | No mutation role |
| T0/T1 attempts raw-string shortcut | `ROLE_PROMPT_CONTRACT_MISSING` | No |
| Role projection hash does not match receipt | `HOST_RECEIPT_PROMPT_MISMATCH` | Result rejected |
| Adapter claims authenticated host origin | `EVIDENCE_ORIGIN_FORGERY_IGNORED` | Mechanics may continue; host claim stays open |
| Exit code 0 without result/receipt | `ROLE_RESULT_MISSING` or `HOST_RECEIPT_MISSING` | No success |
| Checks list is empty | `CHECK_EVIDENCE_EMPTY` | No success |
| Same failure repeats without evidence delta | `BLOCKED_IDENTICAL_FAILURE` | No same-role retry |
| New file/dependency lacks frozen permission | `UNJUSTIFIED_NEW_ARTIFACT` | No promotion |
| Fast lane has checks/diff only | `SCOPE_COMPLIANT`, not semantic `APPROVED`/`MINIMAL` | Final semantic claim remains open |
| Source/runtime revision differs | `RUNTIME_SOURCE_MISMATCH` | Live test stops before host execution |

## 4. Itemized inspection checklists

## A. Prompt refinement and template pipeline

### Implementation inspection

- [ ] The existing `TemplatePolicy` definitions are reused; no second template framework exists.
- [ ] Every T0–T3 path creates `prompt-compilation.json` and active `execution-brief.json`.
- [ ] `compile_ir()` or its consolidated compiler implementation is reachable from every role invocation path.
- [ ] `compile_intent()` no longer treats the first non-empty line as sufficient semantic truth.
- [ ] Explicit requirements, constraints, negations, paths, and permission statements have source references.
- [ ] Template `allowed_scope` uses intersection/rejection semantics.
- [ ] Conflicting `must_do` and `must_not` values are rejected.
- [ ] Production PromptIR/envelopes contain no `todo` identifiers or time-based IDs.
- [ ] `_invoke` accepts a typed role envelope or validated projection, not an arbitrary final prompt string.
- [ ] No exact-string replacement of `User request:\n...` remains in the production path.
- [ ] Role prompt contains exactly one authoritative objective/contract source.

### Artifact inspection

- [ ] Request hash in `intent-contract.json` matches `request-envelope.json`.
- [ ] Template-set hash in `prompt-compilation.json` reproduces from selected template bytes.
- [ ] Execution-brief hash matches its content.
- [ ] Role projection references the same execution-brief hash and invocation ID.
- [ ] Receipt references the same role projection hash.
- [ ] Prompt projection text/hash stored by Core equals the prompt sent to the host.

### Positive QA

- [ ] Multi-paragraph Korean request retains every numbered requirement.
- [ ] English prose with explicit “do not” statements produces non-goals/constraints.
- [ ] T0 direct task and T3 high-risk task both use the same compiler entry point.
- [ ] Planner, implementer, recovery, explorer, and reviewer receive only their required fields.

### Adversarial QA

- [ ] Hand-built raw prompt passed to `_invoke` is rejected.
- [ ] Model proposal inventing a criterion is rejected.
- [ ] Proposal dropping a difficult criterion is rejected.
- [ ] Conflicting read-only and mutation templates fail closed.
- [ ] Duplicate raw and refined goal blocks fail prompt validation.
- [ ] Stale projection copied to another invocation fails receipt validation.

### Completion rule

All implementation, artifact, positive, and adversarial checks above must pass. A rendered preamble test alone is insufficient.

## B. Fake-success prevention

### Implementation inspection

- [ ] Evidence origin is assigned only by parent Core.
- [ ] Adapter/model payload cannot set authenticated origin, host receipt, or claim scope.
- [ ] Host receipt is generated from observed child process facts.
- [ ] Evidence policy maps allowed origins/authorities to claim types in one place.
- [ ] Truth reads claim closure, not adapter verdict strings.

### Artifact inspection

- [ ] Receipt has run/invocation/prompt/transcript/source/runtime bindings.
- [ ] Core evidence bundle independently rehashes source artifacts.
- [ ] Truth report exposes `claimScope` and per-claim status.
- [ ] Test/mechanics run is visibly labelled and cannot be mistaken for authenticated acceptance.

### Positive QA

- [ ] Genuine local deterministic run closes local behavior/scope claims.
- [ ] Genuine authenticated host run closes host claim with valid receipt.

### Adversarial QA

- [ ] Fake host label does not close host claim.
- [ ] Requested model name alone does not close routing claim.
- [ ] Copied receipt, changed transcript, stale report, and exit-zero-only case all fail.
- [ ] Empty checks and skipped required verification cannot become `PROVEN`.

### Completion rule

Every fake/stale/copied variant must fail closed with the documented stable reason; genuine behavior must still be provable at its correct scope.

## C. Hidden-hardcode prevention

### Implementation inspection

- [ ] One shipped run-policy file exists.
- [ ] One strict resolver creates one effective policy artifact.
- [ ] CLI numeric defaults are `None` and resolve through policy.
- [ ] Task attempt/recovery budgets are explicit frozen fields.
- [ ] Tier prompt activation, token budgets, timeout, cycles, replans, bundle limits, hook timeout, and relay interval come from policy.
- [ ] No silent `.get(key, literal)` fallback exists for policy-sensitive fields.
- [ ] Protocol constants that are not runtime policy remain named constants rather than becoming unnecessary configuration.

### Artifact inspection

- [ ] `run-policy.json` records value, source, and canonical hash.
- [ ] Run provenance references the policy hash.
- [ ] Prompt compilation references the policy/template activation used.

### Positive QA

- [ ] Same policy bytes resolve identically across repeated runs.
- [ ] Explicit CLI/file overrides appear with their source.

### Adversarial QA

- [ ] Missing required policy field fails before run creation.
- [ ] Reintroduced numeric default in a policy-sensitive function fails CI.
- [ ] Environment variable cannot silently replace frozen policy unless explicitly supported and recorded as an input source.

### Completion rule

No operational or decision policy may be invisible in runtime code. The policy validator and focused tests must both pass.

## D. Repeated if/else and meaningless defensive-case prevention

### Implementation inspection

- [ ] Repair behavior uses one normalized `RepairState`.
- [ ] Actions use one closed `RepairAction` enum.
- [ ] Rules are an ordered, named decision table with stable IDs.
- [ ] Task executor performs one exhaustive action dispatch.
- [ ] Unreachable `CONTRACT_CHANGE` branch is removed.
- [ ] `max_replans == 1` no longer expands to a hidden larger value.
- [ ] Final review remediation uses the same frozen task budget.
- [ ] Unknown action fails closed rather than entering another defensive fallback.

### Artifact inspection

- [ ] Every repair decision records rule ID, inputs, consumed budget, and next action.
- [ ] Budget remaining values match the frozen policy/task contract.

### Positive QA

- [ ] Success, owner decision, changed failure, recovery, replan, and exhaustion each map to one expected rule.

### Adversarial QA

- [ ] Identical failure with no evidence delta never retries the same role.
- [ ] Unknown role/action/state cannot continue execution.
- [ ] Review rejection cannot secretly spend an extra recovery call.

### Completion rule

Each reachable state has one documented result and one test. No “just in case” branch may continue work without a frozen rule.

## E. Ponytail minimality and bloat prevention

### Implementation inspection

- [ ] Prompt compiler reuses existing algebra, templates, brief, and role-view structures.
- [ ] No generic prompt DSL, workflow engine, DI container, or new third-party package is introduced.
- [ ] `TaskBrief.simplicity` and `ChangeBudget` remain the central minimality structures.
- [ ] New fields are limited to evidence references and explicitly permitted artifacts.
- [ ] New file/dependency/public API changes require frozen authorization.
- [ ] Fast lane emits scope/check facts only, not semantic minimality approval.
- [ ] Reviewer overbuilt finding contains a concrete deletion candidate.
- [ ] Security, authorization, validation, accessibility, data-loss prevention, and explicit requirements cannot be removed as “simplification.”

### Artifact inspection

- [ ] Simplicity rationale lists considered earlier Ponytail rungs.
- [ ] Evidence references show why reuse/stdlib/native/current dependency was insufficient when new code is added.
- [ ] Diff guard report identifies every new file and dependency against the frozen permission list.

### Positive QA

- [ ] Existing helper reuse passes with one-file change and no new dependency.
- [ ] Explicitly required new file passes when permitted and justified.

### Adversarial QA

- [ ] Duplicate prompt compiler or second template registry is rejected.
- [ ] Unjustified helper layer/dependency fails.
- [ ] Scope-compliant but semantically overbuilt change remains unapproved.

### Completion rule

Independent review must find no removable new artifact and no duplicate responsibility. “Few files” alone is not proof of minimality.

## 5. Commands required for final verification

```bash
python3 -m pytest \
  tests/deterministic/test_prompt_compiler_pipeline.py \
  tests/deterministic/test_prompt_template_algebra.py \
  tests/deterministic/test_role_prompt_projection.py \
  tests/deterministic/test_fake_success_barrier.py \
  tests/deterministic/test_run_policy.py \
  tests/deterministic/test_repair_decision_table.py \
  tests/deterministic/test_ponytail_enforcement.py -q

python3 scripts/validate_prompt_pipeline.py
python3 scripts/validate_no_hidden_policy.py
python3 scripts/validate_documented_commands.py
python3 scripts/run_tests.py
python3 scripts/validate_package.py
```

Authenticated acceptance must additionally run the documented Codex and AGY scenarios from an isolated current-source `PROOFLOOP_HOME` and retain raw transcripts and receipts.

## 6. Final release checklist

- [ ] All focused tests pass with raw output retained.
- [ ] Complete deterministic suite passes without deleting or weakening unrelated tests.
- [ ] Package validation passes.
- [ ] Prompt-pipeline validator passes.
- [ ] Hidden-policy validator passes.
- [ ] Documentation command validator passes.
- [ ] Current source hash equals installed runtime hash.
- [ ] Every role receipt binds the correct prompt projection.
- [ ] Genuine Codex and AGY scenarios pass at their declared claim scope.
- [ ] Every fake/bypass/stale/copied adversarial scenario fails with its expected code.
- [ ] Independent prompt-fidelity review finds no lost or invented requirement.
- [ ] Independent Ponytail review finds no removable or duplicated artifact.
- [ ] Execution ledger distinguishes `PASSED`, `FAILED`, `BLOCKED`, and `UNEXECUTED`.
- [ ] No release status is upgraded from local/test evidence to authenticated-host evidence.

## 7. Current status

At the time this document was written:

- Design and checklists: `COMPLETED`
- Product implementation: `UNEXECUTED`
- Focused tests described above: `UNEXECUTED`
- Full deterministic/package validation: `UNEXECUTED`
- Authenticated Codex/AGY acceptance: `UNEXECUTED`
- Release readiness: `NOT PROVEN`
