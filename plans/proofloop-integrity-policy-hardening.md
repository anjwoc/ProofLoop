# proofloop-integrity-policy-hardening - Work Plan

Status: `READY_FOR_EXECUTION`  
Intent: `CLEAR`  
Review required: `true`  
Target repository: `anjwoc/ProofLoop`  
Target branch: `codex/preserve-eb097dd-with-main`  
Planning method: LazyCodex `ulw-plan` principles — explore first, one decision-complete plan, executor needs zero judgment calls, every todo includes acceptance and happy/failure QA, and completion requires a separate final verification wave.

## TL;DR (For humans)

### What you will get

ProofLoop will use four parent-owned contracts instead of scattered conditionals, disconnected prompt text, and hidden defaults:

1. **Prompt Compilation Contract** — the immutable user request is converted into a source-linked intent contract, merged with the existing prompt templates, projected once per role, and cryptographically bound to the invocation. No role may bypass it or receive competing raw/refined goals.
2. **Evidence Contract** — an adapter or model can submit claims, but only Core-owned evidence with a permitted origin can close a proof obligation.
3. **Run Policy Contract** — timeouts, attempts, replans, token budgets, bundle limits, hook timeouts, and release requirements come from one strict, hashed policy artifact.
4. **Simplicity Contract** — repair routing is table-driven, fast-lane output cannot claim semantic approval/minimality, and Ponytail evidence is required before unnecessary files, dependencies, or abstractions are accepted.

### Why this approach

The current defects share one root cause: authority and policy are implicit. A fake adapter can look like a host, numeric defaults exist in several layers, repair behavior is encoded in nested branches, minimality is partly asserted by prose, and the prompt templates exist without being the mandatory path into role execution. Central contracts remove those ambiguities once instead of adding another defensive `if`.

### Confirmed prompt-pipeline defects this plan addresses

1. `proofloop_core/prompting/algebra.py::compile_ir()` and the existing `TemplatePolicy` values are not the mandatory orchestrator path.
2. `compile_intent()` derives the objective from the first non-empty line and acceptance criteria mainly from list items, so a multi-paragraph request can be reduced incorrectly.
3. `compile_ir()` uses time-based prompt IDs and generic contract IDs instead of artifact hashes; several live role prompts still contain literal `todo` metadata.
4. Template algebra documents restrictive allowed-scope merging but currently unions allowed scopes.
5. The grounded compiler is active only for T2/T3. T0/T1 write a shadow brief but role execution does not consume an active compiled brief.
6. T2/T3 activation currently converts a shadow brief through `build_conservative_proposal()`, which changes lifecycle state but does not actually refine user intent from grounded facts.
7. Role-view injection depends on replacing the exact string `User request:\n<request>`. Current role prompts use `refined_request` as their goal, so the role view is normally prepended while the previous goal remains. A role can receive multiple competing prompt authorities.
8. Prompt-integrity tests verify only that the anti-deception preamble renders; they do not prove that user input travelled through template selection, reconciliation, role projection, and host invocation.

### What this will NOT do

- It will not remove all conditionals from the codebase.
- It will not move schema versions, hash algorithms, enum values, template text, or internal I/O chunk sizes into user configuration.
- It will not add a generic workflow engine, prompt DSL, rules DSL, dependency-injection container, or new third-party package.
- It will not ask a model to rewrite the request and trust the rewrite as authority.
- It will not discard the original user request; the exact bytes remain immutable and independently inspectable.
- It will not require an authenticated host to prove ordinary local deterministic behavior.
- It will not let local or test evidence prove host execution, model routing, or UI observation.

### Definition of “no hardcoding”

“Hardcoding prohibited” means **no hidden operational or decision policy in runtime code**. Any value that changes execution outcome, resource budget, retry behavior, template activation, evidence eligibility, or release acceptance must come from the resolved run policy, frozen prompt contract, or frozen task contract and must be persisted with its source and SHA-256. Protocol constants and versioned template content that do not silently choose runtime behavior remain named, reviewable code or data constants.

### Primary risks

- Truth/report/prompt schema consumers must be migrated atomically.
- Existing deterministic tests that treat injected adapters as authenticated hosts must change their expected claim scope.
- Host receipts require source/runtime binding, so live tests will fail until the current branch is installed into an isolated `PROOFLOOP_HOME`.
- Changing prompt construction from mutable strings to typed envelopes touches every role caller and must be completed in one wave.
- Over-generalizing either the policy engine or prompt compiler would recreate the bloat this plan is intended to prevent.

### Fixed design decisions

| ID | Decision |
| --- | --- |
| D1 | The exact request bytes live only in the immutable request envelope. Derived prompt artifacts point back to source spans and hashes. |
| D2 | Existing ProofLoop prompt templates are reused and made mandatory; no parallel replacement template framework is introduced. |
| D3 | Every run tier, including T0/T1, must produce a valid active prompt contract before any role invocation. Higher tiers may add grounded facts/review requirements but cannot bypass the same compiler. |
| D4 | A model may propose semantic refinement, but Core reconciliation accepts only statements linked to user source spans, repository evidence, proof policy, or an explicitly labelled reversible default. Unlinked model text remains a hypothesis and cannot authorize mutation. |
| D5 | Each role invocation receives exactly one `RolePromptEnvelope`; raw request text, formatted intent text, and role view are not separately concatenated. |
| D6 | Prompt IDs, contract IDs, template-set IDs, and projections are content-addressed; no time-based IDs or `todo` identifiers remain in production paths. |
| D7 | Evidence origin is assigned by the parent Core, never accepted from adapter/model payload. |
| D8 | A test adapter may prove mechanics or local deterministic behavior, but can never close `HOST_EXECUTION`, `MODEL_ROUTING`, or `EXTERNAL_OBSERVATION` obligations. |
| D9 | `PROVEN` means every required obligation is closed by eligible evidence; reports also expose `claimScope` so local success cannot look like host success. |
| D10 | Operational policy has one shipped JSON source, one strict resolver, one canonical hash, and one persisted effective artifact. Runtime functions receive resolved values; they do not own defaults. |
| D11 | Repair routing uses one normalized state and an ordered decision table with stable rule IDs. The task executor dispatches an enum with one exhaustive `match`, not repeated defensive branches. |
| D12 | Repeated identical failure with no evidence delta is never retried by the same role. Recovery/replan can occur only when the frozen task/run policy has remaining budget. |
| D13 | Deterministic fast lane may assert only `CHECKS_PASS` and `SCOPE_COMPLIANT`; it cannot emit `APPROVED` or `MINIMAL`. |
| D14 | Ponytail enforcement reuses existing `TaskBrief.simplicity` and `ChangeBudget`; only the minimum new evidence fields are added. No separate complexity framework is introduced. |

## Scope

### In scope

- Immutable request envelope through source-linked intent compilation.
- Mandatory selection and strict merging of the existing prompt templates.
- Grounded refinement, reconciliation, and content-addressed role prompt projection for every tier.
- Parent-owned run provenance and host invocation receipts.
- Evidence-origin eligibility in the proof graph and Truth Gate.
- Single-source execution policy and removal of policy defaults from runtime functions/CLI.
- Table-driven repair decisions and removal of unreachable/redundant branches.
- Deterministic Ponytail gates for task planning, diff scope, dependencies, new files, and semantic review.
- Negative tests that deliberately bypass prompt compilation or forge host/model/report evidence.
- Isolated live-host acceptance with current-source/current-runtime binding.
- CI gates and documentation aligned with real commands.

### Out of scope / Must-NOT-Have

- No new external dependency.
- No generic prompt language, policy language, or expression evaluator.
- No second prompt-template system beside the existing ProofLoop templates.
- No factory/interface with one implementation.
- No provider-specific authentication implementation inside ProofLoop.
- No automatic retry added beyond the frozen policy.
- No global cyclomatic-complexity threshold for every repository file.
- No model self-report accepted as evidence of host, model, command, test, elapsed time, completion, or user intent.
- No compatibility shim that silently accepts the old ambiguous evidence or prompt format.
- No “temporary” fallback from compiled role prompts to raw prompt strings.
- No “temporary” fallback from authenticated-host validation to local/test evidence.

## Verification strategy

### Baseline and red-first order

1. Add prompt-bypass and fake-success negative tests first. They must fail against the current implementation for the expected reason.
2. Implement the smallest shared prompt/policy/evidence contracts that make those tests pass.
3. Run focused tests after each todo.
4. Run the complete deterministic suite and package validation.
5. Install the exact source revision into an isolated `PROOFLOOP_HOME`.
6. Run authenticated Codex and AGY acceptance only after deterministic gates pass.
7. Keep `UNEXECUTED`, `BLOCKED`, `FAILED`, and `PASSED` separate in the execution ledger.

### Evidence requirements

| Claim | Minimum evidence |
| --- | --- |
| User request preserved | Immutable request-envelope bytes and SHA-256 |
| Prompt refinement applied | Prompt compilation trace containing input hashes, selected template IDs/versions, merge result, reconciliation references, output contract hash |
| Role received compiled prompt | Role prompt envelope and projection SHA-256 bound to the same invocation receipt |
| Code behavior | Core-sealed deterministic check bound to current source revision |
| Diff/scope | Core diff guard bound to task contract and baseline |
| Host process executed | Parent-owned host receipt with executable, process, transcript, run, and session binding |
| Model routing observed | Host receipt or ACP session evidence bound to the same invocation |
| UI/browser behavior | Recorded external observation produced by a declared surface scenario |
| Minimality | Frozen simplicity decision + diff facts; model review only when deterministic facts cannot close it |
| Release ready | Prompt compilation, all required claims, current source/runtime hashes, deterministic suite, and package gates pass |

### Planned evidence paths

- `.proofloop/runs/<run-id>/request-envelope.json`
- `.proofloop/runs/<run-id>/intent-contract.json`
- `.proofloop/runs/<run-id>/prompt-compilation.json`
- `.proofloop/runs/<run-id>/execution-brief.json`
- `.proofloop/runs/<run-id>/prompt-projections/<invocation-id>.json`
- `.proofloop/runs/<run-id>/run-policy.json`
- `.proofloop/runs/<run-id>/run-provenance.json`
- `.proofloop/runs/<run-id>/invocations/<invocation-id>/receipt.json`
- `.proofloop/runs/<run-id>/core-evidence/`
- `.proofloop/runs/<run-id>/truth-report.json`
- `reports/release-check.json`
- `reports/live/<scenario>/<host>/`

## Execution strategy

### Wave 1 — prompt and policy authority

Todos 1–2 make prompt compilation mandatory and centralize runtime policy. No host role is invoked until both contracts validate.

### Wave 2 — provenance and host receipts

Todos 3–4 introduce immutable run provenance and parent-owned invocation receipts.

### Wave 3 — truth closure and bounded control flow

Todos 5–6 route all proof closure through the evidence contract and replace repair branching with one decision table.

### Wave 4 — Ponytail and release enforcement

Todos 7–9 remove semantic fake approvals, enforce minimality at existing seams, bind live acceptance to current runtime, and align CI/docs.

### Dependency matrix

| Todo | Depends on |
| --- | --- |
| 1 | none |
| 2 | none |
| 3 | 1, 2 |
| 4 | 2, 3 |
| 5 | 1, 3, 4 |
| 6 | 2 |
| 7 | 1, 2, 5, 6 |
| 8 | 1–7 |
| 9 | 1–8 |

## File change matrix

| File | Exact modification | Expected result |
| --- | --- | --- |
| `proofloop_core/prompting/algebra.py` | Keep the existing templates but make merge rules strict: restrictive authority, conflict rejection, allowed-scope intersection, deterministic ordered output. Remove time-based IDs from compilation. | Existing templates become executable policy rather than dead declarations. |
| `proofloop_core/prompting/prompt_compiler.py` (new) | Orchestrate deterministic extraction, optional grounded proposal reconciliation, template selection, strict merge, PromptIR creation, compilation trace, and content-addressed IDs. | One mandatory compiler produces the sole prompt authority for every tier and role. |
| `proofloop_core/prompting/prompt_ir.py` | Add source/provenance hashes and remove production acceptance of placeholder IDs/metadata. | A prompt can be traced to exact request, intent, templates, brief, role, and invocation. |
| `proofloop_core/prompting/renderers.py` | Render one typed `RolePromptEnvelope`; include mandatory truth contract, role projection, and output contract once. | Raw/refined/role-view prompt duplication disappears. |
| `proofloop_core/engine/intent.py` | Replace first-line/list-only compilation with source-span extraction and explicit provenance per objective/criterion/constraint/non-goal. Preserve uncertainty instead of inventing criteria. | Multi-paragraph Korean/English requests retain all explicit obligations and negations. |
| `proofloop_core/contracts/execution_brief.py` | Accept source-linked intent fields, repository-grounded facts/inferences, template-set hash, and prompt-compiler hash; require active brief for every tier. | The refined brief is inspectable, validated, and bound to source evidence. |
| `proofloop_core/engine/reconciler.py` | Reconcile optional model proposals against source refs, repository facts, authorization, unknowns, and immutable criteria. Reject unreferenced invention and dropped requirements. | Model-assisted refinement cannot silently alter user intent. |
| `proofloop_core/contracts/role_view.py` | Project minimal fields plus binding hashes; preserve approved/protected scope needed by the role; remove ambiguous alias-only authority. | Each role receives exactly the contract fields it needs and no competing goal text. |
| `proofloop_core/engine/roles.py` | Stop constructing independent ad-hoc PromptIR objects with `todo` IDs. Request role envelopes from the compiler and supply only role-specific output schema/context refs. | Explorer/planner/reviewer all use the same compiled request contract. |
| `proofloop_core/engine/task_executor.py` | Request implementer/recovery envelopes from the compiler instead of building prompt strings from `refined_request`. | Mutation roles cannot bypass refined scope, criteria, or template rules. |
| `proofloop_core/engine/orchestrator.py` | Compile active prompt contract for all tiers; remove `compiler_active` tier bypass, `refined_request` string authority, and exact-string replacement injection; block before `_invoke` when projection is absent/invalid. | Every host call is guaranteed to be downstream of the same validated prompt pipeline. |
| `proofloop_core/config/default-run-policy.json` (new) | Store all operational budgets, template activation rules, and evidence/release requirements with schema/policy version. | One visible shipped policy replaces scattered runtime defaults and tier activation literals. |
| `proofloop_core/contracts/run_policy.py` (new) | Strict dataclasses/enums, canonical hash, override merge, no missing-field fallback. | Missing/invalid policy fails before a run starts. |
| `proofloop_core/ui/cli.py` | Numeric argparse defaults become `None`; resolve policy once; create explicit invocation context. | CLI, compiler, orchestrator, role runner, and live harness use the same values. |
| `proofloop_core/contracts/task_brief.py` | Remove attempt defaults; require explicit budgets; strengthen existing simplicity contract with evidence refs and permitted new artifacts. | Planner cannot omit retry/minimality decisions. |
| `proofloop_core/engine/skills.py` | Read tier token budgets from resolved policy. | Skill allocation no longer owns hardcoded tier budgets. |
| `proofloop_core/assurance/live_evidence.py` | Read evidence bundle limits from resolved policy snapshot; seal prompt compilation, policy, provenance, and receipts. | Bundle validation is prompt-, revision-, and policy-bound. |
| `proofloop_core/contracts/run_state.py` | Remove environment/argv inference; write mutable run state separately from immutable provenance. | Adapter/environment spoofing cannot rewrite evidence origin. |
| `proofloop_core/contracts/request_envelope.py` | Record required claim classes/scopes selected by Core command/scenario, not the model. | Host claims are explicit obligations, not inferred from successful exit. |
| `proofloop_core/context/proof_graph.py` | Add evidence `origin`, `claimType`, `runId`, `invocationId`; delegate closure to central eligibility policy. | Authority level alone can no longer let fake/test evidence close host claims. |
| `proofloop_core/contracts/evidence_policy.py` (new) | Define allowed origin/authority combinations per claim type and stable rejection reasons. | One closure rule replaces scattered origin string checks. |
| `proofloop_core/runtimes/host_runner.py` | Parent writes receipt from the actual child process and transcript; include prompt projection hash, executable/version/PID/session/hash/timestamps. | Host evidence proves which exact compiled prompt was executed. |
| `proofloop_core/runtimes/adapters.py` | Treat returned payload as untrusted role output; adapter cannot set origin/scope/receipt/prompt identity. | A fake adapter may supply work output but not promote its evidence class or claim a compiled prompt. |
| `proofloop_core/context/trace.py` | Accept observed model only when linked to a valid invocation receipt. | Copied or free-floating model strings do not prove routing. |
| `proofloop_core/assurance/truth.py` | Compute claim closure from proof graph; require valid prompt-compilation chain; expose claim summary and reject insufficient origin/scope. | `PROVEN` cannot hide prompt bypass or unproven host/routing claims. |
| `proofloop_core/contracts/expected_output.py` | Render prompt-contract status, scope-qualified results, and stable blockers. | UI states which compiled contract ran and never overclaims. |
| `proofloop_core/engine/repair.py` | Replace defaulted nested decisions with `RepairState`, `RepairAction`, ordered rules, and stable rule IDs. | One deterministic decision per state; no magic repeat count. |
| `proofloop_core/assurance/diff_guard.py` | Enforce planned new files/dependencies against existing change/simplicity contract. | Unplanned abstractions/dependencies fail deterministically. |
| `proofloop_core/assurance/assurance.py` | Keep `SCOPE_COMPLIANT` separate from semantic `APPROVED`/`MINIMAL`. | Passing file-count checks does not become semantic approval. |
| `scripts/run_host_live.py` | Create isolated runtime home, install current source, verify source/runtime/prompt hashes, require host receipts. | Live acceptance cannot execute an old global Core or a bypassed prompt. |
| `scripts/validate_no_hidden_policy.py` (new) | AST-check policy-sensitive modules for numeric defaults, silent fallback, direct policy comparisons, and tier activation literals. | CI detects newly reintroduced hidden policy. |
| `scripts/validate_prompt_pipeline.py` (new) | Validate that every mutating/reviewing role is reachable only through the compiler and that no production PromptIR contains placeholders. | CI detects dead templates, raw-string bypass, duplicate goal sources, and `todo` prompt metadata. |
| `scripts/validate_documented_commands.py` | Validate the revised real command set and scenario IDs. | Documentation cannot reference nonexistent tests/fixtures. |
| `.github/workflows/evidence-gates.yml` | Run focused prompt/fake-success gates, policy validators, full deterministic suite, package validator. | Pull requests expose prompt bypass and integrity regressions. |
| `tests/deterministic/test_prompt_compiler_pipeline.py` (new) | End-to-end request envelope → intent → templates → brief → role projection tests across T0–T3. | The existing templates are proven to be on the real execution path. |
| `tests/deterministic/test_prompt_template_algebra.py` (new) | Scope intersection, authority minimum, conflict rejection, stable hashes, no placeholder IDs. | Template merge behavior is restrictive and deterministic. |
| `tests/deterministic/test_role_prompt_projection.py` (new) | Exactly-one-goal/source, role field minimization, invocation binding, no raw-string fallback. | Host prompt projections cannot contain competing request authorities. |
| `tests/deterministic/test_fake_success_barrier.py` (new) | Forged adapter/host/model/copied receipt/stale report cases. | Every fake-success route has a failing regression test. |
| `tests/deterministic/test_run_policy.py` (new) | Strict policy load, overrides, hash, missing fields, no defaults. | Effective policy is reproducible and inspectable. |
| `tests/deterministic/test_repair_decision_table.py` (new) | Rule coverage, no same-role identical retry, exhaustive action dispatch. | Repair behavior is bounded and explainable by rule ID. |
| `tests/deterministic/test_ponytail_enforcement.py` (new) | Fast-lane semantics, new dependency/file, simplicity evidence, deletion candidate. | Bloat cannot be approved by scope checks alone. |
| `docs/EXPECTED_RESULTS_AND_TEST_SCENARIOS.md` | Replace ambiguous `normal` scenario with explicit IDs, prompt input/output contracts, and real commands. | Documented request and compiled prompt equal the executed fixture. |
| `docs/PIPELINE_EXECUTION_GUIDE.md` | Document prompt compilation stages, policy source/hash, and scope-qualified verdicts. | Operators can reproduce both effective prompt and effective limits. |
| `docs/PROOFLOOP_TRUTH_AND_ANTI_DECEPTION_CONTRACT.md` | Update normative prompt/evidence eligibility and release rules. | Prose matches executable policy. |
| `docs/design/PROOFLOOP_EXPECTED_END_STATE_AND_CHECKLIST.md` (new) | Show the final pipeline, artifacts, expected behavior, failure codes, and itemized inspection checklist. | The user can compare implementation results against one explicit target document. |
| `docs/audits/PROOFLOOP_EXECUTION_LEDGER.md` | Record every command/result/artifact without status promotion. | Final report remains auditable. |

## Todos

- [ ] 1. Make the existing prompt templates the mandatory request-to-role compilation path
  - **Files:** modify `proofloop_core/prompting/algebra.py`, `proofloop_core/prompting/prompt_ir.py`, `proofloop_core/prompting/renderers.py`, `proofloop_core/engine/intent.py`, `proofloop_core/contracts/execution_brief.py`, `proofloop_core/engine/reconciler.py`, `proofloop_core/contracts/role_view.py`, `proofloop_core/engine/roles.py`, `proofloop_core/engine/task_executor.py`, `proofloop_core/engine/orchestrator.py`; add `proofloop_core/prompting/prompt_compiler.py`; add three focused test modules and `scripts/validate_prompt_pipeline.py`.
  - **Implementation:** preserve exact request bytes; extract explicit objective/criteria/constraints/non-goals with source pointers; select the existing intent/operation/surface/risk templates from a table; merge them with restrictive algebra; reconcile any model proposal only against user spans and grounded repository facts; produce one active execution brief for T0–T3; create one invocation-bound role envelope; render exactly one goal/contract source; persist compilation/projection hashes. Replace time IDs and all production `todo` identifiers with deterministic content-addressed IDs.
  - **Must NOT:** no second template system, no free-form model rewrite used as authority, no T0/T1 bypass, no string replacement injection, no concatenated raw + refined + role-view goals, no fallback to an uncompiled prompt.
  - **Acceptance criteria:**
    - `compile_ir()` or its extracted compiler logic is called on every role path.
    - Every role invocation has `requestEnvelopeSha256`, `intentContractSha256`, `templateSetSha256`, `executionBriefSha256`, `roleProjectionSha256`, and `invocationId`.
    - T0, T1, T2, and T3 each produce an active `execution-brief.json` and `prompt-compilation.json` before the first role invocation.
    - A multi-paragraph request preserves every explicit numbered/bulleted requirement, negation, path, and authorization statement with source refs.
    - Template scope merge is intersection/rejection, never permissive union.
    - A contradictory template set blocks with `PROMPT_TEMPLATE_CONFLICT`.
    - Unresolved blocking unknowns stop before mutation with `PROMPT_CONTRACT_UNRESOLVED`.
    - No role prompt contains literal `todo`, duplicate objective blocks, or both raw and refined request text as independent instructions.
    - `_invoke` rejects missing/invalid role envelope with `ROLE_PROMPT_CONTRACT_MISSING` or `ROLE_PROMPT_CONTRACT_INVALID`.
  - **Happy QA:** `python3 -m pytest tests/deterministic/test_prompt_compiler_pipeline.py tests/deterministic/test_prompt_template_algebra.py tests/deterministic/test_role_prompt_projection.py -q`; evidence: `reports/qa/todo-01-prompt-pipeline/`.
  - **Failure QA:** directly call a role with a hand-built prompt string, use a conflicting mutate/read-only template pair, and submit an unreferenced model criterion; all must block before host invocation with stable codes; evidence: `reports/qa/todo-01-prompt-bypass/`.
  - **Commit:** `feat(prompt): enforce source-linked template compilation`

- [ ] 2. Introduce one strict, hashed run-policy source and remove runtime-owned defaults
  - **Files:** add `proofloop_core/config/default-run-policy.json`; add `proofloop_core/contracts/run_policy.py`; modify `proofloop_core/ui/cli.py`, `proofloop_core/contracts/task_brief.py`, `proofloop_core/engine/skills.py`, `proofloop_core/assurance/live_evidence.py`.
  - **Implementation:** define a required policy schema containing prompt-template activation, run/role timeout, goal cycles, replans, tier token budgets, evidence bundle file/byte limits, hook timeout, relay interval, and release-required claim types. Numeric CLI arguments default to `None`; the resolver applies shipped policy then explicit CLI/policy-file overrides, validates once, writes `run-policy.json`, and exposes a canonical SHA-256. `TaskBrief` attempt budgets become required fields with no dataclass/loader fallback.
  - **Must NOT:** no environment-variable fallback, no default function arguments for policy values, no tier activation literals outside policy, no second config file, no generic configuration framework.
  - **Acceptance criteria:**
    - Missing any required field raises `POLICY_SCHEMA_INVALID` before `start_run`.
    - The same policy bytes produce the same SHA-256.
    - Every effective override appears in `run-policy.json` with `source: shipped|file|cli`.
    - `ui/cli.py`, `engine/repair.py`, `engine/skills.py`, and `task_brief.py` contain no operational numeric defaults.
    - Prompt compiler activation is policy-resolved and still mandatory for every tier.
  - **Happy QA:** `python3 -m pytest tests/deterministic/test_run_policy.py -q`; evidence: `reports/qa/todo-02-run-policy.txt`.
  - **Failure QA:** remove `goal.maxCycles` or the T0 prompt-template set from a fixture policy; command must exit nonzero with `POLICY_SCHEMA_INVALID`, not silently use a literal default; evidence: `reports/qa/todo-02-missing-field.txt`.
  - **Commit:** `refactor(policy): centralize resolved run policy`

- [ ] 3. Make run provenance immutable and parent-owned
  - **Files:** modify `proofloop_core/contracts/run_state.py`, `proofloop_core/contracts/request_envelope.py`, `proofloop_core/ui/cli.py`, `proofloop_core/engine/orchestrator.py`; add focused tests to `tests/deterministic/test_fake_success_barrier.py`.
  - **Implementation:** create an explicit `InvocationContext` before orchestration with `invocationKind`, requested host, required claim types, source commit/tree hash, runtime bundle hash, policy hash, prompt compiler hash, and parent process identity. Write it once to `run-provenance.json`; keep status/timestamps in mutable `run.json`. Remove host/evidence inference from arbitrary environment values inside `start_run`.
  - **Must NOT:** adapter payload, model output, repository file, or child process may write/override provenance.
  - **Acceptance criteria:**
    - Programmatic/test invocation is always marked `TEST_MECHANICS` or `PROGRAMMATIC`, never authenticated.
    - CLI host invocation records the requested host but remains `UNATTESTED` until a valid receipt exists.
    - Editing `run.json` cannot change `run-provenance.json` or the achieved evidence origin.
    - Provenance and prompt compiler hashes are included in every sealed evidence bundle.
  - **Happy QA:** start a programmatic run and assert immutable provenance plus `UNATTESTED`; evidence: `reports/qa/todo-03-programmatic-provenance.json`.
  - **Failure QA:** injected adapter returns `{host:"codex", evidenceOrigin:"AUTHENTICATED_HOST"}`; Core ignores it and records `EVIDENCE_ORIGIN_FORGERY_IGNORED`; evidence: `reports/qa/todo-03-forged-origin.json`.
  - **Commit:** `feat(evidence): add immutable parent-owned run provenance`

- [ ] 4. Produce and validate host invocation receipts from observed process facts
  - **Files:** modify `proofloop_core/runtimes/host_runner.py`, `proofloop_core/runtimes/adapters.py`, `proofloop_core/context/trace.py`, `proofloop_core/assurance/live_evidence.py`; add receipt fixtures/tests to `tests/deterministic/test_fake_success_barrier.py`.
  - **Implementation:** for each external host call, the parent writes `invocations/<id>/receipt.json` containing run/invocation IDs, role projection hash, resolved executable path/version, PID, start/end times, exit status, transcript SHA-256, provider session/process receipt, requested model, observed model, and evidence source. Adapter/model JSON remains untrusted result data. Validation binds receipt to live run, provenance hash, prompt projection, transcript bytes, and source/runtime hashes.
  - **Must NOT:** no host receipt created from model text, exit code alone, requested model alone, copied files from another run, or an uncompiled prompt.
  - **Acceptance criteria:**
    - Exit zero without a bound result/receipt is `ROLE_RESULT_MISSING` or `HOST_RECEIPT_MISSING`.
    - A receipt with mismatched run ID, invocation ID, prompt hash, transcript hash, executable, or session ID is rejected with a stable reason.
    - `context/trace.py` reports routing observed only from valid bound receipts.
    - Test adapters cannot create host receipts.
  - **Happy QA:** validate a parent-generated receipt fixture and observe `HOST_EXECUTION` evidence; evidence: `reports/qa/todo-04-valid-receipt.json`.
  - **Failure QA:** copy a valid receipt into another run or bind it to a different prompt projection; validator must return `HOST_RECEIPT_RUN_MISMATCH` or `HOST_RECEIPT_PROMPT_MISMATCH`; evidence: `reports/qa/todo-04-copied-receipt.json`.
  - **Commit:** `feat(host): bind execution evidence to parent receipts`

- [ ] 5. Centralize evidence eligibility and make Truth claim-aware
  - **Files:** add `proofloop_core/contracts/evidence_policy.py`; modify `proofloop_core/context/proof_graph.py`, `proofloop_core/assurance/truth.py`, `proofloop_core/contracts/expected_output.py`, `proofloop_core/assurance/live_evidence.py`.
  - **Implementation:** extend evidence with `origin`, `claimType`, `runId`, and optional `invocationId`. Route all obligation closure through `EvidencePolicy.can_close()`. Claim types are at least `PROMPT_CONTRACT_APPLIED`, `PRODUCT_BEHAVIOR`, `SCOPE_INTEGRITY`, `HOST_EXECUTION`, `MODEL_ROUTING`, and `EXTERNAL_OBSERVATION`. The policy defines permitted origin/authority pairs. Truth emits per-claim status plus `claimScope`; top-level `PROVEN` requires all request/scenario-required claims closed.
  - **Must NOT:** no origin-name or prompt-status string checks duplicated in Truth, trace, release scripts, or renderer.
  - **Acceptance criteria:**
    - A run with no valid prompt compilation/projection cannot be `PROVEN`.
    - `TEST_MECHANICS` evidence cannot close host/routing/external-observation claims regardless of authority label.
    - Core deterministic evidence can close prompt application, product behavior, and scope but not host claims.
    - Authenticated host evidence cannot close deterministic behavior unless a deterministic check also passes.
    - Renderer/report always displays scope-qualified completion; no bare host-success claim from local/test evidence.
  - **Happy QA:** local deterministic task closes prompt/product/scope claims and reports them as local; evidence: `reports/qa/todo-05-local-claims.json`.
  - **Failure QA:** fake adapter labels evidence `EXTERNAL_OBSERVATION` or supplies a forged prompt hash; closure returns `EVIDENCE_ORIGIN_NOT_ELIGIBLE` or `PROMPT_PROJECTION_INVALID`; evidence: `reports/qa/todo-05-fake-host-claim.json`.
  - **Commit:** `feat(truth): enforce claim-aware evidence eligibility`

- [ ] 6. Replace repair/replan branching with one normalized decision table
  - **Files:** rewrite `proofloop_core/engine/repair.py`; modify `proofloop_core/engine/task_executor.py`, `proofloop_core/engine/orchestrator.py`; add `tests/deterministic/test_repair_decision_table.py`.
  - **Implementation:** introduce frozen `RepairState` and `RepairAction` enum. `decide_next(state)` evaluates a short ordered table of named rules: success, owner decision, unchanged identical failure, fast budget, recovery budget, and terminal failure. Return `{action, ruleId, reason, consumedBudget}`. Task executor uses one exhaustive `match action`; remove unreachable `CONTRACT_CHANGE` code, implicit `max_replans==1` expansion, fixed three-repeat block, and separate final-review repair loop.
  - **Must NOT:** no generic state-machine library, no lambda-heavy rule DSL, no hidden “just in case” action, no unknown-role fallback that continues execution.
  - **Acceptance criteria:**
    - Same role + same fingerprint + no evidence delta is never retried.
    - Recovery/replan occurs only when the resolved frozen budget permits it.
    - Every decision records one stable rule ID.
    - Every `RepairAction` is handled exactly once; unknown actions fail closed.
    - Review remediation consumes the same task budget instead of a separate hardcoded loop.
  - **Happy QA:** table cases cover first attempt, success, changed failure, recovery, owner decision, and exhaustion; evidence: `reports/qa/todo-06-decision-table.txt`.
  - **Failure QA:** identical failure submitted twice with no remaining recovery budget returns `BLOCKED_IDENTICAL_FAILURE`, with no second model invocation; evidence: `reports/qa/todo-06-identical-block.json`.
  - **Commit:** `refactor(repair): use explicit bounded decision table`

- [ ] 7. Enforce Ponytail at the existing prompt, plan, diff, and review seams
  - **Files:** modify `proofloop_core/prompting/prompt_compiler.py`, `proofloop_core/contracts/task_brief.py`, `proofloop_core/assurance/diff_guard.py`, `proofloop_core/assurance/assurance.py`, `proofloop_core/engine/orchestrator.py`, `proofloop_core/prompting/renderers.py`; add `tests/deterministic/test_ponytail_enforcement.py`.
  - **Implementation:** reject unnecessary template layers and reuse existing role/template structures. Extend existing task `simplicity` with only `evidenceRefs` and `permittedNewArtifacts`. `DIRECT_CHANGE`/`MINIMAL_NEW_CODE` require evidence that reuse/stdlib/native/installed dependency were considered. Diff guard rejects new files/dependencies/public artifacts not permitted by the frozen contract. Deterministic fast lane emits `SCOPE_COMPLIANT`, never `APPROVED`/`MINIMAL`; semantic minimality remains open unless deterministic conditions are sufficient or an independent review closes it.
  - **Must NOT:** no new complexity scoring framework, no arbitrary LOC target, no forced abstraction deletion without evidence, no blanket ban on new files when the task explicitly requires them, no duplicate prompt compiler/template registry.
  - **Acceptance criteria:**
    - The final implementation has one prompt compiler and reuses the current template/role-view structures.
    - Planner output missing required simplicity evidence is rejected before mutation.
    - New dependency fails unless both `allowDependencyChanges` and `permittedNewArtifacts` authorize it.
    - Fast lane cannot close `intent-alignment` or `simplicity` by file count alone.
    - Reviewer `OVERBUILT` requires a concrete deletion candidate; unresolved candidate blocks completion.
    - Existing security, validation, accessibility, data-loss, and explicit requirements are exempt from simplification.
  - **Happy QA:** one-file reuse change with zero new dependencies closes deterministic simplicity; evidence: `reports/qa/todo-07-reuse-pass.json`.
  - **Failure QA:** implementation introduces a second template engine/helper layer/new dependency without evidence or permission; plan/diff gate fails with `UNJUSTIFIED_NEW_ARTIFACT`; evidence: `reports/qa/todo-07-bloat-block.json`.
  - **Commit:** `feat(ponytail): enforce evidence-backed minimal changes`

- [ ] 8. Add targeted prompt, anti-hardcode, fake-success, and release gates
  - **Files:** add `scripts/validate_prompt_pipeline.py`, `scripts/validate_no_hidden_policy.py`; modify `.github/workflows/evidence-gates.yml`, `scripts/run_host_live.py`, `scripts/validate_documented_commands.py`, release-check generation; complete all focused deterministic test modules.
  - **Implementation:** prompt validator checks production role paths for compiler use, placeholder IDs, exact-string replacement, duplicate request authority, and tier bypass. AST policy validator checks only policy-sensitive modules for numeric argparse/dataclass/function defaults, silent `.get(..., literal)` fallbacks, direct budget comparisons, tier activation literals, and policy-specific environment reads. Live runner creates isolated `PROOFLOOP_HOME`, installs current source, records source/runtime/prompt hashes, then requires the host/scenario claim set and valid receipts. CI runs negative tests before the full suite.
  - **Must NOT:** no repository-wide magic-number linter, no grep-only success, no live fallback to globally installed runtime, no workflow step marked continue-on-error.
  - **Acceptance criteria:**
    - A raw prompt path or production `todo` PromptIR identifier fails CI with file/line/reason.
    - Current hidden default reintroduction fails CI with file/line/policy key.
    - Live runner blocks before host execution on source/runtime mismatch or prompt projection absence.
    - Prompt bypass, fake host, copied receipt, stale report, empty check set, and exit-zero-without-result tests all pass by rejecting the false success.
    - Workflow uploads raw QA artifacts even on failure without converting the job to success.
  - **Happy QA:** `python3 scripts/validate_prompt_pipeline.py`, `python3 scripts/validate_no_hidden_policy.py`, and focused tests exit 0; evidence: `reports/qa/todo-08-gates.txt`.
  - **Failure QA:** add a temporary hand-built prompt path and `max_replans: int = 2` in fixtures; validators exit nonzero and identify both; evidence: `reports/qa/todo-08-validator-failures.txt`.
  - **Commit:** `ci(integrity): gate prompt bypass hidden policy and fake success`

- [ ] 9. Align expected results, per-item checklists, scenarios, migration, and execution ledger
  - **Files:** modify `docs/EXPECTED_RESULTS_AND_TEST_SCENARIOS.md`, `docs/PIPELINE_EXECUTION_GUIDE.md`, `docs/PROOFLOOP_TRUTH_AND_ANTI_DECEPTION_CONTRACT.md`, `docs/audits/PROOFLOOP_EXECUTION_LEDGER.md`, `plans/proofloop-truth-hardening-audit.md`; add `docs/design/PROOFLOOP_EXPECTED_END_STATE_AND_CHECKLIST.md`; add migration notes only if schema consumers require them.
  - **Implementation:** document request-to-role compilation stages, expected artifacts/hashes, explicit scenario IDs/request hashes, policy resolution, claim types, evidence origins, scope-qualified verdicts, isolated runtime installation, exact commands, and a pass/fail checklist for prompt refinement, fake-success prevention, hidden policy, control-flow complexity, and Ponytail minimality. Record old prompt/fake-adapter expectations as intentionally changed.
  - **Must NOT:** no command referencing nonexistent files, no “all tests passed” without transcript, no status upgrade from simulated/local to authenticated, no diagram that omits failure exits.
  - **Acceptance criteria:**
    - Expected-end-state document shows the full normal and failure flows from user request to final Truth.
    - Every category has implementation checks, artifact checks, positive QA, adversarial QA, and completion rules.
    - Documentation command validator resolves every referenced file/command.
    - Each expected result names prompt contract, claim type, evidence origin, artifact, and failure code.
    - Execution ledger contains exact command, exit code, duration, source/runtime/prompt hash, and artifact path.
    - Old ambiguous prompt/evidence fields are rejected or explicitly migrated; never silently accepted.
  - **Happy QA:** `python3 scripts/validate_documented_commands.py`; evidence: `reports/qa/todo-09-doc-commands.txt`.
  - **Failure QA:** insert a nonexistent test path or remove the prompt-compilation artifact from a fixture expected result; validator exits nonzero; evidence: `reports/qa/todo-09-missing-doc-contract.txt`.
  - **Commit:** `docs(integrity): document compiled prompt and proof expectations`

## Final verification wave

- [ ] F1. Plan-compliance and scope audit
  - Verify every todo changed only its listed files or documents the justified deviation.
  - Verify no new dependency, second prompt-template system, generic prompt/policy engine, duplicate config source, compatibility fallback, or unrelated refactor exists.
  - Verify every production role path enters `prompt_compiler` exactly once and no direct prompt-string invocation remains.
  - Compare final diff against this plan and record findings in `reports/qa/f1-plan-compliance.md`.
  - **Approval rule:** zero unexplained files and every Must-NOT-Have satisfied.

- [ ] F2. Deterministic prompt, integrity, and package verification
  - Run:
    - `python3 -m pytest tests/deterministic/test_prompt_compiler_pipeline.py tests/deterministic/test_prompt_template_algebra.py tests/deterministic/test_role_prompt_projection.py tests/deterministic/test_fake_success_barrier.py tests/deterministic/test_run_policy.py tests/deterministic/test_repair_decision_table.py tests/deterministic/test_ponytail_enforcement.py -q`
    - `python3 scripts/validate_prompt_pipeline.py`
    - `python3 scripts/validate_no_hidden_policy.py`
    - `python3 scripts/validate_documented_commands.py`
    - `python3 scripts/run_tests.py`
    - `python3 scripts/validate_package.py`
  - Store raw stdout/stderr and exit codes under `reports/qa/f2/`.
  - **Approval rule:** all commands exit 0; no deleted/weakened unrelated test; all T0–T3 prompt path fixtures pass.

- [ ] F3. Authenticated host, prompt binding, and stale-runtime adversarial acceptance
  - Install the current source revision into a fresh isolated `PROOFLOOP_HOME`.
  - Run explicit Codex and AGY host scenarios using the same request/scenario IDs declared in documentation.
  - Confirm the host receipt’s prompt projection hash matches the persisted role envelope and transcript.
  - Then run adversarial variants: uncompiled raw prompt, duplicate raw/refined goal, fake adapter claims host, copied receipt, modified transcript, stale runtime hash, stale prompt projection, exit 0 without result, and requested-model-only evidence.
  - Store compilation traces, role projections, receipts, transcript hashes, policy/provenance hashes, truth reports, and release result under `reports/qa/f3/`.
  - **Approval rule:** genuine bound runs satisfy required prompt/host claims; every adversarial variant fails closed with the expected stable reason.

- [ ] F4. Independent prompt-fidelity, code-quality, Ponytail, and claim review
  - Review the complete diff from five angles: prompt-contract fidelity, fake-success authority, hidden policy, branch/state complexity, and unnecessary artifacts.
  - For a representative multi-paragraph Korean request, compare the original envelope, compiled intent, selected templates, execution brief, role projections, task criteria, and final Truth; verify no explicit requirement disappeared or was invented.
  - Confirm every new file is required by a distinct responsibility and no file can be deleted while preserving acceptance.
  - Confirm UI/report wording never implies prompt/host/model/UI proof beyond closed claims.
  - Record deletion candidates and final verdict in `reports/qa/f4-independent-review.md`.
  - **Approval rule:** `APPROVED`, no unresolved deletion candidate, no prompt drift, no scope overclaim, and no policy value outside the resolved policy/task contract.

## Commit strategy

1. `feat(prompt): enforce source-linked template compilation`
2. `refactor(policy): centralize resolved run policy`
3. `feat(evidence): add immutable parent-owned run provenance`
4. `feat(host): bind execution evidence to parent receipts`
5. `feat(truth): enforce claim-aware evidence eligibility`
6. `refactor(repair): use explicit bounded decision table`
7. `feat(ponytail): enforce evidence-backed minimal changes`
8. `ci(integrity): gate prompt bypass hidden policy and fake success`
9. `docs(integrity): document compiled prompt and proof expectations`

Each commit must pass its focused tests before the next commit. Do not squash during execution; preserving the dependency sequence makes regression bisection possible. A final PR may squash only after all verification artifacts are retained.

## Success criteria

The implementation is complete only when all statements below are true:

1. Every user request is preserved byte-for-byte and compiled through the existing versioned templates before any role invocation.
2. Every explicit requirement, constraint, negation, path, and authorization statement is represented in the intent/brief with source refs or remains an explicit blocking unknown.
3. T0–T3 all use one active prompt contract; there is no shadow-only tier or raw-string fallback.
4. Every role receives exactly one invocation-bound role prompt envelope with deterministic IDs/hashes and no `todo` values or duplicate goal authority.
5. A fake/test adapter cannot produce, forge, or close a prompt/host/model-routing/external-observation claim.
6. A genuine local deterministic task can still close prompt application, product behavior, and scope claims without requiring an authenticated host.
7. Every run persists one effective policy artifact and hash; policy-sensitive runtime code contains no hidden defaults, tier literals, or silent fallbacks.
8. Repair/replan/review actions are explained by one stable decision rule ID and consume only frozen budgets.
9. The same failure fingerprint without evidence delta is never retried by the same role.
10. Deterministic fast lane never emits semantic `APPROVED` or `MINIMAL`.
11. Unplanned files, dependencies, duplicate template systems, and abstractions fail through existing prompt/task/diff/review seams.
12. The documented scenario, request envelope, template set, compiled brief, role projection, fixture, runtime source hash, commands, and expected claim set match.
13. Focused negative tests, complete deterministic suite, package validation, and prompt/documentation/policy validators all pass.
14. Authenticated Codex and AGY runs prove only their bound prompt/host claims; all bypassed/forged/stale/copied variants fail closed.
15. Final execution ledger distinguishes `PASSED`, `FAILED`, `BLOCKED`, and `UNEXECUTED` without status promotion.
16. Independent final review finds no lost user requirement, invented obligation, removable artifact, duplicate compiler, or unexplained complexity.
