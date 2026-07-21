# ProofLoop V2 Remediation Plan

Status: execution approved; completion is evidence-gated  
Source review: 2026-07-21 CodeGraph index + full test and adversarial replay

## 1. Objective

Bring the V2 implementation into alignment with `PROOFLOOP_ARCHITECTURE_V2.md` without treating
schemas, mocked adapters, or model claims as proof of runtime behavior.

The migration is complete only when the real default execution path enforces the contract. A module
that is merely importable or unit-tested is not considered integrated.

## 2. Non-negotiable invariants

1. The raw request is the authority boundary. Refinement may narrow or clarify it, never widen it.
2. `OWNER_DECISION_REQUIRED` and `BLOCKED` stop before any repository mutation.
3. Repository text is untrusted data. Injection signals are recorded without becoming instructions.
4. A model-proposed command is a verification candidate, not authoritative evidence.
5. An acceptance criterion closes only through criterion-linked, Core-approved, fresh evidence.
6. Changing relevant source, contract, scope, or test inputs invalidates downstream evidence.
7. `PROVEN` requires Core-owned checks, scope integrity, required independent review, and a closed
   proof graph. Missing proof produces `PARTIAL` or `BLOCKED`, never optimistic success.
8. Benchmark arms must execute materially different policies while holding documented variables
   constant. Renaming identical runs is not a comparison.
9. Simulated host tests prove mechanics only. Cross-host claims require authenticated live artifacts.
10. The repository's official test command must execute every test style used by the project.

## 3. Work packages

### P0-A — Restore an honest development gate

Changes:

- Replace `unittest` discovery in `scripts/run_tests.py` with `pytest` over deterministic and
  orchestration suites.
- Keep one canonical test command in `Makefile`, release check, and documentation.
- Add a guard test proving top-level pytest functions are included.
- Make the current four host/runtime failures visible as real blockers until their contracts are
  resolved; do not label a red suite as deterministic PASS.

Done when:

- `python3 scripts/run_tests.py` and direct pytest report the same collected/passed/failed counts.
- IntentGate and Grounding tests are present in the official collection.
- Release check cannot report deterministic PASS when the official suite is red.

### P0-B — Enforce IntentGate and repository-data boundaries

Changes:

- Persist IntentGate evidence, then stop immediately on `OWNER_DECISION_REQUIRED` or `BLOCKED`.
- Map authority to allowed operations and check it at mutation, local Git, remote Git, and external
  side-effect boundaries.
- Scan grounded instruction/context files for injection signals using bounded deterministic rules.
- Store injection findings as `{path, ruleId, contentHash}`; do not copy secret-bearing text into
  events.
- Emit `grounding.injection_detected` while keeping the repository text as data.

Done when adversarial end-to-end tests prove:

- An owner-decision request produces `BLOCKED`, invokes no mutating role, and leaves the worktree
  unchanged.
- Analyze/plan requests cannot mutate even if a downstream adapter attempts to do so.
- A hostile README/AGENTS file produces an injection event, does not expand authority, and cannot
  alter the execution contract.

### P0-C — Replace model-selected checks with Evidence Authority

Design authority: high-performance architecture plus independent adversarial review.

Changes:

- Introduce a Core-owned `VerificationPlan` compiled before mutation from:
  - user-explicit checks;
  - benchmark/fixture official evaluators;
  - repository-declared scripts and manifests;
  - deterministic framework adapters;
  - model proposals marked `CANDIDATE`, never authoritative by themselves.
- Give every check a stable `checkId`, `source`, `authority`, `criterionIds`, command digest, repo
  baseline, and freshness inputs.
- Reject or downgrade trivial/self-referential checks such as unconditional `python -c pass` when
  they are the only evidence for behavioral criteria.
- Run mandatory checks from the Core-owned plan. TaskBrief checks may request additions but cannot
  remove or replace mandatory checks.
- Close each acceptance criterion only with matching check/surface evidence. Do not close all `AC-*`
  obligations from one aggregate PASS.
- Wire `live_evidence.validate_bundle` into evidence ingestion and Truth Engine evaluation.

Done when:

- The known weak-check reproduction returns `PARTIAL`, `BLOCKED`, or `FAILED` while the real test is
  failing; it can never return `PROVEN`.
- Prior-commit evidence, post-change stale evidence, tampered output, and unexecuted-command claims
  cannot close an obligation.
- At least one positive fixture reaches `PROVEN` through criterion-linked Core evidence.

### P0-D — Complete Grounding → Compiler → Blueprint activation

Changes:

- Serialize the complete bounded GroundingSnapshot: instruction/manifests hashes, relevant files,
  detected commands, languages/frameworks/test surfaces, dirty paths, and unresolved questions.
- Remove invented host capabilities from Grounding; reference the capability contract instead.
- Feed the GroundingSnapshot into the execution-brief composer.
- Run deterministic reconciliation and persist its report before activating a compiled brief.
- Make compiler activation an explicit versioned policy, with T2/T3 enabled only after shadow and
  adversarial gates pass.
- Generate PromptIR from RoleView fields rather than string replacement.
- Align planner output schema with Blueprint validation (`criterionIds`, proof plan, dependencies,
  scope and escalation data).
- Execute ProofPlan checks and surface scenarios instead of merely parsing them.

Done when:

- A real T2 fixture follows the advertised planner schema and reaches execution rather than
  `BLUEPRINT_VALIDATION_FAILED`.
- Invented criteria, widened authority, unknown criterion links, and missing mandatory proof mapping
  fail closed.

### P1-A — Implement truthful benchmark arms

Arm contracts:

- A: current raw ProofLoop path.
- B: deterministic normalization only.
- C: raw meta-model refinement without grounding.
- D: grounded refinement with generic renderer.
- E: D plus model-specific renderer.
- F: fixed large-directive baseline.

Changes:

- Give each arm an explicit execution-policy object and stable policy hash.
- Make schedule, executor, comparison, and promotion code use the same arm IDs.
- Record controlled variables: repo revision, host, model, seed, budgets, evaluator version, and
  renderer/compiler versions.
- Derive false-PROVEN from official evaluator disagreement; never default a missing metric to zero.
- Require at least 30 valid paired scenarios across at least two repository types before promotion.

Done when:

- A test asserts all six arms resolve to distinct intended policy configurations.
- A real small fixture produces comparable baseline/candidate groups and non-empty paired metrics.
- Identical policy hashes across supposedly different arms invalidate the experiment.

### P1-B — Host capability, renderer, and live evidence

Changes:

- Separate declared, requested, acknowledged, observed, and authenticated capability evidence.
- Populate required capabilities from Blueprint/VerificationPlan instead of passing an empty list.
- Apply downgrade/fallback decisions to the actual invocation; otherwise block.
- Implement and version generic, GPT-5.6, Claude Code, and AGY renderers while preserving identical
  semantic contract and authority fields.
- Persist `prompt-manifest.jsonl` with IR hash, renderer/version, role, runtime, model request, and
  rendered prompt hash.
- Obtain normal and recovery live evidence for Codex, Claude Code, and Antigravity.

Done when:

- Unsupported features are visibly downgraded or blocked and are never still invoked as requested.
- Renderer parity tests prove semantic equivalence.
- Cross-host claims are made only from authenticated live artifacts.

### P2 — Quality and release closure

- Remove debug-only artifacts from the deliverable.
- Resolve host frontmatter and Gemini/Antigravity runtime identity contracts.
- Make Ruff, mypy, `git diff --check`, package validation, and full pytest green.
- Rewrite `MIGRATION_PROGRESS.md` from executed evidence; remove checkbox-only completion claims.
- Keep overall release `FAIL` until required live gates pass.

## 4. Model allocation

Use high-performance reasoning for:

- Evidence Authority and Truth Engine contracts.
- Intent/authorization boundary review.
- Freshness and invalidation rules.
- Compiler/reconciler authority preservation.
- Benchmark experimental design and promotion statistics.
- Independent adversarial review before enabling defaults.

Use implementation-oriented models for:

- Test-runner conversion and fixture migration.
- Schema/data-class implementation after approval.
- Renderer templates after semantic fields are frozen.
- CLI/event plumbing, lint cleanup, and repetitive test cases.

The Core, not any model, owns hashing, validation, command execution, evidence freshness, and final
verdict calculation.

## 5. Execution order and release gates

```text
P0-A honest tests
  -> P0-B authority gate
  -> P0-C evidence authority
  -> P0-D compiler/blueprint
  -> P1-A benchmark
  -> P1-B host/renderer/live evidence
  -> P2 release closure
```

Each package lands only with:

1. a failing regression or adversarial test demonstrating the prior defect;
2. the smallest implementation that makes it pass;
3. targeted tests plus the full official suite;
4. an independent review for P0-C, P0-D, and P1-A;
5. documentation updated from observed output rather than intended behavior.

## 6. Execution record

### 2026-07-21 — continued remediation

Implemented:

- P0-D: T2/T3 now activate the execution-brief compiler by default (the environment variable remains an
  explicit override). The immutable raw request is compiled before planning, reconciled through a
  Core-owned non-identity scope proposal, and projected to each role instead of passing the raw request
  through unchanged.
- P0-D: active blueprints require an executable structured ProofPlan. Baseline/red stages run before
  mutation; automated, surface, adversarial, and cleanup stages run after mutation and feed the same
  retry and final-truth decisions as required checks. A surface scenario without a direct argv command is
  rejected rather than treated as prose evidence.
- P1-B: actual runtime identifiers now match the only supported binaries: `claude`, `codex`, and `agy`.
  Gemini remains a model-family name only; no `gemini` executable is invoked. Prompt projections record
  the selected runtime renderer version and final prompt hash for every role.
- P1-B: `run_host_live.py` now supports an isolated Claude Code normal/recovery harness through a generated
  local plugin and `--plugin-dir`, alongside Codex and Antigravity.
- P2: aligned the Antigravity workflow test contract with the shipped named frontmatter and
  retained AGY (`agy`) as the Gemini/Antigravity runtime launcher.
- P1-A: A–F ablation arms now have explicit, hashable execution-policy artifacts and are no longer
  all dispatched through one `converge_goal` branch. The suite additionally schedules Core,
  Adaptive, and Full ProofLoop policy arms for a direct paired comparison.
- P1-A: comparison treats Arm F as the fixed large-directive baseline for A–E and persists the
  policy object/hash in schedule and trial artifacts. Grounded and model-rendered single-agent arms
  now use distinct prompt paths.

Observed verification:

```text
official pytest suite: 334 passed, 1 skipped, 9 subtests passed
benchmark deterministic tests: PASS (22 tests after policy-arm additions)
package validation: PASS (160 runtime files)
```

Remaining before release:

- obtain authenticated normal/recovery host artifacts from Codex, Claude Code, and Antigravity;
- run the new benchmark on real paired fixtures with complete TokScale coverage; no efficiency
  claim may be made from dry-run or simulated results.

### 2026-07-21 — first bounded remediation slice

Implemented:

- P0-A: official runner changed from `unittest` discovery to pytest collection.
- P0-B: owner-decision and read-only/mutation conflicts now stop before role invocation.
- P0-B: bounded repository instruction scanning records path, rule ID, and content hash without
  persisting matched text.
- P0-C slice 1: added a Core-owned verification plan that separates repository-discovered mandatory
  checks from model-proposed candidates.
- P0-C slice 1: final verification adds mandatory repository tests and no longer closes every
  acceptance criterion from an arbitrary aggregate PASS.
- Added an adversarial regression where a planner selects a fake `1 passed` command while the real
  repository test fails; the run now fails final verification instead of returning `PROVEN`.
- P0-C slice 2: Core now seals final checks, check logs, diff evidence, and its in-memory
  verification plan into a manifest-backed bundle. Truth revalidates the bundle and its original
  source artifacts immediately before verdict issuance, so post-capture tampering fails closed.
- P0-C slice 2: repository test entrypoints/configuration discovered before mutation are hashed in
  the plan. Changing one during the run invalidates Core evidence rather than allowing a
  self-referential test success claim.
- P0-C slice 2: a baseline verification plan is now frozen before direct bootstrap as well as
  planned execution. Task-specific plans inherit that authority instead of recomputing evaluator
  hashes after an implementer has had a chance to edit the worktree.
- P0-C/P0-D bridge: planner and direct-bootstrap task contracts now require explicit
  `criterion_ids`; Core links an acceptance criterion only when its task declares that criterion
  and requests the matching Core-approved command. For legacy single-task/single-criterion host
  responses only, Core persists an auditable deterministic mapping; unlinked plural criteria
  remain open.
- P0-D slice 1: compiler activation now writes a versioned policy artifact and a deterministic
  reconciliation report before an execution brief can be projected to roles. The first active
  reconciliation is deliberately identity-only; model refinement is not yet an authority source.

Observed verification:

```text
targeted remediation tests: PASS (35 evidence/verification tests; 30 compiler/evidence tests)
package validation: PASS (160 runtime files)
official pytest suite: 330 passed, 4 failed, 1 skipped, 9 subtests passed
```

The four remaining failures are the existing Antigravity frontmatter assertions (3) and the
Gemini/Antigravity runtime identity expectation (1). Therefore the development and release gates
remain red. P0-C now has output freshness/tamper checks and evaluator-entrypoint protection;
criterion-to-behavior mapping, baseline test-surface policy, and authenticated external evaluators
remain incomplete. P0-D still needs a non-identity refinement proposal and executable ProofPlan
surface scenarios before compiler activation can become a default policy.
