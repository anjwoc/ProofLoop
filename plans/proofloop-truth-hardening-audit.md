# ProofLoop Truth Hardening Audit Plan

Status: IN_PROGRESS  
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
7. Every non-trivial new rule leaves one runnable regression check.
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
- [ ] Produce a phase-by-phase inventory of timeouts, attempt limits, token limits, output truncation, file/line budgets, polling intervals, loop counts, and environment overrides.
- [ ] Classify every limit as `SAFETY_BOUNDARY`, `OPERATIONAL_DEFAULT`, `TASK_CONTRACT`, `TEST_ONLY`, or `UNJUSTIFIED_HARDCODE`.
- [ ] Record source path, symbol, default, override path, affected phase, and failure semantics.

## Workstream B — False-success and fake-evidence audit

- [ ] Trace the complete path from adapter result to `truth-report.json`.
- [ ] Identify every place where exit code, generated artifact, mocked model identity, or empty/skipped checks can become PASS/APPROVED/PROVEN.
- [ ] Separate deterministic unit fixtures from authenticated host acceptance reports by schema and storage path.
- [ ] Verify that `PROVEN` requires current-run Core evidence, required criteria closure, valid diff scope, and the appropriate review authority.
- [ ] Verify that release checks reject missing, stale, simulated, or copied host evidence.
- [ ] Add adversarial cases: fake result file, fake host label, zero checks, skipped proof, stale evidence, copied report, test adapter claiming observed model, and host exit zero without ProofLoop run.

## Workstream C — Skill quality audit

- [x] Read `agent-skill-creator` validation philosophy: evidence-derived intent, complete artifacts, spec validation, security scan, pipeline check, eval validation, and held-out evidence.
- [x] Read Ponytail: understand the whole flow first, then choose the highest reusable rung; one runnable check for non-trivial logic; never remove safety.
- [x] Read LazyCodex: plan before product code, durable checklist execution, evidence-verified completion, and post-implementation multi-angle review.
- [ ] Audit `skills/proofloop/SKILL.md` for activation, host parity, unsupported promises, install/runtime assumptions, and cross-platform invocation correctness.
- [ ] Audit every role protocol injected into planner/explorer/implementer/recovery/reviewer.
- [ ] Add a mandatory anti-deception contract that is injected before role-specific instructions and cannot be disabled by task/domain skills.
- [ ] Ensure Ponytail rules apply to implementation and review without weakening correctness or required evidence.
- [ ] Add a validation test proving the mandatory contract appears in every mutating and reviewing role prompt.

## Workstream D — Minimal hardening changes

- [ ] Add one shared evidence-origin policy rather than scattered string checks.
- [ ] Mark simulated adapter runs as non-production evidence in durable run metadata.
- [ ] Prevent authenticated acceptance artifacts from being written from simulated runs.
- [ ] Require non-empty authoritative checks for criteria claimed as satisfied.
- [ ] Prevent deterministic fast-lane review from asserting intent alignment or minimality when its only evidence is file-count/diff-budget compliance.
- [ ] Replace unconditional `APPROVED`/`MINIMAL` generation with a bounded, source-derived fast-lane policy or an honest `CANNOT_VERIFY` result.
- [ ] Remove or justify duplicated retry/loop defaults and contradictory documented defaults.
- [ ] Preserve a single explicit run deadline source; expose every derived deadline in artifacts.

## Workstream E — Verification ladder

- [ ] Static audit report contains exact file/symbol evidence and distinguishes confirmed facts from hypotheses.
- [ ] Targeted deterministic tests cover every changed guard.
- [ ] Existing deterministic suite is run without deleting or weakening unrelated tests.
- [ ] Package validation is run and reported only as packaging evidence.
- [ ] Skill spec validation/security scan/pipeline validation are run where the referenced tool is available.
- [ ] Authenticated Codex acceptance is run once after deterministic gates pass.
- [ ] Authenticated Antigravity acceptance is run once after deterministic gates pass.
- [ ] Visual/browser claims are either explicitly asserted or left unproven.
- [ ] All command lines, exit codes, durations, and artifact paths are recorded.

## Workstream F — Deliverables

- [ ] `docs/audits/PROOFLOOP_FULL_PIPELINE_AUDIT.md`: categorized findings, severity, evidence, impact, and root cause.
- [ ] `docs/audits/PROOFLOOP_HARDCODE_AND_LIMIT_INVENTORY.md`: exhaustive limit inventory.
- [ ] `docs/audits/PROOFLOOP_SKILL_VALIDATION_REPORT.md`: agent-skill-creator + Ponytail + LazyCodex assessment.
- [ ] `docs/PROOFLOOP_TRUTH_AND_ANTI_DECEPTION_CONTRACT.md`: normative rules and evidence taxonomy.
- [ ] Code/tests implementing the smallest sufficient hardening changes.
- [ ] Final execution ledger listing `PASSED`, `FAILED`, `BLOCKED`, and `UNEXECUTED` checks without upgrading any status.

## Stop conditions

Stop and report honestly when any of these applies:

- The connected environment cannot execute the repository or authenticated host CLI.
- Required source cannot be read from the target branch.
- A proposed fix would broaden the task beyond truth/evidence/limit/skill hardening.
- The only available proof is a fake adapter, self-authored JSON, or a test that does not exercise the production path.

## Current execution constraints

- GitHub source and writes are available through the connected GitHub app.
- The local container cannot resolve `github.com`, so a fresh clone and local pytest run are currently unavailable in this session.
- Therefore, repository edits may be made from source inspection, but no local or authenticated-host test will be marked passed until an actual command transcript is available.
