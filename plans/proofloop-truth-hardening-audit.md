# ProofLoop Truth Hardening Audit Plan

Status: IN_PROGRESS — source audit and first hardening slice complete; deterministic/live execution remains open  
Branch: `codex/preserve-eb097dd-with-main`  
Method: LazyCodex-style decision-complete plan + Ponytail minimal-change ladder + agent-skill-creator validation gates

## Completion promise

This plan is complete only when every checked item has a repository artifact or a command result that another person can inspect. A model statement, mocked host response, generated JSON without provenance, or a test that only proves its own fixture is not completion evidence.

## Non-negotiable rules

1. Never promote `TEST`, `MOCK`, `SIMULATED`, `CLI_REQUESTED_ONLY`, or missing host evidence into an authenticated-host success claim.
2. Never call a run `PROVEN` only because a child process exited zero or wrote the expected JSON shape.
3. A check must exercise the changed promise. Package-presence tests and schema-only tests are supporting checks, not acceptance evidence.
4. Test fixtures must be visibly marked and structurally unable to overwrite authenticated acceptance evidence.
5. Do not add abstractions where one shared guard or one existing contract field is sufficient.
6. Keep security, data-loss prevention, authorization boundaries, and trust-boundary validation even when simplifying.
7. Every non-trivial new rule leaves one runnable check.
8. Any unexecuted live-host scenario remains `UNEXECUTED` or `BLOCKED`; never infer success.

## Evidence classes

| Class | Meaning | May prove production behavior? |
| --- | --- | --- |
| `STATIC_SOURCE` | File/line inspection of current branch | Only implementation presence, never runtime behavior |
| `DETERMINISTIC_LOCAL` | Real subprocess/check against local code | Yes, for the exact local behavior exercised |
| `SIMULATED_ADAPTER` | In-process fake/test host | No; only orchestration branch logic |
| `AUTHENTICATED_HOST` | Installed CLI, real account, preserved transcript | Yes, for host integration and routing |
| `MANUAL_VISUAL` | Human-observed UI/browser evidence | Yes, only for the recorded scenario |

## Workstream A — Repository and promise inventory

- [x] Read `docs/EXPECTED_RESULTS_AND_TEST_SCENARIOS.md` and extract the stated success contract.
- [x] Read `docs/PIPELINE_EXECUTION_GUIDE.md` and extract documented limits and retry policy.
- [x] Compare branch with `main` and identify deleted/replaced verification coverage.
- [x] Produce a phase-by-phase inventory of timeouts, attempt limits, token limits, output truncation, file/line budgets, polling intervals, loop counts, and environment overrides.
- [x] Classify every limit as `SAFETY_BOUNDARY`, `OPERATIONAL_DEFAULT`, `TASK_CONTRACT`, `TEST_ONLY`, `CONTRADICTORY`, or `UNJUSTIFIED_HARDCODE`.
- [x] Record source path, symbol, default, override path, affected phase, and failure semantics.

Evidence: `docs/audits/PROOFLOOP_HARDCODE_AND_LIMIT_INVENTORY.md`.

## Workstream B — False-success and fake-evidence audit

- [x] Trace the complete path from adapter result to `truth-report.json`.
- [x] Identify where exit code, generated artifact, mocked model identity, or empty/skipped checks can become PASS/APPROVED/PROVEN.
- [ ] Separate deterministic unit fixtures from authenticated host acceptance reports by enforced schema and storage path.
- [x] Audit whether `PROVEN` requires current-run Core evidence, criteria closure, diff scope, and review authority; document the remaining fast-lane authority gap.
- [ ] Make release checks reject missing, stale, simulated, copied, or source/runtime-mismatched host evidence.
- [ ] Complete adversarial cases for fake result file, fake host label, skipped/stale/copied evidence, and host exit zero without a ProofLoop run.
- [x] Add an adversarial Truth case for an empty check list that falsely says PASS.
- [x] Persist CLI/programmatic evidence origin in run metadata.

Evidence: `docs/audits/PROOFLOOP_FULL_PIPELINE_AUDIT.md`, `proofloop_core/contracts/run_state.py`, `proofloop_core/assurance/truth.py`, and `tests/deterministic/test_evidence_origin_and_empty_truth.py`.

## Workstream C — Skill quality audit

- [x] Read `agent-skill-creator` validation philosophy: evidence-derived intent, complete artifacts, spec validation, security scan, pipeline check, eval validation, and held-out evidence.
- [x] Read Ponytail: understand the whole flow first, then choose the highest reusable rung; one runnable check for non-trivial logic; never remove safety.
- [x] Read LazyCodex: plan before product code, durable checklist execution, evidence-verified completion, and post-implementation multi-angle review.
- [x] Audit `skills/proofloop/SKILL.md` for activation, host parity, unsupported promises, install/runtime assumptions, and cross-platform invocation correctness.
- [x] Audit every role protocol and its actual prompt-consumer mapping.
- [x] Add a mandatory anti-deception contract before provider and role-specific instructions.
- [x] Apply Ponytail rules without weakening validation, security, authorization, or evidence.
- [x] Add a validation test proving the mandatory contract appears in every role/provider prompt.
- [x] Allow the entry skill to use an isolated `PROOFLOOP_HOME` runtime and fail visibly when the runtime is missing.

Evidence: `docs/audits/PROOFLOOP_SKILL_VALIDATION_REPORT.md`, `proofloop_core/prompting/renderers.py`, `skills/proofloop/SKILL.md`, and `tests/deterministic/test_prompt_integrity.py`.

## Workstream D — Minimal hardening changes

- [x] Add one evidence-origin classification point in run-state creation.
- [x] Mark programmatic/unknown runs separately from CLI host runs in durable metadata.
- [ ] Prevent authenticated acceptance artifacts from being written/accepted from simulated runs.
- [x] Require non-empty check evidence at the Truth Gate.
- [ ] Reject plans before mutation when no executable post-change verifier exists.
- [ ] Prevent deterministic fast-lane review from overclaiming semantic intent alignment or global minimality.
- [ ] Replace unconditional `APPROVED`/`MINIMAL` generation with a bounded policy verdict or honest `CANNOT_VERIFY`.
- [ ] Remove duplicated retry/loop defaults and contradictory budget paths.
- [ ] Preserve a single explicit run deadline/budget source and expose every derived limit.
- [ ] Bind live acceptance source revision to installed runtime revision.

## Workstream E — Verification ladder

- [x] Static audit report contains exact file/symbol evidence and distinguishes confirmed facts from hypotheses.
- [x] Targeted deterministic test files were added for every guard changed in this slice.
- [ ] Execute the targeted deterministic tests.
- [ ] Execute the existing deterministic suite without deleting or weakening unrelated tests.
- [ ] Run package validation and report it only as packaging evidence.
- [ ] Run skill spec validation, security scan, and pipeline/eval validation.
- [ ] Run one authenticated Codex acceptance after deterministic gates pass.
- [ ] Run one authenticated Antigravity acceptance after deterministic gates pass.
- [x] Leave visual/browser claims explicitly unproven until the documented scenario and assertions exist.
- [x] Record reproducible commands, expected outcomes, statuses, and artifact requirements in an execution ledger.

## Workstream F — Deliverables

- [x] `docs/audits/PROOFLOOP_FULL_PIPELINE_AUDIT.md`
- [x] `docs/audits/PROOFLOOP_HARDCODE_AND_LIMIT_INVENTORY.md`
- [x] `docs/audits/PROOFLOOP_SKILL_VALIDATION_REPORT.md`
- [x] `docs/PROOFLOOP_TRUTH_AND_ANTI_DECEPTION_CONTRACT.md`
- [x] First minimal code/test hardening slice
- [x] `docs/audits/PROOFLOOP_EXECUTION_LEDGER.md`

## Stop conditions

Stop and report honestly when any of these applies:

- The connected environment cannot execute the repository or authenticated host CLI.
- Required source cannot be read from the target branch.
- A proposed fix would broaden the task beyond truth/evidence/limit/skill hardening.
- The only available proof is a fake adapter, self-authored JSON, or a test that does not exercise the production path.

## Current execution constraints

- GitHub source and writes are available through the connected GitHub app.
- The local container could not resolve `github.com`, so a fresh clone and local pytest run were unavailable in this session.
- New tests are committed but remain `UNEXECUTED`.
- No authenticated host run or GitHub CI run is being represented as passed.
- The exact continuation commands and expected current failures are in `docs/audits/PROOFLOOP_EXECUTION_LEDGER.md`.
