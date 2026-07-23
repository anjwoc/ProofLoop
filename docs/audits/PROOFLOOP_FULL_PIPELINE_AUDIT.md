# ProofLoop Full Pipeline Audit

Audit target: `codex/preserve-eb097dd-with-main`  
Audit method: static source inspection through the connected GitHub app, branch comparison, external skill-source review, and bounded source fixes.  
Execution limitation: the current local container could not resolve `github.com`; no local pytest or authenticated host acceptance is marked passed in this report.

## Executive verdict

**Current release status: NOT PROVEN.**

The repository contains strong evidence-oriented prose and several real Core safeguards, but the documented promise, installed runtime, selected skills, deterministic tests, and live acceptance harness are not yet one coherent executable contract.

The main failure is not one model. It is an architecture that still permits **declarative assurance**:

- a document names tests that do not exist
- a selected skill can be announced without being injected
- a fake adapter run can produce an ordinary `PROVEN` mechanics report
- a fast lane generates `APPROVED` and `MINIMAL` without semantic review
- a live runner can execute a different fixture than the documented scenario
- source and `$HOME/.proofloop` runtime can differ
- a release report already says `FAIL`, while no CI run exists for the current work

## Evidence status used in this audit

| Evidence | Status | Meaning |
| --- | --- | --- |
| Current branch source inspection | `PASSED` | Paths and symbols below were read from the target branch |
| Branch comparison with `main` | `PASSED` | Large source/test replacement was observed |
| Local deterministic suite | `UNEXECUTED` | Repository clone was unavailable in the local container |
| Package validation after this audit | `UNEXECUTED` | No local source checkout |
| Authenticated Codex acceptance | `UNEXECUTED` | No authenticated host execution in this session |
| Authenticated AGY acceptance | `UNEXECUTED` | No authenticated host execution in this session |
| GitHub CI for audit commit | `UNEXECUTED` | No workflow run/status was present |

## P0 findings

### P0-01 — Documented acceptance commands reference missing test files

**Confirmed fact**

`docs/EXPECTED_RESULTS_AND_TEST_SCENARIOS.md` instructs users to run:

- `tests/deterministic/test_direct_bootstrap.py`
- `tests/deterministic/test_static_web.py`

Neither path exists on the target branch. The same fetch also failed on `main`.

**Impact**

The published acceptance command cannot be reproduced. A report claiming this documented gate passed has no valid command target.

**Root cause**

Documentation and test inventory are maintained separately. Package validation checks required text fragments but does not validate every documented command/path.

**Smallest remediation**

Add a documentation-command validator that parses fenced shell commands used as release gates and verifies referenced repository files. Then either restore the tests or replace the command with existing tests that directly exercise the promise.

### P0-02 — Documented live scenario and actual fixture test different products

**Confirmed fact**

The expectation document describes a static Three.js solar-system website and its browser/animation checks. `scripts/run_host_live.py --scenario normal` reads `tests/live/fixtures/normal/README.md`, whose request is to fix an `IdempotencyExecutor` concurrency bug.

**Impact**

A successful live `normal` run cannot prove the documented static-web behavior. The user can follow the guide exactly and receive evidence for another scenario.

**Root cause**

One generic scenario name (`normal`) is overloaded as a release acceptance target while documentation evolved to a different feature.

**Smallest remediation**

Use explicit scenario IDs, such as `static-web-solar-system` and `idempotency-concurrency`, and require the expected-output contract to declare and match the scenario ID and request hash.

### P0-03 — Live runner expects host metadata that the run did not persist

**Confirmed fact**

`run_host_live.result_from_workspace()` reads `run.json["host"]` and reports `HOST_SKILL_ROUTING_MISMATCH` when it differs from the requested host. Before this audit, `start_run()` did not write a host field.

**Impact**

A valid host run could be rejected as a routing mismatch, or host provenance could remain absent.

**Applied fix**

`proofloop_core/contracts/run_state.py` now records:

- `host`
- `evidenceOrigin: CLI_HOST_RUN | PROGRAMMATIC_OR_UNKNOWN`

It derives the host from the explicit CLI argv, supported session environment, or leaves it unresolved. This labels provenance without claiming authentication.

**Verification status**

Regression tests were added but are `UNEXECUTED` in this session.

### P0-04 — Empty check evidence can look like PASS before Truth

**Confirmed fact**

`run_checks()` computes PASS using `all(...)`; an empty result list satisfies Python's vacuous truth. Empty proof stages are also represented as `SKIPPED` with `expectationMet: true`.

The proof graph often prevents final `PROVEN` because acceptance obligations remain open, but intermediate artifacts can still say PASS and the fast lane can create an approval artifact.

**Impact**

Logs and reports can visually imply successful verification despite no command execution. Detached artifacts are particularly misleading.

**Applied fix**

`proofloop_core/assurance/truth.py` now rejects an empty `checks` list with `CHECK_EVIDENCE_EMPTY`, even when the report says `verdict: PASS`.

**Remaining work**

The planner/task schema should reject tasks that contain no executable post-change verifier, rather than waiting until Truth.

### P0-05 — Fake adapter mechanics can produce an ordinary `PROVEN` result

**Confirmed fact**

`tests/deterministic/test_orchestrator_smoke.py` uses an injected adapter with `modelEvidence: TEST`, writes source directly, and asserts the overall result is `PROVEN`.

The trace summarizer correctly treats `TEST` as weak model evidence, but the fake adapter reports `ROLE_ROUTING_ONLY`, so routing is not claimed and the mechanics run may still reach `PROVEN`.

**Impact**

A truth report detached from its test context can be mistaken for authenticated production evidence. It trains models and developers to equate fake-host mechanics with end-to-end success.

**Root cause**

Truth verdict and evidence scope are conflated. Release reporting adds a simulation label later, but the run artifact itself lacks a hard production/mechanics distinction.

**Applied partial fix**

All new runs now persist `evidenceOrigin`. Programmatic runs are visibly labelled `PROGRAMMATIC_OR_UNKNOWN`.

**Required remediation**

Add an explicit `evidenceScope` to Truth (`MECHANICS_ONLY`, `LOCAL_DETERMINISTIC`, `AUTHENTICATED_HOST`) and prohibit an authenticated release gate from accepting `MECHANICS_ONLY`, regardless of the internal mechanics verdict.

### P0-06 — Source branch and installed runtime can differ during live acceptance

**Confirmed fact**

The entry skill invokes `$HOME/.proofloop/bin/proofloop-core`. `scripts/run_host_live.py` builds and copies project-local host skills/agents into the temporary fixture but does not install or verify that sidecar against the source commit under test. The install guide itself states source changes are not automatically reflected in the installed runtime.

**Impact**

A live test can execute old Core code while presenting current branch skills. A pass or failure may belong to a different revision.

**Root cause**

Host adapter packaging and Core runtime installation are separate mutable states with no revision handshake.

**Smallest remediation**

For live acceptance, create an isolated `PROOFLOOP_HOME`, install the current source into it, record a source/runtime hash, and fail before host invocation when they differ.

## P1 findings

### P1-01 — `proofloop-verify` is selected and charged but not injected

`resolve_skills()` selects process protocols and reserves their token budgets. `_prompt_with_selected_skills()` maps intent/design/plan/implement/debug/review to roles but never maps `proofloop-verify`. Events still announce that the skill was selected and its instructions were loaded.

**Impact:** visible skill activation does not equal actual prompt application.

**Remediation:** either make verification an explicit Core-owned protocol with no prompt-loaded claim, or inject it into a dedicated verifier role. Do not charge an injection budget for an unconsumed document.

### P1-02 — Process protocols are experimental E0 but auto-selected

All seven built-in process protocol contracts are `status: EXPERIMENTAL` and `evaluation.evidenceLevel: E0`. Registry eligibility excludes only `QUARANTINED` and `STALE`; experimental process protocols remain default candidates.

The package validator checks behavior/trigger eval fixtures for domain packs, not process protocols.

**Impact:** `skill.selected` sounds stronger than the protocol's own evidence status.

**Remediation:** require process-protocol schema validation and eval qualification. Emit status/evidence level in visible selection, and do not auto-select E0 experimental protocols for production claims unless explicitly allowed.

### P1-03 — Skill contract loading silently defaults malformed fields

`skill_registry._load_contract()` states that defensive validation was removed and trusts internal JSON. Missing fields receive defaults such as experimental status, model-claim authority, 10,000 tokens, and 10 invocations.

**Impact:** a typo or omitted authority/budget field can silently change execution policy.

**Remediation:** validate every internal contract against a checked-in JSON schema at discovery time. Internal files are still a trust boundary because models modify them.

### P1-04 — Fast lane auto-creates semantic approval and minimality

When deep review is not required, `_final_verification_and_review()` writes:

- `verdict: APPROVED`
- `simplicityVerdict: MINIMAL`
- `reviewMode: DETERMINISTIC_FAST_LANE`

Its evidence is only checks and diff guard. `_record_verification_proof()` then uses this to close intent-alignment and simplicity obligations.

**Impact:** passing commands and bounded diff are stronger than no evidence, but they do not universally prove semantic intent alignment or global minimality.

**Remediation:** rename the result to a bounded policy verdict, include criterion-to-check mapping, and leave semantic review explicitly unproven unless the policy can derive it.

### P1-05 — Planner instructions require checks, schema does not

The planner prompt says every task must include executable required/post-change checks. `load_task_brief()` accepts an empty `requiredChecks` list and absent/empty proof plan. `materialize_plan()` validates paths and task count but not executable acceptance evidence.

**Impact:** critical guarantees depend on model obedience rather than Core schema.

**Remediation:** reject plans with no post-change verifier and reject tasks without criterion links after deterministic single-task inference.

### P1-06 — Retry policy is duplicated and contradictory

Examples:

- TaskBrief defaults: fast/recovery `1/0`
- `decide_next()` function defaults: `2/1`
- repeated fingerprint hardcoded at `3`
- final review loop hardcoded to two cycles and may call recovery once without consulting task recovery budget
- replan logic contains a special `max_replans == 1` branch that expands to tier-dependent `2/3`

**Impact:** documented cost policy is not the only effective invocation policy.

**Remediation:** one immutable run budget artifact must own all invocation counts, including final review repair and replanning.

### P1-07 — Release report is already FAIL and is not portable

`reports/release-check.json` records:

- deterministic checks `FAIL`
- simulated host mechanics only
- all authenticated host reports `MISSING`
- authenticated routing and repair `UNPROVEN`
- overall release `FAIL`

It also contains absolute `/Users/...` paths and no durable source/runtime revision pair.

**Impact:** the repository's own retained evidence contradicts any release-ready claim and cannot be reproduced on another machine.

**Remediation:** regenerate reports with repository-relative artifact paths, commit/runtime hashes, timestamps, command durations, and immutable evidence class.

### P1-08 — No CI status exists for the audit branch commits

The connected GitHub status and workflow queries returned no status checks or workflow runs.

**Impact:** repository users cannot distinguish source-only commits from tested commits.

**Remediation:** add a minimal CI workflow for deterministic tests, package validation, documentation command validation, and skill contract validation. Live authenticated tests remain a separate manual/secured gate.

## P2 findings

### P2-01 — Package validation contains brittle correctness proxies

`scripts/validate_package.py` hardcodes a runtime source-file budget of 185 based on a historical baseline plus two modules. It also hardcodes expected role models and required text fragments.

These checks may be useful packaging constraints, but they are not behavioral acceptance and should not fail a correct feature merely because file count changes.

### P2-02 — Model-detection regex and marketing text can stale independently

Host model parsing contains a hardcoded regex for named model families. The Codex plugin manifest text references specific Sol/Terra routing. These values can drift from current route configuration and host output formats.

### P2-03 — AGY may expose both a skill and workflow named `proofloop`

The AGY build copies the `proofloop` skill and also creates `workflows/proofloop.md`. Whether the host resolves this without collision needs a real installed-host observation. This is a **hypothesis**, not a confirmed runtime defect.

### P2-04 — Old broad tests were removed during a large rewrite

The branch comparison shows large removals of benchmark, event, host-adapter, package, skill-registry, watch, and orchestration tests while replacing the core orchestrator. Deletion is not inherently wrong, but coverage equivalence has not been demonstrated by CI or a coverage map.

## What is already good

The following are real strengths and should be preserved:

- immutable request envelope and refined intent separation
- worktree isolation and promotion after verification
- parent-owned result artifact extraction for real CLI adapters
- monotonic timeout/heartbeat implementation
- current-run evidence sealing and freshness validation
- proof graph with authority-aware obligations
- explicit `NEEDS_INPUT` path separate from Truth
- implement/review/verify protocol prose that rejects model summaries as proof
- provider private-reasoning redaction
- diff guard before promotion

The problem is not that ProofLoop has no safeguards. It is that several safeguards exist as prose, optional metadata, or disconnected layers rather than one enforced release contract.

## Changes applied in this audit

1. Added `plans/proofloop-truth-hardening-audit.md` using a decision-complete LazyCodex-style checklist.
2. Added the mandatory truth/minimality contract at the start of every rendered role prompt.
3. Added the same absolute constraints to `skills/proofloop/SKILL.md`.
4. Added prompt-integrity regression tests for every role/provider combination.
5. Added host and evidence-origin metadata to `run.json`.
6. Added a Truth Gate blocker for empty check evidence.
7. Added regression tests for CLI/programmatic provenance and empty checks.
8. Added this normative anti-deception contract and audit set.

## Verification ledger for applied changes

| Gate | Status | Evidence |
| --- | --- | --- |
| Source files committed to target branch | `PASSED` | GitHub commit results for each file update |
| Static source review of changed files | `PASSED` | Connected GitHub file reads |
| New deterministic tests executed | `UNEXECUTED` | Local checkout unavailable |
| Existing deterministic suite | `UNEXECUTED` | Local checkout unavailable |
| Package validation | `UNEXECUTED` | Local checkout unavailable |
| agent-skill-creator validator/security scan | `UNEXECUTED` | External repository scripts not installed in this environment |
| Authenticated Codex live test | `UNEXECUTED` | Requires installed current runtime and authenticated CLI |
| Authenticated AGY live test | `UNEXECUTED` | Requires installed current runtime and authenticated CLI |
| GitHub CI | `UNEXECUTED` | No workflow run/status present |

## Ordered improvement plan

### Phase 0 — Make the repository testable

1. Add deterministic CI.
2. Add document-command/path validation.
3. Make live runner install current source into isolated `PROOFLOOP_HOME`.
4. Record source/runtime hashes and scenario ID.

### Phase 1 — Close false-success paths

1. Add Truth `evidenceScope` and release-gate authority requirement.
2. Reject plans without executable post-change verification.
3. Make zero-check reports non-PASS at the check-report layer as well as Truth.
4. Bound fast-lane claims to explicit policy authority.
5. Separate simulated report directories and schemas from authenticated reports.

### Phase 2 — Make skills executable contracts

1. Validate every process protocol contract against schema.
2. Add trigger/behavior/held-out evals for process protocols.
3. Resolve `proofloop-verify` ownership: dedicated role or explicit Core implementation.
4. Show skill status/evidence/injection mode in events.
5. Quarantine or require opt-in for E0 experimental protocols.

### Phase 3 — Unify budgets

1. Generate one `execution-budget.json` before role invocation.
2. Include run/role/check/initial-output deadlines and every invocation count.
3. Remove function defaults that differ from the frozen budget.
4. Count final review repair and replans against the same budget.
5. Require new hypothesis/evidence for retry.

### Phase 4 — Prove the advertised experience

1. Restore or replace the missing documented tests.
2. Add an explicit solar-system fixture if that remains the advertised scenario.
3. Run deterministic gates.
4. Run one authenticated Codex normal acceptance.
5. Run one authenticated AGY normal acceptance.
6. Record visual limitations honestly; do not claim planet-count/visual correctness without assertions.

## Release decision

Do not merge this branch as a proven ProofLoop release until Phases 0 and 1 are complete and the authenticated-host ledger contains real runs from the same source/runtime revision.
