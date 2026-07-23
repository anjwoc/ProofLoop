# proofloop-integrity-policy-hardening - Work Plan

Status: `READY_FOR_EXECUTION`  
Intent: `CLEAR`  
Review required: `true`  
Target repository: `anjwoc/ProofLoop`  
Target branch: `codex/preserve-eb097dd-with-main`  
Planning method: LazyCodex `ulw-plan` principles — explore first, one decision-complete plan, executor needs zero judgment calls, every todo includes acceptance and happy/failure QA, and completion requires a separate final verification wave.

## TL;DR (For humans)

### What you will get

ProofLoop will use three parent-owned contracts instead of scattered conditionals and hidden defaults:

1. **Evidence Contract** — an adapter or model can submit claims, but only Core-owned evidence with a permitted origin can close a proof obligation.
2. **Run Policy Contract** — timeouts, attempts, replans, token budgets, bundle limits, hook timeouts, and release requirements come from one strict, hashed policy artifact.
3. **Simplicity Contract** — repair routing is table-driven, fast-lane output cannot claim semantic approval/minimality, and Ponytail evidence is required before unnecessary files, dependencies, or abstractions are accepted.

### Why this approach

The current defects share one root cause: policy and authority are implicit. A fake adapter can look like a host, numeric defaults exist in several layers, repair behavior is encoded in nested branches, and minimality is partly asserted by prose. Central contracts remove those ambiguities once instead of adding another defensive `if`.

### What this will NOT do

- It will not remove all conditionals from the codebase.
- It will not move schema versions, hash algorithms, enum values, or internal I/O chunk sizes into user configuration.
- It will not add a generic workflow engine, rules DSL, dependency-injection container, or new third-party package.
- It will not require an authenticated host to prove ordinary local deterministic behavior.
- It will not let local or test evidence prove host execution, model routing, or UI observation.

### Definition of “no hardcoding”

“Hardcoding prohibited” means **no hidden operational or decision policy in runtime code**. Any value that changes execution outcome, resource budget, retry behavior, evidence eligibility, or release acceptance must come from the resolved run policy or the frozen task contract and must be persisted with its source and SHA-256. Protocol constants that do not choose behavior remain named code constants.

### Primary risks

- Truth/report schema consumers must be migrated atomically.
- Existing deterministic tests that treat injected adapters as authenticated hosts must change their expected claim scope.
- Host receipts require source/runtime binding, so live tests will fail until the current branch is installed into an isolated `PROOFLOOP_HOME`.
- Over-generalizing the policy engine would recreate the bloat this plan is intended to prevent.

### Fixed design decisions

| ID | Decision |
| --- | --- |
| D1 | Evidence origin is assigned by the parent Core, never accepted from adapter/model payload. |
| D2 | A test adapter may prove mechanics or local deterministic behavior, but can never close `HOST_EXECUTION`, `MODEL_ROUTING`, or `EXTERNAL_OBSERVATION` obligations. |
| D3 | `PROVEN` means every required obligation is closed by eligible evidence; reports also expose `claimScope` so local success cannot look like host success. |
| D4 | Operational policy has one shipped JSON source, one strict resolver, one canonical hash, and one persisted effective artifact. Runtime functions receive resolved values; they do not own defaults. |
| D5 | Repair routing uses one normalized state and an ordered decision table with stable rule IDs. The task executor dispatches an enum with one exhaustive `match`, not repeated defensive branches. |
| D6 | Repeated identical failure with no evidence delta is never retried by the same role. Recovery/replan can occur only when the frozen task/run policy has remaining budget. |
| D7 | Deterministic fast lane may assert only `CHECKS_PASS` and `SCOPE_COMPLIANT`; it cannot emit `APPROVED` or `MINIMAL`. |
| D8 | Ponytail enforcement reuses existing `TaskBrief.simplicity` and `ChangeBudget`; only the minimum new evidence fields are added. No separate complexity framework is introduced. |

## Scope

### In scope

- Parent-owned run provenance and host invocation receipts.
- Evidence-origin eligibility in the proof graph and Truth Gate.
- Single-source execution policy and removal of policy defaults from runtime functions/CLI.
- Table-driven repair decisions and removal of unreachable/redundant branches.
- Deterministic Ponytail gates for task planning, diff scope, dependencies, new files, and semantic review.
- Negative tests that deliberately forge host/model/report evidence.
- Isolated live-host acceptance with current-source/current-runtime binding.
- CI gates and documentation aligned with real commands.

### Out of scope / Must-NOT-Have

- No new external dependency.
- No generic policy language or expression evaluator.
- No factory/interface with one implementation.
- No provider-specific authentication implementation inside ProofLoop.
- No automatic retry added beyond the frozen policy.
- No global cyclomatic-complexity threshold for every repository file.
- No model self-report accepted as evidence of host, model, command, test, elapsed time, or completion.
- No compatibility shim that silently accepts the old ambiguous evidence format.
- No “temporary” fallback from authenticated-host validation to local/test evidence.

## Verification strategy

### Baseline and red-first order

1. Add negative tests first. They must fail against the current implementation for the expected reason.
2. Implement the smallest shared contract that makes those tests pass.
3. Run focused tests after each todo.
4. Run the complete deterministic suite and package validation.
5. Install the exact source revision into an isolated `PROOFLOOP_HOME`.
6. Run authenticated Codex and AGY acceptance only after deterministic gates pass.
7. Keep `UNEXECUTED`, `BLOCKED`, `FAILED`, and `PASSED` separate in the execution ledger.

### Evidence requirements

| Claim | Minimum evidence |
| --- | --- |
| Code behavior | Core-sealed deterministic check bound to current source revision |
| Diff/scope | Core diff guard bound to task contract and baseline |
| Host process executed | Parent-owned host receipt with executable, process, transcript, run, and session binding |
| Model routing observed | Host receipt or ACP session evidence bound to the same invocation |
| UI/browser behavior | Recorded external observation produced by a declared surface scenario |
| Minimality | Frozen simplicity decision + diff facts; model review only when deterministic facts cannot close it |
| Release ready | All required claims closed, current source/runtime hashes match, deterministic suite/package gates pass |

### Planned evidence paths

- `.proofloop/runs/<run-id>/run-policy.json`
- `.proofloop/runs/<run-id>/run-provenance.json`
- `.proofloop/runs/<run-id>/invocations/<invocation-id>/receipt.json`
- `.proofloop/runs/<run-id>/core-evidence/`
- `.proofloop/runs/<run-id>/truth-report.json`
- `reports/release-check.json`
- `reports/live/<scenario>/<host>/`

## Execution strategy

### Wave 1 — authority and policy foundations

Todos 1–3 introduce strict policy, immutable provenance, and parent-owned invocation receipts. No Truth behavior changes before these artifacts exist.

### Wave 2 — closure and state-machine integration

Todos 4–5 route all proof closure through the evidence contract and replace repair branching with one decision table.

### Wave 3 — Ponytail and release enforcement

Todos 6–8 remove semantic fake approvals, enforce minimality at existing seams, bind live acceptance to current runtime, and align CI/docs.

### Dependency matrix

| Todo | Depends on |
| --- | --- |
| 1 | none |
| 2 | 1 |
| 3 | 1, 2 |
| 4 | 2, 3 |
| 5 | 1 |
| 6 | 1, 4, 5 |
| 7 | 3, 4, 6 |
| 8 | 1–7 |

## File change matrix

| File | Exact modification | Expected result |
| --- | --- | --- |
| `proofloop_core/config/default-run-policy.json` (new) | Store all operational budgets and evidence/release requirements with schema/policy version. | One visible shipped policy replaces scattered runtime defaults. |
| `proofloop_core/contracts/run_policy.py` (new) | Strict dataclasses/enums, canonical hash, override merge, no missing-field fallback. | Missing/invalid policy fails before a run starts. |
| `proofloop_core/ui/cli.py` | Numeric argparse defaults become `None`; resolve policy once; pass explicit invocation context. | CLI, orchestrator, role runner, and live harness use the same values. |
| `proofloop_core/contracts/task_brief.py` | Remove attempt defaults; require explicit budgets; strengthen existing simplicity contract with evidence refs and permitted new artifacts. | Planner cannot omit retry/minimality decisions. |
| `proofloop_core/engine/skills.py` | Read tier token budgets from resolved policy. | Skill allocation no longer owns hardcoded tier budgets. |
| `proofloop_core/assurance/live_evidence.py` | Read evidence bundle limits from resolved policy snapshot; seal policy/provenance/receipts. | Bundle validation is revision- and policy-bound. |
| `proofloop_core/contracts/run_state.py` | Remove environment/argv inference; write mutable run state separately from immutable provenance. | Adapter/environment spoofing cannot rewrite evidence origin. |
| `proofloop_core/contracts/request_envelope.py` | Record required claim classes/scopes selected by Core command/scenario, not the model. | Host claims are explicit obligations, not inferred from successful exit. |
| `proofloop_core/context/proof_graph.py` | Add evidence `origin`, `claimType`, `runId`, `invocationId`; delegate closure to central eligibility policy. | Authority level alone can no longer let fake/test evidence close host claims. |
| `proofloop_core/contracts/evidence_policy.py` (new) | Define allowed origin/authority combinations per claim type and stable rejection reasons. | One closure rule replaces scattered origin string checks. |
| `proofloop_core/runtimes/host_runner.py` | Parent writes receipt from the actual child process and transcript; include executable/version/PID/session/hash/timestamps. | Host evidence comes from observed process facts. |
| `proofloop_core/runtimes/adapters.py` | Treat returned payload as untrusted role output; adapter cannot set origin/scope/receipt. | A fake adapter may supply work output but not promote its evidence class. |
| `proofloop_core/context/trace.py` | Accept observed model only when linked to a valid invocation receipt. | Copied or free-floating model strings do not prove routing. |
| `proofloop_core/assurance/truth.py` | Compute claim closure from proof graph; expose claim summary and reject insufficient origin/scope. | `PROVEN` cannot hide unproven host/routing claims. |
| `proofloop_core/contracts/expected_output.py` | Render scope-qualified results and stable blockers. | UI says local/mechanics/authenticated explicitly. |
| `proofloop_core/engine/repair.py` | Replace defaulted nested decisions with `RepairState`, `RepairAction`, ordered rules, and stable rule IDs. | One deterministic decision per state; no magic repeat count. |
| `proofloop_core/engine/task_executor.py` | Build normalized repair state; exhaustive `match` dispatch; remove unreachable `CONTRACT_CHANGE` block and implicit replan expansion. | No repeated if/else defense maze; policy decides budgets. |
| `proofloop_core/engine/orchestrator.py` | Remove fixed final-review loops and fast-lane semantic approval; consume policy and proof eligibility. | Review cannot bypass task budgets or auto-claim minimality. |
| `proofloop_core/assurance/diff_guard.py` | Enforce planned new files/dependencies against existing change/simplicity contract. | Unplanned abstractions/dependencies fail deterministically. |
| `proofloop_core/assurance/assurance.py` | Keep `SCOPE_COMPLIANT` separate from semantic `APPROVED`/`MINIMAL`. | Passing file-count checks does not become semantic approval. |
| `scripts/run_host_live.py` | Create isolated runtime home, install current source, verify source/runtime hash, require host receipts. | Live acceptance cannot execute an old global Core. |
| `scripts/validate_no_hidden_policy.py` (new) | AST-check policy-sensitive modules for numeric defaults, silent fallback, and direct policy comparisons. | CI detects newly reintroduced hidden policy. |
| `scripts/validate_documented_commands.py` | Validate the revised real command set and scenario IDs. | Documentation cannot reference nonexistent tests/fixtures. |
| `.github/workflows/evidence-gates.yml` | Run focused negative gates, no-hidden-policy validator, full deterministic suite, package validator. | Pull requests expose fake-success/policy regressions. |
| `tests/deterministic/test_fake_success_barrier.py` (new) | Forged adapter/host/model/copied receipt/stale report cases. | Every fake-success route has a failing regression test. |
| `tests/deterministic/test_run_policy.py` (new) | Strict policy load, overrides, hash, missing fields, no defaults. | Effective policy is reproducible and inspectable. |
| `tests/deterministic/test_repair_decision_table.py` (new) | Rule coverage, no same-role identical retry, exhaustive action dispatch. | Repair behavior is bounded and explainable by rule ID. |
| `tests/deterministic/test_ponytail_enforcement.py` (new) | Fast-lane semantics, new dependency/file, simplicity evidence, deletion candidate. | Bloat cannot be approved by scope checks alone. |
| `docs/EXPECTED_RESULTS_AND_TEST_SCENARIOS.md` | Replace ambiguous `normal` scenario with explicit IDs and real commands. | Documented scenario equals executed fixture. |
| `docs/PIPELINE_EXECUTION_GUIDE.md` | Document policy source/hash and scope-qualified verdicts. | Operators can reproduce effective limits. |
| `docs/PROOFLOOP_TRUTH_AND_ANTI_DECEPTION_CONTRACT.md` | Update normative evidence eligibility and release rules. | Prose matches executable policy. |
| `docs/audits/PROOFLOOP_EXECUTION_LEDGER.md` | Record every command/result/artifact without status promotion. | Final report remains auditable. |

## Todos

- [ ] 1. Introduce one strict, hashed run-policy source and remove runtime-owned defaults
  - **Files:** add `proofloop_core/config/default-run-policy.json`; add `proofloop_core/contracts/run_policy.py`; modify `proofloop_core/ui/cli.py`, `proofloop_core/contracts/task_brief.py`, `proofloop_core/engine/skills.py`, `proofloop_core/assurance/live_evidence.py`.
  - **Implementation:** define a required policy schema containing run/role timeout, goal cycles, replans, tier token budgets, evidence bundle file/byte limits, hook timeout, relay interval, and release-required claim types. Numeric CLI arguments default to `None`; the resolver applies shipped policy then explicit CLI/policy-file overrides, validates once, writes `run-policy.json`, and exposes a canonical SHA-256. `TaskBrief` attempt budgets become required fields with no dataclass/loader fallback.
  - **Must NOT:** no environment-variable fallback, no default function arguments for policy values, no second config file, no generic configuration framework.
  - **Acceptance criteria:**
    - Missing any required field raises `POLICY_SCHEMA_INVALID` before `start_run`.
    - The same policy bytes produce the same SHA-256.
    - Every effective override appears in `run-policy.json` with `source: shipped|file|cli`.
    - `ui/cli.py`, `engine/repair.py`, `engine/skills.py`, and `task_brief.py` contain no operational numeric defaults.
  - **Happy QA:** `python3 -m pytest tests/deterministic/test_run_policy.py -q`; evidence: `reports/qa/todo-01-run-policy.txt`.
  - **Failure QA:** remove `goal.maxCycles` from a fixture policy; command must exit nonzero with `POLICY_SCHEMA_INVALID`, not silently use `8`; evidence: `reports/qa/todo-01-missing-field.txt`.
  - **Commit:** `refactor(policy): centralize resolved run policy`

- [ ] 2. Make run provenance immutable and parent-owned
  - **Files:** modify `proofloop_core/contracts/run_state.py`, `proofloop_core/contracts/request_envelope.py`, `proofloop_core/ui/cli.py`, `proofloop_core/engine/orchestrator.py`; add focused tests to `tests/deterministic/test_fake_success_barrier.py`.
  - **Implementation:** create an explicit `InvocationContext` before orchestration with `invocationKind`, requested host, required claim types, source commit/tree hash, runtime bundle hash, policy hash, and parent process identity. Write it once to `run-provenance.json`; keep status/timestamps in mutable `run.json`. Remove host/evidence inference from arbitrary environment values inside `start_run`.
  - **Must NOT:** adapter payload, model output, repository file, or child process may write/override provenance.
  - **Acceptance criteria:**
    - Programmatic/test invocation is always marked `TEST_MECHANICS` or `PROGRAMMATIC`, never authenticated.
    - CLI host invocation records the requested host but remains `UNATTESTED` until a valid receipt exists.
    - Editing `run.json` cannot change `run-provenance.json` or the achieved evidence origin.
    - Provenance hash is included in every sealed evidence bundle.
  - **Happy QA:** start a programmatic run and assert immutable provenance plus `UNATTESTED`; evidence: `reports/qa/todo-02-programmatic-provenance.json`.
  - **Failure QA:** injected adapter returns `{host:"codex", evidenceOrigin:"AUTHENTICATED_HOST"}`; Core ignores it and records `EVIDENCE_ORIGIN_FORGERY_IGNORED`; evidence: `reports/qa/todo-02-forged-origin.json`.
  - **Commit:** `feat(evidence): add immutable parent-owned run provenance`

- [ ] 3. Produce and validate host invocation receipts from observed process facts
  - **Files:** modify `proofloop_core/runtimes/host_runner.py`, `proofloop_core/runtimes/adapters.py`, `proofloop_core/context/trace.py`, `proofloop_core/assurance/live_evidence.py`; add receipt fixtures/tests to `tests/deterministic/test_fake_success_barrier.py`.
  - **Implementation:** for each external host call, the parent writes `invocations/<id>/receipt.json` containing run/invocation IDs, resolved executable path/version, PID, start/end times, exit status, transcript SHA-256, provider session/process receipt, requested model, observed model, and evidence source. Adapter/model JSON remains untrusted result data. Validation binds receipt to live run, provenance hash, transcript bytes, and source/runtime hashes.
  - **Must NOT:** no host receipt created from model text, exit code alone, requested model alone, or copied files from another run.
  - **Acceptance criteria:**
    - Exit zero without a bound result/receipt is `ROLE_RESULT_MISSING` or `HOST_RECEIPT_MISSING`.
    - A receipt with mismatched run ID, invocation ID, transcript hash, executable, or session ID is rejected with a stable reason.
    - `context/trace.py` reports routing observed only from valid bound receipts.
    - Test adapters cannot create host receipts.
  - **Happy QA:** validate a parent-generated receipt fixture and observe `HOST_EXECUTION` evidence; evidence: `reports/qa/todo-03-valid-receipt.json`.
  - **Failure QA:** copy a valid receipt into another run; validator must return `HOST_RECEIPT_RUN_MISMATCH`; evidence: `reports/qa/todo-03-copied-receipt.json`.
  - **Commit:** `feat(host): bind execution evidence to parent receipts`

- [ ] 4. Centralize evidence eligibility and make Truth claim-aware
  - **Files:** add `proofloop_core/contracts/evidence_policy.py`; modify `proofloop_core/context/proof_graph.py`, `proofloop_core/assurance/truth.py`, `proofloop_core/contracts/expected_output.py`, `proofloop_core/assurance/live_evidence.py`.
  - **Implementation:** extend evidence with `origin`, `claimType`, `runId`, and optional `invocationId`. Route all obligation closure through `EvidencePolicy.can_close()`. Claim types are at least `PRODUCT_BEHAVIOR`, `SCOPE_INTEGRITY`, `HOST_EXECUTION`, `MODEL_ROUTING`, and `EXTERNAL_OBSERVATION`. The policy defines permitted origin/authority pairs. Truth emits per-claim status plus `claimScope`; top-level `PROVEN` requires all request/scenario-required claims closed.
  - **Must NOT:** no origin-name string checks duplicated in Truth, trace, release scripts, or renderer.
  - **Acceptance criteria:**
    - `TEST_MECHANICS` evidence cannot close host/routing/external-observation claims regardless of authority label.
    - Core deterministic evidence can close product behavior/scope but not host claims.
    - Authenticated host evidence cannot close deterministic behavior unless a deterministic check also passes.
    - Renderer/report always displays scope-qualified completion; no bare host-success claim from local/test evidence.
  - **Happy QA:** local deterministic task closes product/scope claims and reports them as local; evidence: `reports/qa/todo-04-local-claims.json`.
  - **Failure QA:** fake adapter labels evidence `EXTERNAL_OBSERVATION`; closure returns `EVIDENCE_ORIGIN_NOT_ELIGIBLE` and Truth remains non-PROVEN for the host scenario; evidence: `reports/qa/todo-04-fake-host-claim.json`.
  - **Commit:** `feat(truth): enforce claim-aware evidence eligibility`

- [ ] 5. Replace repair/replan branching with one normalized decision table
  - **Files:** rewrite `proofloop_core/engine/repair.py`; modify `proofloop_core/engine/task_executor.py`, `proofloop_core/engine/orchestrator.py`; add `tests/deterministic/test_repair_decision_table.py`.
  - **Implementation:** introduce frozen `RepairState` and `RepairAction` enum. `decide_next(state)` evaluates a short ordered table of named rules: success, owner decision, unchanged identical failure, fast budget, recovery budget, and terminal failure. Return `{action, ruleId, reason, consumedBudget}`. Task executor uses one exhaustive `match action`; remove unreachable `CONTRACT_CHANGE` code, implicit `max_replans==1` expansion, fixed three-repeat block, and separate final-review repair loop.
  - **Must NOT:** no generic state-machine library, no lambda-heavy rule DSL, no hidden “just in case” action, no unknown-role fallback that continues execution.
  - **Acceptance criteria:**
    - Same role + same fingerprint + no evidence delta is never retried.
    - Recovery/replan occurs only when the resolved frozen budget permits it.
    - Every decision records one stable rule ID.
    - Every `RepairAction` is handled exactly once; unknown actions fail closed.
    - Review remediation consumes the same task budget instead of a separate hardcoded loop.
  - **Happy QA:** table cases cover first attempt, success, changed failure, recovery, owner decision, and exhaustion; evidence: `reports/qa/todo-05-decision-table.txt`.
  - **Failure QA:** identical failure submitted twice with no remaining recovery budget returns `BLOCKED_IDENTICAL_FAILURE`, with no second model invocation; evidence: `reports/qa/todo-05-identical-block.json`.
  - **Commit:** `refactor(repair): use explicit bounded decision table`

- [ ] 6. Enforce Ponytail at the existing plan, diff, and review seams
  - **Files:** modify `proofloop_core/contracts/task_brief.py`, `proofloop_core/assurance/diff_guard.py`, `proofloop_core/assurance/assurance.py`, `proofloop_core/engine/orchestrator.py`, `proofloop_core/prompting/renderers.py`; add `tests/deterministic/test_ponytail_enforcement.py`.
  - **Implementation:** extend existing `simplicity` with only `evidenceRefs` and `permittedNewArtifacts`. `DIRECT_CHANGE`/`MINIMAL_NEW_CODE` require evidence that reuse/stdlib/native/installed dependency were considered. Diff guard rejects new files/dependencies/public artifacts not permitted by the frozen contract. Deterministic fast lane emits `SCOPE_COMPLIANT`, never `APPROVED`/`MINIMAL`; semantic minimality remains open unless deterministic conditions are sufficient or an independent review closes it.
  - **Must NOT:** no new complexity scoring framework, no arbitrary LOC target, no forced abstraction deletion without evidence, no blanket ban on new files when the task explicitly requires them.
  - **Acceptance criteria:**
    - Planner output missing required simplicity evidence is rejected before mutation.
    - New dependency fails unless both `allowDependencyChanges` and `permittedNewArtifacts` authorize it.
    - Fast lane cannot close `intent-alignment` or `simplicity` by file count alone.
    - Reviewer `OVERBUILT` requires a concrete deletion candidate; unresolved candidate blocks completion.
    - Existing security, validation, accessibility, data-loss, and explicit requirements are exempt from simplification.
  - **Happy QA:** one-file reuse change with zero new dependencies closes deterministic simplicity; evidence: `reports/qa/todo-06-reuse-pass.json`.
  - **Failure QA:** planner proposes a helper layer/new dependency without evidence or permission; plan/diff gate fails with `UNJUSTIFIED_NEW_ARTIFACT`; evidence: `reports/qa/todo-06-bloat-block.json`.
  - **Commit:** `feat(ponytail): enforce evidence-backed minimal changes`

- [ ] 7. Add targeted anti-hardcode, fake-success, and release gates
  - **Files:** add `scripts/validate_no_hidden_policy.py`; modify `.github/workflows/evidence-gates.yml`, `scripts/run_host_live.py`, `scripts/validate_documented_commands.py`, release-check generation; complete the four focused deterministic test modules.
  - **Implementation:** AST validator checks only policy-sensitive modules for numeric argparse/dataclass/function defaults, silent `.get(..., literal)` fallbacks, direct budget comparisons, and policy-specific environment reads. Live runner creates isolated `PROOFLOOP_HOME`, installs current source, records source/runtime hashes, then requires the host/scenario claim set and valid receipts. CI runs negative tests before the full suite.
  - **Must NOT:** no repository-wide magic-number linter, no grep-only success, no live fallback to globally installed runtime, no workflow step marked continue-on-error.
  - **Acceptance criteria:**
    - Current hidden default reintroduction fails CI with file/line/policy key.
    - Live runner blocks before host execution on source/runtime mismatch.
    - Fake host, copied receipt, stale report, empty check set, and exit-zero-without-result tests all pass by rejecting the false success.
    - Workflow uploads raw QA artifacts even on failure without converting the job to success.
  - **Happy QA:** `python3 scripts/validate_no_hidden_policy.py` and focused tests exit 0; evidence: `reports/qa/todo-07-gates.txt`.
  - **Failure QA:** add temporary `max_replans: int = 2` in a fixture module; validator exits nonzero and identifies it; evidence: `reports/qa/todo-07-hidden-default.txt`.
  - **Commit:** `ci(integrity): gate hidden policy and fake success`

- [ ] 8. Align documented scenarios, migration, and execution ledger with the executable contracts
  - **Files:** modify `docs/EXPECTED_RESULTS_AND_TEST_SCENARIOS.md`, `docs/PIPELINE_EXECUTION_GUIDE.md`, `docs/PROOFLOOP_TRUTH_AND_ANTI_DECEPTION_CONTRACT.md`, `docs/audits/PROOFLOOP_EXECUTION_LEDGER.md`, `plans/proofloop-truth-hardening-audit.md`; add migration notes only if schema consumers require them.
  - **Implementation:** replace ambiguous `normal` with explicit scenario IDs and request hashes; document policy resolution, claim types, evidence origins, scope-qualified verdicts, isolated runtime installation, and exact commands. Record old test-adapter `PROVEN` expectations as intentionally changed where they represented host claims.
  - **Must NOT:** no command referencing nonexistent files, no “all tests passed” without transcript, no status upgrade from simulated/local to authenticated.
  - **Acceptance criteria:**
    - Documentation command validator resolves every referenced file/command.
    - Each expected result names claim type, evidence origin, artifact, and failure code.
    - Execution ledger contains exact command, exit code, duration, source/runtime hash, and artifact path.
    - Old ambiguous evidence fields are rejected or explicitly migrated; never silently accepted.
  - **Happy QA:** `python3 scripts/validate_documented_commands.py`; evidence: `reports/qa/todo-08-doc-commands.txt`.
  - **Failure QA:** insert a nonexistent test path into a fixture copy of the document; validator exits nonzero; evidence: `reports/qa/todo-08-missing-doc-path.txt`.
  - **Commit:** `docs(integrity): align scenarios with executable proof`

## Final verification wave

- [ ] F1. Plan-compliance and scope audit
  - Verify every todo changed only its listed files or documents the justified deviation.
  - Verify no new dependency, generic policy engine, duplicate config source, compatibility fallback, or unrelated refactor exists.
  - Compare final diff against this plan and record findings in `reports/qa/f1-plan-compliance.md`.
  - **Approval rule:** zero unexplained files and every Must-NOT-Have satisfied.

- [ ] F2. Deterministic integrity and package verification
  - Run:
    - `python3 -m pytest tests/deterministic/test_fake_success_barrier.py tests/deterministic/test_run_policy.py tests/deterministic/test_repair_decision_table.py tests/deterministic/test_ponytail_enforcement.py -q`
    - `python3 scripts/validate_no_hidden_policy.py`
    - `python3 scripts/validate_documented_commands.py`
    - `python3 scripts/run_tests.py`
    - `python3 scripts/validate_package.py`
  - Store raw stdout/stderr and exit codes under `reports/qa/f2/`.
  - **Approval rule:** all commands exit 0; no deleted/weakened unrelated test.

- [ ] F3. Authenticated host and stale-runtime adversarial acceptance
  - Install the current source revision into a fresh isolated `PROOFLOOP_HOME`.
  - Run explicit Codex and AGY host scenarios using the same request/scenario IDs declared in documentation.
  - Then run adversarial variants: fake adapter claims host, copied receipt, modified transcript, stale runtime hash, exit 0 without result, and requested-model-only evidence.
  - Store receipts, transcript hashes, policy/provenance hashes, truth reports, and release result under `reports/qa/f3/`.
  - **Approval rule:** genuine bound runs satisfy required host claims; every adversarial variant fails closed with the expected stable reason.

- [ ] F4. Independent code-quality, Ponytail, and claim-fidelity review
  - Review the complete diff from four angles: fake-success authority, hidden policy, branch/state complexity, and unnecessary artifacts.
  - Confirm every new file is required by a distinct responsibility and no file can be deleted while preserving acceptance.
  - Confirm UI/report wording never implies host/model/UI proof beyond closed claims.
  - Record deletion candidates and final verdict in `reports/qa/f4-independent-review.md`.
  - **Approval rule:** `APPROVED`, no unresolved deletion candidate, no scope overclaim, and no policy value outside the resolved policy/task contract.

## Commit strategy

1. `refactor(policy): centralize resolved run policy`
2. `feat(evidence): add immutable parent-owned run provenance`
3. `feat(host): bind execution evidence to parent receipts`
4. `feat(truth): enforce claim-aware evidence eligibility`
5. `refactor(repair): use explicit bounded decision table`
6. `feat(ponytail): enforce evidence-backed minimal changes`
7. `ci(integrity): gate hidden policy and fake success`
8. `docs(integrity): align scenarios with executable proof`

Each commit must pass its focused tests before the next commit. Do not squash during execution; preserving the dependency sequence makes regression bisection possible. A final PR may squash only after all verification artifacts are retained.

## Success criteria

The implementation is complete only when all statements below are true:

1. A fake/test adapter cannot produce, forge, or close a host/model-routing/external-observation claim.
2. A genuine local deterministic task can still close product behavior and scope claims without requiring an authenticated host.
3. Every run persists one effective policy artifact and hash; policy-sensitive runtime code contains no hidden defaults or silent fallbacks.
4. Repair/replan/review actions are explained by one stable decision rule ID and consume only frozen budgets.
5. The same failure fingerprint without evidence delta is never retried by the same role.
6. Deterministic fast lane never emits semantic `APPROVED` or `MINIMAL`.
7. Unplanned files, dependencies, and abstractions fail through existing task/diff/review seams.
8. The documented scenario, fixture, request hash, runtime source hash, commands, and expected claim set match.
9. Focused negative tests, complete deterministic suite, package validation, and documentation/policy validators all pass.
10. Authenticated Codex and AGY runs prove only their bound host claims; all forged/stale/copied variants fail closed.
11. Final execution ledger distinguishes `PASSED`, `FAILED`, `BLOCKED`, and `UNEXECUTED` without status promotion.
12. Independent final review finds no removable artifact or unexplained complexity.
