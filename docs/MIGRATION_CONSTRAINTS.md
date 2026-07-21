# ProofLoop — Migration Constraints, Risks & Architecture-Doc Gaps

Companion to `docs/IMPLEMENTATION_PLAN_V2.md`. Read before executing any phase.
Every item cites a repository fact (`file:line` / symbol) or a specific section of `docs/PROOFLOOP_ARCHITECTURE_V2.md`.

---

## 1. Invariants that MUST be preserved through migration

These already hold in the current code and are load-bearing; a migration must not regress them.

1. **Raw request is authority; repository text is data.** `intent.compile_intent` preserves `original_request` + SHA-256 (`intent.py:79`). V2 §7.4 / §34.1–2 make this explicit. Migration must keep the hash chain and never let repository/instruction files widen authority.
2. **Model output is a claim, not evidence.** `truth.build_truth_report` reads artifacts, not model prose (`truth.py:19`); `proof_graph.AUTHORITY` ranks `MODEL_CLAIM=0` below deterministic checks. Do not add a path where a model message closes an obligation.
3. **The implementer cannot certify its own work.** `reviewer_deep` is a separate subprocess reading only the git-snapshot baseline (`orchestrator.py:1662`). Migration must keep implementer/reviewer separation (V2 §15.1, §34.10).
4. **Evidence goes stale.** `proof_graph.record` rejects revision-mismatched evidence (`proof_graph.py:78`). Migration must *add the missing revision-bump trigger*, not remove the check.
5. **Requested ≠ observed model.** `host_runner`/`acp_runner` always record `requestedModel` separately and only upgrade to observed on real host output (`host_runner.py:175`, `acp_runner.py:172`). Never copy requested→observed (V2 §17, capability_contract `FORBIDDEN_STATES`).
6. **Authority is not upward-inferred.** Current `intent.authorization_boundary` limits external writes to separate authorization (`intent.py:84`). V2 §6.3 formalizes this ("구현" ≠ "배포"). The new `AuthorityLevel` enum must not let compilation escalate authority.
7. **Bounded retries, failure-conditioned.** `repair.decide_next` + `fingerprint` bound fast→recovery escalation (`repair.py`, `fingerprint.py`). V2 §23 keeps this; do not introduce unbounded loops.
8. **Deterministic core owns verdicts.** STATUS.md and `remaining-work.md §C` list what automation (not models) must own. Migration must keep truth/verdict/hash/usage computation in deterministic code.

---

## 2. Hidden coupling (surprises that will break naive refactors)

1. **Artifacts are the API between phases.** The orchestrator writes ~25 JSON/JSONL files under `run_dir`; `truth.py`, `assurance.py`, `watch.py`, `usage.py`, `benchmark.py` re-read them by *filename and key*. Any rename (e.g., `checks/checks.json`, `diff-guard.json`, `review.json`, `proof-graph.json`, `model-trace-summary.json`) silently breaks the truth aggregator. Treat artifact filenames + JSON keys as a versioned contract (V2 §14/§19 imply this but the code enforces it by convention only).
2. **`truth.build_truth_report` depends on exact verdict/key strings.** It matches `checks.verdict=="PASS"`, `review.verdict=="APPROVED"`, `diff.verdict=="PASS"`, `proof_graph.obligations[].status=="CLOSED"` (`truth.py:33–56`). Adding `PARTIAL` or new obligation statuses requires updating this function in lockstep.
3. **`orchestrator.py:388` reads `context.get("verdict")` but `ensure_codegraph` returns `status`.** A likely dead/no-op branch; fixing `ensure_codegraph` to also set `verdict`, or fixing the check, changes context-gating behavior — verify against `test_repository_context.py` before touching.
4. **Two prompt paths, two skill-injection strategies.** `orchestrator._prompt_with_selected_skills` injects SKILL.md **paths** (`orchestrator.py:963`); `benchmark.build_builtin_domain_context` injects SKILL.md **contents** (`benchmark.py:777`). Unifying onto Prompt IR (Phase 8) must reconcile both or benchmark results stop being comparable to production runs.
5. **`role_view` uses a different role vocabulary.** `_ROLE_FIELDS` = `{explorer, planner_deep, implementer_fast, recovery, reviewer}` vs canonical `{planner_deep, explorer_fast, implementer_fast, implementer_recovery, reviewer_deep}`. Wiring `role_view` into the live path (Phase 5/8) requires a name-mapping layer or `project_role_view` raises `unknown role`.
6. **`gemini` and `antigravity` share the `agy` launcher** (`runtime.py:82,92`). Changing one host's launcher affects assumptions about the other. Confirm whether `agy` genuinely multiplexes both before editing.
7. **`external_loop.py` is a second orchestration path** using the same `run_checks`/`inspect_diff`/`decide_next` but bypassing `ExternalCLIAdapter`. Deprecating it (plan Phase-P/9) requires confirming no `Makefile`/CLI/live-harness caller depends on `external-loop`.
8. **`active-run.json` is a single per-repo mutable file** (`run_state.py`). Concurrent runs in one repo race on it; any V2 multi-run/observability work must not assume more than one active run per repo unless this is changed.
9. **Goal-mode illegal transitions raise `ValueError`, not `OrchestrationError`.** They fall through to `_finalize_terminal("FAILED", "ORCHESTRATOR_INTERNAL_ERROR")` (`orchestrator.py:469`). New goal transitions must be added to `GOAL_TRANSITIONS` (`goal.py:11`) or they surface as internal failures.
10. **`_is_ephemeral_generated` duplicated** in `diff_guard.py:57` and `git_snapshot.py:55`. Changing scope/ephemeral logic in one place and not the other will desync the diff guard from the snapshot.

---

## 3. Migration risks (ranked)

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Rewiring the request-compilation spine changes verdicts for existing scenarios | High | High | Shadow mode (Phase 5) + tier-gated activation (Phase 6); compare truth verdicts against baseline before/after |
| Adding `PARTIAL` desyncs `truth.py`/`cli.py` exit codes/consumers | Med | High | Update `truth.py`, `cli.py:443`, `watch`, `benchmark` in one phase (Phase 10); keep `UNPROVEN` alias |
| Wiring `live_evidence`/`capability_contract` (never run in production) exposes latent bugs | Med | Med | Keep their pure-validator nature; add integration fixtures before wiring; feature-flag |
| Host Adapter changes break the only working hosts (codex/claude) | Med | High | Phase-P fix first; matcher additive; retain single-adapter fallback; live gates from STATUS.md/E-01..E-06 |
| Prompt IR migration alters prompt semantics and tanks agent quality | Med | High | `generic-v1` renderer must byte-reproduce current prompts as the default; per-model renderers behind versioned config (V2 §14.5); benchmark before promotion (V2 §28.4) |
| `mock=True` codegraph or `DETERMINISTIC_FAST_LANE` leaking into "proven" claims | Med | High | Gate `mock` to test-only; retire fast-lane auto-approval for review-required tiers (Phase 10) |
| Regex-based classification (`strategy.py`, `domain_runtime.py`) misroutes non-matching phrasings | High | Med | Move classification onto RefinedIntentContract+Grounding (V2 §10); keep regex only as a low-confidence signal |
| `diff_guard` regex heuristics (ASSERTION_REMOVED, TEST_DISABLED) false-positive/negative across languages | Med | Med | Treat as soft gate; do not make them the sole proof for test-integrity obligations |
| Deprecating `external_loop`/`attempts` breaks a live harness | Low | Med | Freeze + grep callers (`scripts/`, `Makefile`, `tests/live`) before removal |
| Concurrent runs corrupt `active-run.json` | Low | Med | Document single-active-run assumption; only lift if V2 observability requires it |

---

## 4. Contradictions & underspecified areas in `PROOFLOOP_ARCHITECTURE_V2.md`

These need an owner decision or clarification **before** the affected phase; they are not blockers for Phases 1–4.

1. **`UNPROVEN` vs `PARTIAL` semantics.** V2 §22 defines four verdicts `PROVEN/PARTIAL/BLOCKED/FAILED` but the code uses `UNPROVEN` (`truth.py:10`). V2 §22.3 `PARTIAL` = "일부 deliverable 완료, 필수 증명 부족" which overlaps but is not identical to current `UNPROVEN` (= any non-blocking gap). **Decision needed**: is `UNPROVEN` renamed to `PARTIAL`, or do both coexist (PARTIAL = deliverable-present-but-unprovable, UNPROVEN = evidence-missing)? Plan assumes rename-with-alias.
2. **Evidence model mismatch: V2 `Evidence` vs design-02 evidence levels (L0–L4).** V2 §21.3 defines a flat `Evidence` dataclass; `docs/designs/02-live-evidence-contract.md` and `live_evidence.py` use an L0–L4 evidence-*level* ladder. These are two different models. **Decision needed**: is the V2 truth engine level-based (L0–L4) or type-based (§21.4 taxonomy)? The plan treats levels as an orthogonal confidence axis layered on the type taxonomy.
3. **Authority ladder mismatch.** V2 §6.3 `AuthorityLevel` = READ_ONLY/REPOSITORY_MUTATION/GIT_LOCAL/GIT_REMOTE/EXTERNAL_SIDE_EFFECT; `proof_graph.AUTHORITY` is an *evidence* authority (MODEL_CLAIM…EXTERNAL_OBSERVATION). These are unrelated ladders with confusingly similar names. Migration must keep them distinct namespaces to avoid `EXTERNAL_SIDE_EFFECT` vs `EXTERNAL_OBSERVATION` confusion.
4. **Host capabilities V2 asserts vs what is provable.** V2 §16.2 `HostCapability` includes `supports_model_selection`, `supports_session_resume`, `supports_worktree_isolation`, etc. `docs/designs/03` + `capability_contract.py` explicitly cap Codex/Claude/Gemini at **host-reported observation** and Antigravity at **session-only**, and *forbid* attestation states. **Constraint**: the migration must populate `HostCapability` from evidence, not declaration (V2 §16.6), and must NOT claim capabilities (e.g., per-role routing on Antigravity) that §16/design-03 mark unproven. Do not invent Host capabilities (explicit user MUST-NOT).
5. **Workload scoring bands vs current tiering.** V2 §10.2 gives a 6-axis score with bands (0–5 T0, 6–10 T1, 11–18 T2, 19+ T3) and critical-risk ratchet to T3. Current `strategy.py` uses 3 axes and different thresholds. The V2 bands are illustrative ("예시") and not reconciled with the current heuristics. **Decision needed**: adopt V2 bands verbatim or recalibrate against benchmark data (V2 §28) before promotion.
6. **Meta-compilation budget vs recovery.** V2 §8.6 caps meta compilation at 2 (normal) / 3 (T3), and §23.3 caps recovery at 3 same-fingerprint attempts. Their interaction (does a meta-recompile reset the recovery counter?) is unspecified. **Decision needed** before Phase 11.
7. **"Surface" verification without a running service.** V2 §12.4 SurfaceScenario + §29.3 ("로그 파일만 만들고 실제 서비스는 실행하지 않음 → PROVEN 금지") require actually exercising HTTP/CLI/DB/browser surfaces. The current repo has no surface-execution harness (only `checks.py` command runner). **Constraint**: surface obligations must degrade to `PARTIAL` (not PROVEN) when no surface harness exists — matches V2 §22.3. Building surface harnesses is out of the smallest-safe scope and should be a later, explicitly-scoped phase.
8. **`intent_refiner`/`truth` as roles vs deterministic components.** V2 §15.1 lists `truth` as a role but §22/§34.11 say the truth layer reads artifacts deterministically. The current `truth.py` is deterministic (correct). **Constraint**: keep `truth` deterministic; `intent_refiner` may be a model role but must not gain completion authority (V2 §1.4).
9. **Renderer resolution vs "fable" model alias.** V2 §13.3 renderer resolution keys on model family; `runtime.CONTROLLER_ROUTES` uses a nonstandard model alias `fable` for claude-code reviewer and display strings ("Gemini 3.1 Pro (High)") elsewhere. **Decision needed**: a canonical model-id registry (`configs/models.yaml`, V2 §30) must be introduced so renderer selection is deterministic; today model identity is inconsistent across routes.
10. **Cross-host DoD vs unproven live evidence.** V2 §33 DoD requires execution on all three hosts with identical contract, but STATUS.md marks all authenticated host E2E as unproven and antigravity's direct path is broken. **Constraint**: DoD claims must be gated on the E-01…E-06 live evidence (remaining-work.md §D); do not mark cross-host parity "done" without authenticated artifacts.

---

## 5. Host-capability ground truth (do not invent)

Verified from `hosts.py`, `runtime.py`, `capability_contract.py`, `docs/designs/03`:

- **Codex**: real dual-transport (CLI `codex exec --json`, ACP `codex-acp`), real parser. Provable up to host-reported observed model; access enforcement unproven.
- **Claude Code**: real dual-transport (`claude -p ... stream-json`, ACP `claude-agent-acp`), real parser, session resume. Provider-signed identity unproven.
- **Gemini**: real, but launcher is `agy` (not `gemini`); reasoning-applied + authenticated identity unproven.
- **Antigravity**: `ROLE_ROUTING_ONLY`; model = `current-session-model` sentinel; **direct role invocation currently broken** (`_require_executable`); real path is IDE self-relay workflow; **per-role/cross-model routing is NOT available** and must not be claimed.
- **Attestation/certification**: not implemented anywhere; `capability_contract.FORBIDDEN_STATES` rejects `ATTESTED/CERTIFIED/PROVIDER_SIGNED/VERIFIED_ATTESTATION`; `certification` is always `NOT_EVALUATED`. The migration must not produce a "certified model identity" claim.

---

## 6. Prerequisites & rollback discipline (cross-phase)

- **Feature flags/env gates** for every behavior-changing phase (`PROOFLOOP_EVENT_BUS`, `PROOFLOOP_INTENT_GATE`, `PROOFLOOP_COMPILER_SHADOW`, `PROOFLOOP_COMPILER_ACTIVE_TIERS`, renderer config). Default = current behavior.
- **Artifact additivity**: new phases add new artifact files; they must not repurpose existing filenames/keys until the consuming function (`truth.py`, etc.) is migrated in the same phase.
- **`make check` / `scripts/run_tests.py`** (Makefile:3–9) must stay green after every phase; **`make release-check`** (`scripts/release_check.py`) verdict must not regress below its current state (`FAIL` pending live evidence — do not claim it becomes `PASS` without authenticated host runs).
- **No test is asserted to pass in this analysis.** All completion criteria in the plan require actually running the named tests during implementation.
