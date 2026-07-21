# ProofLoop — V2 Implementation & Migration Plan

Target: `docs/PROOFLOOP_ARCHITECTURE_V2.md` (authoritative for product intent)
Baseline: `docs/CURRENT_ARCHITECTURE_MAP.md` (authoritative for current implementation)
Constraints: `docs/MIGRATION_CONSTRAINTS.md` (read before executing any phase)
Task traceability: `docs/PHASE_TASK_INDEX.md`

Principle followed here: **the V2 doc's Phase plan (§27) assumes more greenfield than the repository actually is.** Several V2 layers already exist in evolved form (proof graph, truth engine, event log, tiering, requested-vs-observed model, and five built-but-unwired bridge modules). This plan therefore favors *wiring and evolving existing machinery* over rebuilding, and defines the **smallest safe phase sequence** with an explicit rollback boundary and completion criteria per phase.

This is a plan. **No production code is modified by this document.** No test is claimed to pass.

---

## 1. Module disposition (retain / modify / deprecate / replace)

| Module | Disposition | Rationale |
|---|---|---|
| `proof_graph.py` | **Retain + extend** | Authority ladder + staleness already match V2 §21. Add evidence types (surface/http/db/screenshot), content_hash/repo_head fields, and a revision-bump trigger. |
| `truth.py` | **Modify** | Already deterministic/artifact-based (V2 §22). Add `PARTIAL` verdict; wire `live_evidence` validation; enforce independent-review-passed obligation. |
| `strategy.py` | **Modify → split** | T0–T3 + ratchet-up retained. Replace regex-on-raw-text classification with classification over `RefinedIntentContract`+`GroundingSnapshot` (V2 §10 forbids regex-only). Keep as the *shape/tier* selector; introduce a 6-axis `WorkloadScore`. |
| `intent.py` | **Retain as Stage-1** | `compile_intent` becomes the deterministic normalization stage inside the new `IntentGate`+compiler pipeline (V2 §5.2, §8.5 T0). Add IntentKind/ClarityLevel/AuthorityLevel. |
| `execution_brief.py` | **Retain + wire** | Already the RefinedIntentContract composer (V2 §5.2/§8). Wire into `run()` in shadow then active mode. |
| `role_view.py` | **Retain + fix + wire** | Already the role-context projector (V2 §15.2). Fix role-name mismatch; wire as Prompt-IR input source. |
| `reconciler.py` | **Retain + wire** | Already the anti-fabrication validator (V2 §9). Wire as the Contract Validator T2/T3 path. |
| `live_evidence.py` | **Retain + wire** | Already the tamper-resistant evidence validator (V2 §21/§22). Wire into truth aggregation. |
| `capability_contract.py` | **Retain + wire** | Already the capability/claim evaluator (V2 §16). Wire host-event records into it; keep attestation states forbidden. |
| `events.py` | **Modify → EventBus** | JSONL store retained. Add typed `ProofLoopEvent`, a pub/sub `EventBus` with subscribers, and V2 §18.2 event-type coverage. Keep schemaVersion "1" readable (dual-emit). |
| `renderers/` (human/jsonl/quiet) | **Retain (rename concept)** | These are *event display* renderers; keep. Introduce a **separate** `prompting/renderer` package for Prompt IR (do not overload the name). |
| `watch.py` | **Retain + extend** | Poll-tail retained; extend toward the V2 §20.7 TUI (proof obligations, budget, roles panels) — later phase. |
| `hosts.py` / `runtime.py` / `adapters.py` / `host_runner.py` / `acp_runner.py` / `process_runner.py` | **Modify** | Formalize `HostAdapter` (V2 §16.1), add `HostCapability` (V2 §16.2) from `capability_contract`, add a Blueprint→Capability matcher. **Fix `_require_executable` bug first.** |
| `output_parsers/` | **Retain** | Real per-host parsers; keep, feed capability records. |
| `checks.py` / `diff_guard.py` / `git_snapshot.py` / `fingerprint.py` | **Retain** | Deterministic gates map directly to V2 deterministic/scope checks. `diff_guard` regex heuristics noted as soft (see constraints). |
| `assurance.py` | **Retain + fold** | Claim/simplicity audit becomes proof obligations in the unified proof graph. |
| `skill_registry.py` / `domain_runtime.py` | **Retain** | Strong skill resolution → becomes V2 §24 Skill Slice source. Add slice compilation (policy fragments, not whole docs). |
| `skill_qualification.py` | **Retain** | Benchmark/eval tool; unchanged for core migration. |
| `benchmark.py` / `benchmark_environment.py` / `swe_skills_bench.py` | **Retain + extend** | Add V2 §28 arms (renderer effect, meta-compiler effect isolation). Unify its divergent prompt path onto Prompt IR (see Phase 8). |
| `usage.py` / `tokscale.py` | **Retain** | Budget/cost telemetry maps to V2 budget policy. |
| `memory.py` | **Retain** | Orthogonal context mechanism; unchanged. |
| `repository_context.py` | **Modify** | Add a real fact snapshot (`GroundingSnapshot`, V2 §7) alongside CodeGraph readiness. **Gate/flag `mock=True`.** |
| `external_loop.py` | **Deprecate (candidate)** | Parallel/legacy retry loop that duplicates `ExternalCLIAdapter`+orchestrator. Freeze; migrate callers; remove after Host Adapter standardization. Confirm no live dependency first. |
| `attempts.py` | **Modify or deprecate** | External attempt path diverges from orchestrator inline loop (`classification=None` bug). Either fix parity or deprecate in favor of the inline loop. |
| `io.py` | **Retain** | Shared helpers. |

Nothing in the current tree is a full **replace** — every V2 capability has a current analog to evolve. The only true *new-build* subsystems are: `IntentGate` enums+classifier, `GroundingSnapshot` fact collector, `PromptIR` + prompt renderers, and the `EventBus` pub/sub layer.

---

## 2. V2 capability → current state → gap → migration action

| # | V2 capability (doc §) | Current analog | Gap | Action |
|---|---|---|---|---|
| C1 | Immutable Raw Request / `RequestEnvelope` (§5.1) | `request.json` + `IntentContract.original_request_hash` | No envelope dataclass; orchestrator `.strip()` on input; no explicit_permissions/denials | New `RequestEnvelope`; stop stripping; preserve exact Unicode + SHA-256 |
| C2 | IntentGate (IntentKind/Clarity/Authority) (§6) | `strategy.classify_request` + `intent.authorization_boundary` (free string) | No enums, no authority ladder, no owner-decision policy | New `intent_gate` module + enums; deterministic rules first, light model on low confidence |
| C3 | Grounding Wave 0 snapshot (§7) | `preflight.py` + `repository_context.ensure_codegraph` (readiness only) | No file/symbol/test *fact* snapshot; prompt-injection-as-data policy not enforced | New `GroundingSnapshot` collector; repository-text-is-data guard |
| C4 | Grounded Prompt Compiler → RefinedIntentContract (§8) | `execution_brief.compose_execution_brief` (unwired) | Not wired; no per-field provenance enum; no model-assisted T2/T3 path | Wire `execution_brief`; add `ProvenanceType`; T2/T3 strong-model proposal via `reconciler` |
| C5 | Deterministic Contract Validator (§9) | `reconciler.reconcile_proposal` (unwired) | Not wired; missing several §9.1 checks | Wire `reconciler` as validator; add authority-not-widened, capability-exists, STOP-WHEN checks |
| C6 | Workload Classifier 6-axis (§10) | `strategy._decision_for` 3-axis scores | 3 axes (risk/complexity/uncertainty) vs 6; classifies raw text not contract | Extend to 6-axis over RefinedIntentContract+Grounding; keep ratchet-up |
| C7 | Execution Strategy shapes (§11) | 4 strategies (DIRECT/PLANNED/HIGH_RISK/ANALYSIS) | Missing MULTI_WORKER, explicit EXPLORE_PLAN_EXECUTE/ADVERSARIAL/RECOVERY as shapes | Map existing→shapes; add shapes incrementally (MULTI_WORKER later) |
| C8 | Execution Blueprint V2 / TaskBrief V2 / ProofPlan (§12) | `TaskBrief` + inline plan | No criterion_ids linkage, no ProofPlan/SurfaceScenario, no dependency graph object | Extend `TaskBrief`; add `ProofPlan`, `SurfaceScenario`, dependency graph; blueprint validation gate |
| C9 | Prompt IR + model-aware Renderer (§13/§14) | Inline f-strings; `role_view` (unwired) | No IR, no renderer registry; two divergent prompt paths | New `PromptIR` from `role_view`; renderer registry (generic→gpt-5.6→claude→gemini); unify benchmark path |
| C10 | Role model (§15) | 5 roles exist | Missing `intent_refiner`, `truth` as explicit roles; implementer_fast/deep split partial | Add roles; enforce role-context bounding via `role_view` |
| C11 | Host Adapter + HostCapability + matcher (§16) | `ExternalCLIAdapter` (one per run) | No capability matcher; broken antigravity path; no blueprint→capability step | Fix bug; formalize `HostCapability` from `capability_contract`; add matcher |
| C12 | Observable Runtime / DecisionRecord (§17) | events + `strategy.json` reasons | No structured `DecisionRecord`; decisions scattered | Add `DecisionRecord` emitted for model/strategy/host selection |
| C13 | Event Bus + ProofLoopEvent (§18) | `EventEmitter` JSONL (untyped, single subscriber) | No pub/sub, no typed event, partial event-type set | Add `EventBus`, `ProofLoopEvent`; complete §18.2 event types |
| C14 | Run Artifact structure (§19) | Close but missing several files | Missing envelope/grounding/refined/blueprint/verdict/evidence-tree | Emit new artifacts as each phase lands |
| C15 | Proof Obligation Engine + Evidence (§21) | `proof_graph.py` (authority+staleness) | Limited obligation/evidence taxonomy; no surface evidence; revision-bump trigger missing | Extend obligations/evidence types; add invalidation trigger; wire `live_evidence` |
| C16 | Truth Verdict PROVEN/PARTIAL/BLOCKED/FAILED (§22) | PROVEN/UNPROVEN/FAILED/BLOCKED | `UNPROVEN` ≠ `PARTIAL` semantics; BLOCKED not from truth fn | Introduce `PARTIAL`; map/retire `UNPROVEN`; allow BLOCKED from truth |
| C17 | Recovery Loop + FailureFingerprint (§23) | `repair.decide_next` + `fingerprint.py` | Bounded recovery exists; no evidence-invalidation-on-contract-change; no meta-recompile trigger | Add contract-change→evidence invalidation; bound meta recompile |
| C18 | Skill Injection / Skill Slice (§24) | `skill_registry` + SKILL.md concat | Whole-doc concat, two paths, no slice object | Compile `SkillSlice` (policy fragments) per role; unify paths |
| C19 | Cross-host contract parity (§33 DoD) | one host per run | Not proven across 3 hosts; antigravity broken | After matcher + bug fix, prove same contract on ≥2 hosts (per STATUS.md live gates) |
| C20 | Benchmark of routing vs prompt effect (§28) | `benchmark.py` multi-arm | Missing renderer-effect / meta-compiler-effect isolation arms | Add arms D/E/F; control variables per §28.3 |

---

## 3. Smallest safe phase sequence

Ordering rationale: **observability + immutability first** (so every later change is inspectable and reversible), **then the request-compilation spine in shadow mode** (zero behavior change), **then activation gated by tier**, **then prompt/host/proof formalization**, **then recovery/benchmark**. Each phase is independently testable and revertible.

Prerequisite **Phase P (fixes)** must precede host work; it is tiny and de-risks everything.

### Phase P — Prerequisite bug fixes (blocking for host phases)
- **Goal**: Remove known runtime landmines before building on them.
- **Changes**: fix `_require_executable` in `host_runner.py:82`; resolve `orchestrator.py:388` `verdict`/`status` key mismatch; fix/annotate `role_view` role-name mismatch; gate `ensure_codegraph(mock=True)` behind an explicit test-only flag; align `attempts.record_attempt` classification with the inline loop (or mark deprecated).
- **Tests**: extend `tests/deterministic/test_host_adapters.py`, `test_repository_context.py`, `test_role_view.py`, `test_attempts.py`; add a regression asserting antigravity `invoke_role` no longer raises `NameError` (mocked binary).
- **Rollback boundary**: each fix is a localized diff; revert per-file. No schema/artifact change.
- **Completion criteria**: all listed tests green locally; no new behavior for codex/claude paths (diff-guard scope unchanged).

### Phase 1 — Event Bus + typed event + immutable RequestEnvelope
- **Goal**: V2 §18 EventBus + `ProofLoopEvent`; V2 §5.1 `RequestEnvelope`.
- **Changes**: add `ProofLoopEvent` dataclass and an `EventBus` (pub/sub) wrapping the existing `EventEmitter` writer (dual-emit v1 dict + v2 typed); add `RequestEnvelope` (exact raw text, SHA-256, explicit_permissions/denials, invocation_source); stop `.strip()` on request; emit `request.envelope_created`.
- **Tests**: `test_events.py` (bus fan-out, sequence monotonicity, corruption recovery preserved), new `test_request_envelope.py` (immutability, hash stability, no stripping), event-type coverage test vs V2 §18.2.
- **Rollback boundary**: EventBus is additive over the existing writer; feature-flag `PROOFLOOP_EVENT_BUS`. Envelope is additive artifact `request-envelope.json`.
- **Completion criteria**: every run emits `run-id` + `events.jsonl` + `request-envelope.json`; existing `watch` still replays; redaction verified before persistence.

### Phase 2 — Watch/TUI evolution (observation only)
- **Goal**: V2 §20.7 panels (roles, proof obligations, budget) as read-only projections.
- **Changes**: extend `watch.py` to render proof-obligation + budget panels from `proof-graph.json`/`usage-summary.json`; add `--watch` to `run`.
- **Tests**: `test_watch.py` replay of a fixture run reconstructs panels; no-follow mode deterministic.
- **Rollback boundary**: pure read-side; revert `watch.py` only.
- **Completion criteria**: a finished run can be re-watched with identical panel output.

### Phase 3 — IntentGate (enums + deterministic classification)
- **Goal**: V2 §6 IntentKind/ClarityLevel/AuthorityLevel + owner-decision policy.
- **Changes**: new `intent_gate.py`; deterministic rules first, light model only on low confidence; emit `intent-gate.json` + events. Authority is *not* upward-inferred ("구현" ≠ "배포").
- **Tests**: V2 §29.1 authority tests ("분석" no mutation, "구현" no push, "PR" no merge, "배포 계획" no deploy); §29.2 prompt-injection-as-data.
- **Rollback boundary**: additive artifact + shadow use only (IntentGate result recorded, not yet gating execution). Flag `PROOFLOOP_INTENT_GATE`.
- **Completion criteria**: authority tests pass; no execution-path behavior change (shadow).

### Phase 4 — Grounding Snapshot (facts, not readiness)
- **Goal**: V2 §7 `GroundingSnapshot` fact collection + repository-text-is-data guard.
- **Changes**: extend `repository_context.py`/new `grounding.py` to collect git state, instruction files, manifests, detected commands, relevant files, host capability; emit `grounding-snapshot.json`; tier-scoped (T0…T3).
- **Tests**: no user question for repo-answerable facts; dirty worktree recorded; stale-grounding detection; injection strings treated as data (event signal).
- **Rollback boundary**: additive artifact; consumed only by shadow compiler in Phase 5.
- **Completion criteria**: grounding artifact produced; protected dirty paths preserved.

### Phase 5 — Grounded Prompt Compiler in SHADOW mode
- **Goal**: V2 §27 Phase 5 — wire `execution_brief` + `reconciler` to produce a RefinedIntentContract **without affecting execution**.
- **Changes**: call `compose_execution_brief(request, intent, strategy, grounding)`; run `reconcile_proposal` (T2/T3); emit `refined-request-shadow.json`, `reconciliation-report.json`, `prompt-diff.json`; add `ProvenanceType` enum.
- **Tests**: same input+repo → same brief hash; raw-request change staleness; T0/T1 no model call; proposal cannot invent criteria/widen authority (reuse `test_reconciler.py`); ≥20 shadow scenarios (per V2 §27 Phase 5).
- **Rollback boundary**: shadow only — existing execution untouched; flag `PROOFLOOP_COMPILER_SHADOW`.
- **Completion criteria**: shadow artifacts for ≥20 scenarios; authority-expansion and criterion-invention detected; token cost measured.

### Phase 6 — Activate compiler for T2/T3
- **Goal**: V2 §27 Phase 6 — RefinedIntentContract drives T2/T3 execution (raw prompt no longer passed straight to planner).
- **Changes**: for T2/T3, feed planner/implementer from RefinedIntentContract via `role_view`; validation failure → explicit `BLOCKED` (no silent fallback); meta-compiler cannot self-approve completion.
- **Tests**: T2/T3 use refined contract; validation-fail → BLOCKED recorded; owner-decision policy fires; T0/T1 legacy path unchanged (regression).
- **Rollback boundary**: tier-gated flag `PROOFLOOP_COMPILER_ACTIVE_TIERS=T2,T3`; revert to shadow instantly. T0/T1 untouched.
- **Completion criteria**: a T2 scenario runs end-to-end on the refined contract with equal-or-better truth verdict vs baseline; no authority expansion.

### Phase 7 — Execution Blueprint V2 (ProofPlan + criterion linkage)
- **Goal**: V2 §12 — TaskBrief V2 with criterion_ids, dependency graph, ProofPlan, SurfaceScenario; blueprint validation gate.
- **Changes**: extend `task_brief.py`; add `ProofPlan`/`SurfaceScenario`; blueprint validator must pass before execution; each TaskBrief links ≥1 criterion; every mandatory obligation maps to a task/check.
- **Tests**: blueprint-validation-blocks-execution; unlinked criterion rejected; surface scenario schema.
- **Rollback boundary**: additive schema fields with defaults; old plans still load; flag on validator strictness.
- **Completion criteria**: T2/T3 blueprints validate; obligation↔task coverage asserted.

### Phase 8 — Prompt IR + model-aware renderers (+ unify benchmark path)
- **Goal**: V2 §13/§14 — `PromptIR` + renderer registry (generic → gpt-5.6 → claude → gemini-visual).
- **Changes**: new `prompting/` package: `PromptIR` (from `role_view`), `renderer_registry.select(model,role,host)`; migrate inline f-strings and `benchmark.build_single_agent_prompt` onto IR; persist `prompt-manifest.jsonl` (hash + renderer version).
- **Tests**: V2 §29.7 — same TaskBrief across generic/gpt-5.6/claude/gemini keeps identical semantic contract/authority/proof requirements, only ordering/phrasing differ; prompt hash + renderer version recorded.
- **Rollback boundary**: renderer registry defaults to `generic-v1` reproducing current prompts; per-model renderers behind config (V2 §14.5 versioned); revert to inline path via flag.
- **Completion criteria**: role prompts generated from IR; benchmark and orchestrator share one prompt path; hashes stable.

### Phase 9 — Host Adapter standardization + capability matcher
- **Goal**: V2 §16 — formal `HostAdapter`, `HostCapability`, Blueprint→Capability matcher; requested-vs-resolved honesty.
- **Changes**: formalize `HostAdapter` methods (detect_capabilities/start_role/stream_events/cancel/collect_result); build `HostCapability` from `capability_contract` records; add matcher that downgrades or BLOCKS on unsupported proof requirements (no fake support); wire `capability_contract.evaluate_capability`.
- **Tests**: V2 §29.6 — unsupported CLI option, no session resume, antigravity requested-model-unavailable → capability-based adjustment, never fake success; requested≠observed → `routingDivergence`.
- **Rollback boundary**: matcher additive; single-adapter path retained as fallback; Phase P bug fix is prerequisite.
- **Completion criteria**: same blueprint runs on ≥2 hosts where capable; unsupported features surfaced as downgrade/BLOCKED; observed model recorded.

### Phase 10 — Proof Graph + Truth Engine V2 (PARTIAL, evidence invalidation, wired live_evidence)
- **Goal**: V2 §21/§22 — richer obligations/evidence, `PARTIAL` verdict, evidence invalidation, independent-review-passed enforcement, `live_evidence` in the truth path.
- **Changes**: extend `Evidence`/`ProofObligation` types (surface/http/db/screenshot; content_hash/repo_head/worktree_hash); add revision-bump trigger on contract/source change; add `PARTIAL`; wire `live_evidence.validate_bundle` before an obligation may close via external evidence; require independent-review obligation for T2/T3; retire `DETERMINISTIC_FAST_LANE` auto-approval for tiers requiring review.
- **Tests**: V2 §29.3 evidence truthfulness (fake test-pass, stale evidence, reused prior-commit result → no PROVEN); §29.4 scope (test deletion/skip → FAILED); PARTIAL emitted when deliverable present but surface unprovable.
- **Rollback boundary**: `PARTIAL` additive; keep `UNPROVEN` alias during transition; invalidation trigger behind flag.
- **Completion criteria**: model-message-only cannot PROVEN; stale evidence cannot PROVEN; scope violation cannot PROVEN; PARTIAL path exercised.

### Phase 11 — Recovery Controller V2
- **Goal**: V2 §23 — contract-change→evidence invalidation, bounded meta-recompile, fingerprint-conditioned retries.
- **Changes**: on contract change invalidate dependent evidence; add meta-recompile trigger for §8.7 conditions only (not syntax/lint/type/simple-test failures); bound recompile counts (§8.6).
- **Tests**: V2 §29.5 — same fingerprint repeats → FAILED/BLOCKED; no meta-recompile on syntax error; contract change invalidates prior evidence; retry-exhaustion accurate.
- **Rollback boundary**: recompile behind budget counters; disable via config → current bounded fast→recovery loop.
- **Completion criteria**: infinite same-failure loops impossible; recompile only on allowed conditions.

### Phase 12 — Benchmark of routing vs prompt effect
- **Goal**: V2 §28 — isolate meta-compiler effect and renderer effect from model effect.
- **Changes**: add arms A–F (§28.1); control variables (§28.3); promotion gate (§28.4) before any renderer/policy default change.
- **Tests**: paired-trial completeness; no default promotion without ≥30 valid scenarios and no false-PROVEN increase.
- **Rollback boundary**: benchmark is read-only over execution; no production behavior change.
- **Completion criteria**: routing effect and meta-compiler effect measured separately; results reproducible.

---

## 4. Sequencing dependencies (summary)

```
P (fixes)
 ├─ Phase 1 (EventBus + Envelope)
 │    └─ Phase 2 (Watch/TUI)
 │    └─ Phase 3 (IntentGate)
 │         └─ Phase 4 (Grounding)
 │              └─ Phase 5 (Compiler shadow)
 │                   └─ Phase 6 (Compiler active T2/T3)
 │                        └─ Phase 7 (Blueprint V2)
 │                             └─ Phase 8 (Prompt IR + renderers)
 └─ Phase 9 (Host Adapter + capability matcher)   [needs P; benefits from Phase 8]
      └─ Phase 10 (Proof/Truth V2)   [needs Phase 7 for obligation↔task; Phase 9 for host evidence]
           └─ Phase 11 (Recovery V2)
                └─ Phase 12 (Benchmark)
```

Phases 1–8 form the request-compilation + prompting spine (mostly additive/shadow, low risk). Phases 9–11 change verdict-affecting behavior and carry the most risk — each is tier/flag-gated so it can be reverted without touching the spine. Phase 12 is measurement-only.

---

## 5. What this plan deliberately does NOT expand (scope guard)

Per the user's MUST-NOT and V2 §32 "not now": no web dashboard, no OMO integration, no remote telemetry server, no multi-user auth, no cloud control plane, no every-model renderer, no unbounded multi-agent teams, no automatic renderer optimization. `MULTI_WORKER` shape and Gemini visual renderer are deferred until after Phases 1–11 land and benchmarks justify them.
