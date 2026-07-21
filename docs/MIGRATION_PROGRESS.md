# ProofLoop V2 Migration — Progress Log & Handoff

Purpose: single source of truth for what has been done, what is in flight, and how to continue — written so a fresh agent (or human) can pick up without re-deriving context.

Companion docs: [`PROOFLOOP_ARCHITECTURE_V2.md`](PROOFLOOP_ARCHITECTURE_V2.md) (target), [`CURRENT_ARCHITECTURE_MAP.md`](CURRENT_ARCHITECTURE_MAP.md), [`IMPLEMENTATION_PLAN_V2.md`](IMPLEMENTATION_PLAN_V2.md) (phase/task plan), [`MIGRATION_CONSTRAINTS.md`](MIGRATION_CONSTRAINTS.md), [`PHASE_TASK_INDEX.md`](PHASE_TASK_INDEX.md).

Last updated: 2026-07-21.

---

## 0. How to work on this migration

- **Method**: TDD (Prove-It). Every change is a failing test first, then the fix, then full-suite regression. See `~/.claude/skills/test-driven-development`.
- **Run tests**: `python3 -m pytest tests/deterministic tests/orchestration -q` (≈60s). Or `make check` / `python3 scripts/run_tests.py`.
- **Compile check**: `python3 -m compileall -q proofloop_core`.
- **Safety discipline**: every behavior-changing phase is additive + flag/tier-gated so it reverts cleanly. New artifacts are added, existing filenames/keys are not repurposed until the consuming code migrates in the same phase.
- **Do NOT** claim an unexecuted test passes; do not invent Host capabilities; keep raw request authoritative (see `MIGRATION_CONSTRAINTS.md §1`).

---

## 1. Current test baseline

```
tests/deterministic + tests/orchestration: 301 passed, 4 failed, 1 skipped, 9 subtests passed
```

The **4 failures are pre-existing and NOT from this migration** — they come from other in-progress uncommitted edits present in the working tree before Phase P began (see §4). They were left untouched by explicit user decision.

Baseline before any migration work: 250 passed / 8 failed. Migration work fixed 4 (the T-P1 group) and added new passing tests; the other 4 pre-existing failures remain.

---

## 2. Completed work

### Phase P — Prerequisite bug fixes ✅ (all 5 tasks)

| Task | Change | Files | Tests |
|---|---|---|---|
| T-P1 | Restored antigravity command to `str(executable)` (removed undefined `_require_executable` NameError; kept intended `--mode` flag) | `proofloop_core/host_runner.py` | 4 existing antigravity tests RED→GREEN (`test_host_adapters.py`) |
| T-P2 | `context.get("verdict")` → `context.get("status")` (defensive; branch currently unreachable — only `REPOSITORY_ANALYSIS` sets `context_required` and it returns early via audit. Becomes live in Phase 4/6.) | `proofloop_core/orchestrator.py` (~line 393) | no reachable test (documented) |
| T-P3 | `role_view` accepts canonical role names (`explorer_fast`/`implementer_recovery`/`reviewer_deep`) via `_ROLE_ALIASES`; still echoes requested role | `proofloop_core/role_view.py` | `test_role_view.py`: `test_canonical_orchestrator_role_names_accepted`, `test_reviewer_deep_canonical_gets_assumptions` |
| T-P4 | `ensure_codegraph(mock=True)` gated behind `PROOFLOOP_ALLOW_MOCK_CONTEXT=1` (fail-closed BLOCKED otherwise — a simulated index can no longer fabricate READY) | `proofloop_core/repository_context.py` | `test_repository_context.py`: `test_mock_requires_explicit_opt_in` + updated `test_mock_initializes_index_evidence_when_opted_in` |
| T-P5 | `record_attempt(..., classification=None)` now propagates classification; added CLI `--classification` — external attempt path can now reach `RETURN_TO_PLANNER` (parity with orchestrator inline loop) | `proofloop_core/attempts.py`, `proofloop_core/cli.py` | `test_attempts.py`: `test_classification_enables_return_to_planner` |

### Phase 1 — Event Bus + RequestEnvelope ✅ (all 5 tasks)

| Task | Change | Files | Tests |
|---|---|---|---|
| T-1.1 | `ProofLoopEvent` frozen dataclass (V2 §18.1) + `from_v1_dict` projection + `to_dict` (V2 camelCase). In-memory typed view; **does not change the persisted v1 `events.jsonl` format**. | `proofloop_core/events.py` | `test_events.py`: `ProofLoopEventTest` |
| T-1.2 | `EventBus` pub/sub (`subscribe`→unsubscribe fn, `publish`, `subscriber_count`). `EventEmitter` now owns `self.bus` (default empty → zero behavior change) and publishes a `ProofLoopEvent` after write+render. Subscriber exceptions are isolated (never break the log). | `proofloop_core/events.py` | `test_events.py`: `EventBusTest` (fan-out, exception isolation, unsubscribe, default-empty) |
| T-1.3 | `V2_EVENT_TYPES` frozenset = canonical V2 §18.2 vocabulary (registry only; emission of not-yet-produced types like `grounding.*`, `prompt_ir.*`, `verdict.issued` comes with later phases — NOT enforced in `emit`). | `proofloop_core/events.py` | `test_events.py`: `EventTypeRegistryTest` |
| T-1.4 | `RequestEnvelope` immutable module (V2 §5.1): exact raw bytes + `sha256:` hash, whitespace preserved, empty rejected, frozen. Wired into `orchestrator.run()` → emits `request-envelope.json` + `request.envelope_created` event. **`.strip()` kept for the legacy pipeline** (design-01 Stage 0 defers strip removal to a separate slice); exact bytes preserved via new `self.raw_request`. | `proofloop_core/request_envelope.py` (NEW), `proofloop_core/orchestrator.py` | `test_request_envelope.py` (7 unit) + `test_orchestrator.py::test_run_emits_immutable_request_envelope_with_exact_raw_text` (integration) |
| T-1.5 | Secrets redacted (`redact_secrets`) on `message` + `data` **before** persist/render/return/publish — one scrubbed object everywhere. | `proofloop_core/events.py` | `test_events.py`: `RedactionTest` |

**New feature flags / env vars introduced**: `PROOFLOOP_ALLOW_MOCK_CONTEXT=1` (T-P4). No new flags for Phase 1 (EventBus/envelope are additive-by-default).

**New run artifact**: `.proofloop/runs/<id>/request-envelope.json`.

### Phase 2 — Watch/TUI panels ✅ (T-2.1/T-2.2)

| Task | Change | Files | Tests |
|---|---|---|---|
| T-2.1 | Added `WatchPanels`, a read-only role/proof/budget projection that consumes only typed `ProofLoopEvent` values. `watch_events` remains a replay adapter and may publish parsed events into a caller-provided EventBus; the panel itself never reads artifact files. Timeline filters do not remove global run-state events from the panel. `render_watch_panels` produces deterministic terminal output. | `proofloop_core/watch.py` | `test_watch.py`: replay twice through fresh EventBus instances yields the same snapshot; filtered timeline still yields a complete panel; CLI panel replay and deterministic rendering covered. |
| T-2.2 | Added explicit `run --watch` and `watch --panels` flags. Both attach panels to EventBus; JSONL event stdout remains machine-readable because panel output goes to stderr. `run_proofloop`/orchestrator accept an optional injected EventBus without changing the default path. | `proofloop_core/cli.py`, `proofloop_core/orchestrator.py` | `test_orchestrate_cli.py`: live fixture panel output and JSONL stdout preservation. |

**New feature flags / CLI options**: `run --watch`, `watch --panels`. They are opt-in; the default run and watch event rendering paths are unchanged. No new artifact or JSON key was introduced.

### Phase 3 — IntentGate ✅ (all 5 tasks)

| Task | Change | Files | Tests |
|---|---|---|---|
| T-3.1 | `IntentKind`, `ClarityLevel`, `AuthorityLevel` enums | `proofloop_core/intent_gate.py` (NEW) | `test_intent_gate.py`: `test_intent_enums` |
| T-3.2 | Deterministic classifier + fallback structure | `proofloop_core/intent_gate.py` | `test_intent_gate.py`: tested via `evaluate_intent` |
| T-3.3 | Owner-decision policy (≤1 question/run) | `proofloop_core/intent_gate.py` | `test_intent_gate.py`: `test_owner_question_limit` |
| T-3.4 | Authority non-escalation tests | `proofloop_core/intent_gate.py` | `test_intent_gate.py`: `test_authority_non_escalation` (분석≠mutate, 구현≠push, PR≠merge) |
| T-3.5 | Prompt-injection-as-data guard + `intent-gate.json` | `proofloop_core/intent_gate.py`, `proofloop_core/orchestrator.py` | `test_intent_gate.py`: `test_prompt_injection_as_data` |

**New artifact**: `.proofloop/runs/<id>/intent-gate.json`.
**New events**: `intent_gate.started`, `intent_gate.completed`, `intent_gate.owner_decision_required`, `intent_gate.blocked`.

**Phase 3 verification executed**:

```text
python3 -m pytest tests/deterministic/test_watch.py tests/orchestration/test_orchestrate_cli.py -q
→ 17 passed

python3 -m pytest tests/deterministic tests/orchestration -q
→ 305 passed, 4 failed, 1 skipped, 9 subtests passed

python3 -m compileall -q proofloop_core
→ pass
```

---

## 3. Files touched by this migration

Production code:
- `proofloop_core/request_envelope.py` (NEW)
- `proofloop_core/events.py` (EventBus, ProofLoopEvent, V2_EVENT_TYPES, redaction, bus wiring)
- `proofloop_core/orchestrator.py` (envelope emit + `self.raw_request`; T-P2 status key)
- `proofloop_core/host_runner.py` (T-P1)
- `proofloop_core/role_view.py` (T-P3)
- `proofloop_core/repository_context.py` (T-P4)
- `proofloop_core/attempts.py` (T-P5)
- `proofloop_core/cli.py` (T-P5 `--classification`; Phase 2 watch/panel flags and JSONL preservation)
- `proofloop_core/watch.py` (Phase 2 EventBus-backed panel projection + deterministic renderer)
- `proofloop_core/orchestrator.py` (optional EventBus injection for `run --watch`; Phase 3 IntentGate shadow wiring)
- `proofloop_core/intent_gate.py` (NEW)

Tests:
- `tests/deterministic/test_request_envelope.py` (NEW)
- `tests/deterministic/test_events.py`, `test_role_view.py`, `test_repository_context.py`, `test_attempts.py`
- `tests/orchestration/test_orchestrator.py`
- `tests/deterministic/test_watch.py`
- `tests/orchestration/test_orchestrate_cli.py`
- `tests/deterministic/test_intent_gate.py` (NEW)

**No commits made.** The working tree also contains unrelated in-progress edits (see §4); committing is left to the maintainer so migration changes are not bundled with that work.

---

## 4. Known pre-existing failures (NOT this migration — left untouched by user decision)

These are intentional but unfinished refactors already in the working tree, with tests not yet updated. They are out of the migration plan's scope.

- **B — antigravity workflow frontmatter** (3 tests): `hosts.py::antigravity_workflow()` added `name: proofloop` to frontmatter; tests assert `startswith("---\ndescription:")`. Failing: `test_antigravity_adapter_has_recognizable_frontmatter`, `test_antigravity_project_install`, `test_antigravity_user_install_writes_both_skill_locations_and_workflow`. Fix = update those assertions to the new frontmatter, once the change is confirmed final.
- **C — gemini model-id/launcher refactor** (1 test): `runtime.py` renamed gemini model IDs to display strings (`Gemini 3.1 Pro (High)`) and changed launcher `gemini`→`agy`; `test_runtime_goal_memory.py::test_goal_registry_routes_roles_across_available_runtimes` still mocks the old `gemini` binary. This intersects `MIGRATION_CONSTRAINTS.md §4.9` (needs a canonical model registry / owner decision). Do NOT lock in test changes here without confirming the intended final model identity.
- **D — unrelated whitespace diagnostic**: `git diff --check` currently reports trailing whitespace at `scripts/run_host_live.py:192` and `:211`. Phase 2 did not modify this file; do not fold it into a migration commit without maintainer direction.

---

## 5. Next up (per `IMPLEMENTATION_PLAN_V2.md §3` and `PHASE_TASK_INDEX.md`)

Immediate candidates (spine, low-risk, additive):
- **Phase 4 Grounding Snapshot** -> **Phase 5 Compiler shadow** -> **Phase 6 activate T2/T3**, etc.

**Owner decisions still open before their phases** (`MIGRATION_CONSTRAINTS.md §4`): `UNPROVEN` vs `PARTIAL` semantics (Phase 10); evidence levels L0–L4 vs type taxonomy (Phase 10); 6-axis workload bands (Phase 6); meta-compile vs recovery budget interaction (Phase 11); canonical model registry (Phase 8/host work — overlaps failure C); surface-execution harness scope.

### How to leverage already-built-but-unwired bridge modules
When you reach the relevant phase, wire (don't rebuild) these existing, tested modules:
- `execution_brief.py` → Phase 5 (RefinedIntentContract composer)
- `role_view.py` → Phase 5/8 (role projection; canonical names now accepted after T-P3)
- `reconciler.py` → Phase 5 (contract validator / anti-fabrication)
- `live_evidence.py` → Phase 10 (tamper-resistant evidence validation)
- `capability_contract.py` → Phase 9 (HostCapability from evidence)
- `ProofLoopEvent`/`EventBus` (this phase) → Phase 2 (TUI subscribes to the bus)

---

## 6. Progress checklist

- [x] Phase P — prerequisite fixes (T-P1..T-P5)
- [x] Phase 1 — EventBus + RequestEnvelope (T-1.1..T-1.5)
- [x] Phase 2 — Watch/TUI panels (T-2.1/T-2.2)
- [x] Phase 3 — IntentGate
- [x] Phase 4 — Grounding Snapshot
- [x] Phase 5: Fast Implementer + Recovery bounds (C7)
- [x] Phase 6: Deep Review + Blueprint compilation (C4, C8)
- [x] Phase 7: Execution Blueprint V2 (IMPLEMENTATION) (C5)
- [x] Phase 8: Prompt IR + renderers (C9, C10, C18)
- [x] Phase 9 — Host Adapter + capability matcher
- [x] Phase 10 — Proof Graph + Truth Engine V2 (PARTIAL, live_evidence)
- [x] Phase 11 — Recovery Controller V2
- [x] Phase 12 — Benchmark routing vs prompt effect
