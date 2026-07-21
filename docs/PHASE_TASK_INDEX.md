# ProofLoop — Phase / Task Index & Traceability

Maps every V2 capability to concrete tasks, code touchpoints, tests, dependencies, and explicit completion criteria.
Cross-refs: capability IDs `C1…C20` from `docs/IMPLEMENTATION_PLAN_V2.md §2`; phases from `§3`; constraints/decisions from `docs/MIGRATION_CONSTRAINTS.md`.
No task is started or implemented by this document.

---

## 1. Task list (by phase)

Legend — Dep: prerequisite task(s). Test: file(s) to add/extend. Done = completion criterion (must be *executed*, not assumed).

### Phase P — Prerequisite fixes
| Task | Description | Code touchpoints | Test | Dep | Done |
|---|---|---|---|---|---|
| T-P1 | Fix `_require_executable` NameError | `host_runner.py:82` | `tests/deterministic/test_host_adapters.py` | — | antigravity `invoke_role` returns structured BLOCKED/result, no `NameError` (mocked binary) |
| T-P2 | Resolve `context.get("verdict")`/`status` mismatch | `orchestrator.py:388`, `repository_context.py:36` | `test_repository_context.py` | — | context-gating behavior matches intent; test asserts BLOCKED on real failure |
| T-P3 | Fix `role_view` role-name mismatch | `role_view.py:12` | `test_role_view.py` | — | `project_role_view` accepts canonical role names via mapping |
| T-P4 | Gate `ensure_codegraph(mock=True)` to test-only | `repository_context.py:44`, `cli.py:400` | `test_repository_context.py` | — | `mock` unreachable in normal runs; explicit flag required |
| T-P5 | Align `attempts.record_attempt` classification (or deprecate) | `attempts.py:31` | `test_attempts.py` | — | external + inline attempt paths agree, or `attempts` marked deprecated with note |

### Phase 1 — Event Bus + RequestEnvelope (C13, C1, C14)
| Task | Description | Code touchpoints | Test | Dep | Done |
|---|---|---|---|---|---|
| T-1.1 | `ProofLoopEvent` typed dataclass | new `events.py` addition | `test_events.py` | — | typed event round-trips to/from v1 dict |
| T-1.2 | `EventBus` pub/sub over existing writer | `events.py` | `test_events.py` | T-1.1 | multiple subscribers receive events; sequence monotonic; corruption recovery intact |
| T-1.3 | Complete V2 §18.2 event-type coverage | `events.py`, `orchestrator.py` emits | `test_events.py` | T-1.2 | lifecycle/intent/grounding/strategy/proof event types emitted |
| T-1.4 | `RequestEnvelope` + stop `.strip()` | `intent.py`/new `request_envelope.py`, `orchestrator.py:270,292` | new `test_request_envelope.py` | — | exact Unicode + SHA-256 preserved; `request-envelope.json` emitted; explicit_permissions/denials present |
| T-1.5 | Redaction-before-persist verification | `redact.py`, `events.py`, `host_runner.py` | `test_redact.py` | — | secrets masked before `events.jsonl`/`stdout.log` write |

### Phase 2 — Watch/TUI panels (C12 partial)
| Task | Description | Code touchpoints | Test | Dep | Done |
|---|---|---|---|---|---|
| T-2.1 | Proof-obligation + budget panels | `watch.py` | `test_watch.py` | Phase 1 | finished run re-watched reconstructs panels identically |
| T-2.2 | `run --watch` flag | `cli.py`, `orchestrator.py` | `test_orchestrate_cli.py` | T-2.1 | live run observable in second terminal |

### Phase 3 — IntentGate (C2)
| Task | Description | Code touchpoints | Test | Dep | Done |
|---|---|---|---|---|---|
| T-3.1 | IntentKind/ClarityLevel/AuthorityLevel enums | new `intent_gate.py` | `test_intent_gate.py` | — | enums per V2 §6.1–6.3 |
| T-3.2 | Deterministic classifier + low-confidence model hook | `intent_gate.py` | `test_intent_gate.py` | T-3.1 | deterministic first; model only on low confidence |
| T-3.3 | Owner-decision policy (≤1 question/run) | `intent_gate.py` | `test_intent_gate.py` | T-3.2 | repo-answerable facts never asked; ≤1 owner question |
| T-3.4 | Authority non-escalation tests | `intent_gate.py` | `test_intent_gate.py` | T-3.1 | V2 §29.1: 분석≠mutate, 구현≠push, PR≠merge, 배포계획≠deploy |
| T-3.5 | Prompt-injection-as-data guard + `intent-gate.json` | `intent_gate.py`, `grounding` | `test_intent_gate.py` | T-3.1 | V2 §29.2 strings treated as data; injection signal event |

### Phase 4 — Grounding Snapshot (C3)
| Task | Description | Code touchpoints | Test | Dep | Done |
|---|---|---|---|---|---|
| T-4.1 | `GroundingSnapshot` collector (git/instr/manifest/commands/files) | new `grounding.py`, extend `preflight.py`/`repository_context.py` | `test_grounding.py` | Phase 3 | `grounding-snapshot.json` produced; tiered T0–T3 |
| T-4.2 | Dirty-worktree + protected-path recording | `grounding.py`, `git_snapshot.py` | `test_grounding.py` | T-4.1 | user dirty paths preserved and flagged |
| T-4.3 | Stale-grounding detection | `grounding.py` | `test_grounding.py` | T-4.1 | grounding invalidated on repo change |

### Phase 5 — Grounded Compiler (shadow) (C4, C5)
| Task | Description | Code touchpoints | Test | Dep | Done |
|---|---|---|---|---|---|
| T-5.1 | Wire `compose_execution_brief` in shadow | `orchestrator.py`, `execution_brief.py` | `test_execution_brief.py` | Phase 4 | `refined-request-shadow.json` emitted; no exec change |
| T-5.2 | `ProvenanceType` enum + per-field provenance | `execution_brief.py` | `test_execution_brief.py` | T-5.1 | V2 §8.4 provenance on every field |
| T-5.3 | Wire `reconcile_proposal` (T2/T3 shadow) | `orchestrator.py`, `reconciler.py` | `test_reconciler.py` | T-5.1 | invented criteria/widened authority rejected; `reconciliation-report.json` |
| T-5.4 | ≥20-scenario shadow harness + `prompt-diff.json` | `benchmark.py`/new script | `tests/orchestration/` | T-5.1..3 | ≥20 shadow runs; token cost + authority-expansion detection measured |

### Phase 6 — Compiler active for T2/T3 (C4, C6, C7)
| Task | Description | Code touchpoints | Test | Dep | Done |
|---|---|---|---|---|---|
| T-6.1 | Feed T2/T3 roles from RefinedIntentContract via `role_view` | `orchestrator.py`, `role_view.py` | `test_orchestrator.py` | Phase 5, T-P3 | T2/T3 planner/impl use refined contract, not raw prompt |
| T-6.2 | Validation-fail → explicit BLOCKED (no silent fallback) | `orchestrator.py`, `reconciler.py` | `test_orchestrator.py` | T-6.1 | validation failure recorded as BLOCKED |
| T-6.3 | 6-axis `WorkloadScore` over contract+grounding | `strategy.py`, `workload.py` | `test_workload.py`, `test_strategy.py` | Phase 5 | 6 axes computed; ratchet-up retained; T0/T1 regression clean |
| T-6.4 | Meta-compiler self-approval forbidden | `orchestrator.py` | `test_orchestrator.py` | T-6.1 | compiler cannot declare completion (V2 §1.4) |

### Phase 7 — Execution Blueprint V2 (C8)
| Task | Description | Code touchpoints | Test | Dep | Done |
|---|---|---|---|---|---|
| T-7.1 | TaskBrief V2 (criterion_ids, dependencies, interfaces) | `task_brief.py` | `test_task_brief.py` (new) | Phase 6 | each TaskBrief links ≥1 criterion |
| T-7.2 | `ProofPlan` + `SurfaceScenario` schema | `task_brief.py`/new | `test_task_brief.py` | T-7.1 | proof plan schema per V2 §12.3–12.4 |
| T-7.3 | Blueprint validator gate before execution | `orchestrator.py`, new `blueprint validator` | `test_orchestrator.py` | T-7.1 | invalid blueprint blocks execution; obligation↔task coverage asserted |

### Phase 8 — Prompt IR + renderers (C9, C10, C18)
| Task | Description | Code touchpoints | Test | Dep | Done |
|---|---|---|---|---|---|
| T-8.1 | `PromptIR` dataclass from `role_view` | new `prompting/prompt_ir.py` | `test_prompt_ir.py` | Phase 7 | IR per V2 §13.1 |
| T-8.2 | Renderer registry (generic→gpt-5.6→claude→gemini) | new `prompting/renderer*.py`, `configs/renderers.yaml` | `test_prompt_renderers.py` | T-8.1 | `generic-v1` reproduces current prompts; resolution order per V2 §13.3 |
| T-8.3 | Migrate inline f-strings + benchmark path onto IR | `orchestrator.py:1125..1769`, `benchmark.py:887` | `test_orchestrator.py`, `test_benchmark.py` | T-8.2 | single prompt path; benchmark == production prompt source |
| T-8.4 | `prompt-manifest.jsonl` (hash + renderer version) | `orchestrator.py` | `test_prompt_renderers.py` | T-8.2 | V2 §29.7: same contract/authority/proof across renderers; hashes stable |
| T-8.5 | `SkillSlice` compilation (policy fragments per role) | `skill_registry.py`, `domain_runtime.py` | `test_skill_registry.py` | T-8.1 | slices per role (V2 §24.2); no whole-doc dumps |

### Phase 9 — Host Adapter + capability matcher (C11, C19)
| Task | Description | Code touchpoints | Test | Dep | Done |
|---|---|---|---|---|---|
| T-9.1 | Formalize `HostAdapter` (detect/start/stream/cancel/collect) | `adapters.py`, `hosts.py` | `test_host_adapters.py` | Phase P | protocol per V2 §16.1 |
| T-9.2 | `HostCapability` from `capability_contract` records | `capability_contract.py`, `host_runner.py`, `acp_runner.py` | `test_capability_contract.py` | T-9.1 | capabilities from evidence not declaration; attestation forbidden |
| T-9.3 | Blueprint→Capability matcher (downgrade/BLOCK, no fake) | new matcher, `orchestrator.py` | `test_host_adapters.py` | T-9.2 | V2 §29.6: unsupported → downgrade/BLOCKED, never fake success |
| T-9.4 | requested≠observed → `routingDivergence` end-to-end | `host_runner.py`, `acp_runner.py`, `trace.py` | `test_output_parsers.py`, `test_live_runner.py` | T-9.2 | observed model recorded; divergence surfaced |

### Phase 10 — Proof Graph + Truth Engine V2 (C15, C16)
| Task | Description | Code touchpoints | Test | Dep | Done |
|---|---|---|---|---|---|
| T-10.1 | Extend Evidence/Obligation taxonomy (+content_hash/repo_head) | `proof_graph.py` | `test_proof_graph.py` | Phase 7 | V2 §21.3–21.4 fields present |
| T-10.2 | Evidence revision-bump trigger on contract/source change | `orchestrator.py`, `proof_graph.py` | `test_proof_graph.py` | T-10.1 | stale evidence cannot close obligation (V2 §21.5) |
| T-10.3 | Add `PARTIAL` verdict; map/retire `UNPROVEN` | `truth.py:10,61`, `cli.py:443` | `test_truth.py` | T-10.1 | four verdicts; consumers updated in lockstep |
| T-10.4 | Wire `live_evidence.validate_bundle` before external-evidence closure | `truth.py`, `live_evidence.py` | `test_live_evidence.py`, `test_truth.py` | T-10.1 | tamper/stale/reused evidence → no PROVEN (V2 §29.3) |
| T-10.5 | Retire `DETERMINISTIC_FAST_LANE` auto-approval for review-required tiers | `orchestrator.py:1631` | `test_orchestrator.py` | T-10.3 | review-required tiers cannot self-approve |
| T-10.6 | Independent-review-passed obligation for T2/T3 | `proof_graph.py`, `orchestrator.py` | `test_orchestrator.py` | T-10.1 | T2/T3 require real reviewer verdict |

### Phase 11 — Recovery Controller V2 (C17)
| Task | Description | Code touchpoints | Test | Dep | Done |
|---|---|---|---|---|---|
| T-11.1 | Contract-change → evidence invalidation | `orchestrator.py`, `proof_graph.py` | `test_orchestrator.py` | Phase 10 | prior evidence invalidated on contract change (V2 §29.5) |
| T-11.2 | Bounded meta-recompile (allowed conditions only) | `orchestrator.py`, `repair.py` | `test_repair.py` | T-11.1 | no recompile on syntax/lint/type/simple-test fail; caps per V2 §8.6 |
| T-11.3 | Same-fingerprint exhaustion → FAILED/BLOCKED | `repair.py`, `fingerprint.py` | `test_repair.py` | — | infinite same-failure loop impossible (V2 §23.3) |

### Phase 12 — Benchmark (C20)
| Task | Description | Code touchpoints | Test | Dep | Done |
|---|---|---|---|---|---|
| T-12.1 | Add arms A–F (routing vs prompt isolation) | `benchmark.py` | `test_benchmark.py` | Phase 8 | arms per V2 §28.1; variables controlled §28.3 |
| T-12.2 | Renderer-effect / meta-compiler-effect isolation | `benchmark.py` | `test_benchmark.py` | T-12.1 | model effect separated from prompt effect |
| T-12.3 | Promotion gate enforcement | `benchmark.py`, `scripts/release_check.py` | `test_release_gate.py` | T-12.1 | no default promotion without §28.4 thresholds |

---

## 2. V2 capability → phase → task traceability matrix

| Cap | V2 § | Phase(s) | Tasks | Primary current code |
|---|---|---|---|---|
| C1 RequestEnvelope | 5.1 | 1 | T-1.4 | `intent.py`, `run_state.py` |
| C2 IntentGate | 6 | 3 | T-3.1..3.5 | `strategy.py`, `intent.py` |
| C3 Grounding | 7 | 4 | T-4.1..4.3 | `preflight.py`, `repository_context.py` |
| C4 Grounded Compiler | 8 | 5,6 | T-5.1,5.2,6.1,6.4 | `execution_brief.py` (unwired) |
| C5 Contract Validator | 9 | 5 | T-5.3 | `reconciler.py` (unwired) |
| C6 Workload 6-axis | 10 | 6 | T-6.3 | `strategy.py`, `workload.py` |
| C7 Strategy shapes | 11 | 6 (+later MULTI_WORKER) | T-6.3 | `strategy.py` |
| C8 Blueprint V2 | 12 | 7 | T-7.1..7.3 | `task_brief.py` |
| C9 Prompt IR/Renderer | 13,14 | 8 | T-8.1..8.4 | inline f-strings, `role_view.py` |
| C10 Role model | 15 | 8,10 | T-8.1,10.6 | `orchestrator.py` roles |
| C11 Host Adapter/Capability | 16 | P,9 | T-P1,9.1..9.4 | `adapters.py`, `capability_contract.py` |
| C12 Observable/DecisionRecord | 17 | 1,2 | T-1.3,2.1 | `events.py`, `strategy.json` |
| C13 Event Bus | 18 | 1 | T-1.1..1.3 | `events.py` |
| C14 Run artifacts | 19 | 1,5,7,10 | T-1.4,5.1,7.1,10.x | run_dir artifacts |
| C15 Proof/Evidence | 21 | 10 | T-10.1,10.2,10.4 | `proof_graph.py`, `live_evidence.py` |
| C16 Truth verdict | 22 | 10 | T-10.3,10.5 | `truth.py` |
| C17 Recovery | 23 | 11 | T-11.1..11.3 | `repair.py`, `fingerprint.py` |
| C18 Skill Slice | 24 | 8 | T-8.5 | `skill_registry.py`, `domain_runtime.py` |
| C19 Cross-host parity (DoD) | 33 | 9 (+ live E-01..E-06) | T-9.1..9.4 | `hosts.py`, live harness |
| C20 Benchmark | 28 | 12 | T-12.1..12.3 | `benchmark.py` |

Every V2 capability C1–C20 maps to at least one phase, task set, code touchpoint, test, dependency chain, and completion criterion above. Capabilities explicitly deferred (out of smallest-safe scope, require their own scoped phase): **surface-execution harness** (V2 §12.4/§29.3 — currently only command-runner exists; surface obligations degrade to `PARTIAL`), **MULTI_WORKER shape** (V2 §11.1), **Gemini visual renderer** (V2 §14.4), and the **web dashboard/OMO/remote telemetry** items excluded by V2 §32.

---

## 3. Global completion criteria (STOP WHEN)

Migration analysis is complete (this deliverable set). Implementation is complete when, per V2 §33 Definition of Done AND `remaining-work.md §D` live gates:

1. All C1–C20 tasks green under `make check` (`scripts/run_tests.py`).
2. RefinedIntentContract drives T2/T3; raw prompt not passed straight to planner.
3. Role prompts generated from Prompt IR; GPT-5.6 + Claude renderers supported; renderer version + prompt hash recorded.
4. Model-message-only, stale-evidence, and scope-violation cannot yield `PROVEN`; `PARTIAL` supported.
5. Independent reviewer + deterministic Truth Engine separated; no self-approval for review-required tiers.
6. Same contract runs on ≥2 hosts where capable; unsupported features surfaced as downgrade/BLOCKED (no fake support); observed model recorded.
7. Bounded, fingerprint-conditioned retries; contract change invalidates prior evidence.
8. Benchmark isolates routing effect from prompt effect; no default promotion without V2 §28.4 thresholds.
9. Cross-host parity claims backed by authenticated live artifacts (E-01…E-06), not simulated — `release-check` not claimed `PASS` without them.

No completion criterion may be marked satisfied without executing the corresponding tests.
