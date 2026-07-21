# ProofLoop — Current Architecture Map

Status: Repository-verified as of branch `main`, commit baseline 2026-07-21
Method: Direct source reading of the decision core (`orchestrator.run()`, `intent.py`, `strategy.py`, `truth.py`, `proof_graph.py`, `workload.py`, `cli.py`) plus four parallel subsystem analyses covering all 43 `proofloop_core/*.py` modules and the `.proofloop/runs/` artifacts.
Authority note: This document describes what the code **does today**. Where a conclusion is inferred rather than executed, it is marked `(inferred)`. No test was executed; no test is claimed to pass.

---

## 0. Executive summary

ProofLoop today is a **CLI-driven, phase-machine orchestration kernel** that compiles a raw request into a scope-preserving intent contract, classifies it into a strategy/tier, invokes external coding-agent CLIs (`claude`, `codex`, `agy`) as isolated per-role subprocesses, gates every result behind deterministic checks + a diff/scope guard + an isolated model reviewer, and only then computes a verdict from artifacts on disk.

Crucially, several V2 concepts already exist in embryonic or evolved form:

- An **evidence-authority proof graph** with staleness (`proof_graph.py`).
- A **deterministic, artifact-reading truth engine** (`truth.py`) — model claims are already not trusted.
- **T0–T3 tiering** with ratchet-up (`strategy.py`).
- A **persisted JSONL event log** with lifecycle events and a `watch` follower (`events.py`, `watch.py`).
- **Requested-vs-observed model** discipline throughout host invocation.

And several V2 bridge modules are **already built but not yet wired into `run()`**: `execution_brief.py`, `role_view.py`, `reconciler.py`, `live_evidence.py`, `capability_contract.py` (the H01-S1 / H02-S1 / H03-S1 approved slices from `docs/designs/`).

The largest genuine gaps are: no `IntentGate` (IntentKind/ClarityLevel/AuthorityLevel enums), no Grounding-Wave-0 fact snapshot, no Prompt IR / model-aware prompt renderer, no cross-host capability matcher (one adapter per run), and no `PARTIAL` verdict (the code uses `UNPROVEN`).

---

## 1. Module inventory (all 43 core modules)

Clusters: **ENT** entry/orchestration · **HST** host/execution · **PRF** proof/verification · **OBS** observability · **PRM** prompting/skills · **BMK** benchmark · **LIB** shared lib · **BRG** built-but-unwired V2 bridge.

| Module | LOC | Cluster | Purpose (verified) |
|---|---:|---|---|
| `orchestrator.py` | 2131 | ENT | `ProofLoopOrchestrator` phase machine; entrypoints `orchestrate`/`converge_goal`/`run_proofloop`; role invocation, repair loop, final verify+review, truth gate. |
| `cli.py` | 448 | ENT | argparse dispatch for ~25 subcommands; maps `--strategy` to enum; sets exit code from `verdict`. |
| `runtime.py` | 277 | HST | `RUNTIME_SPECS`, `CONTROLLER_ROUTES`, `GOAL_ROUTES`, `RuntimeRegistry.resolve` (ACP-preferred, legacy-CLI fallback). |
| `run_state.py` | 57 | ENT | `start_run`/`finalize_run`/`abort_run`; `.proofloop/active-run.json` lifecycle. |
| `goal.py` | 98 | ENT | `GoalFSM` + `build_goal_contract` for `--mode goal` convergence. |
| `strategy.py` | 210 | ENT | `classify_request` → 4 strategies + T0–T3 tier; `reclassify_after_diff`, `_apply_repository_signals` (ratchet-up). |
| `workload.py` | 54 | ENT | `probe_repository_signals` — repo *signals* (public/persistent/critical/greenfield). NOT the tier scorer. |
| `intent.py` | 107 | ENT | `compile_intent` — deterministic `IntentContract` (objective, AC, constraints, non-goals, authority string, unknowns, risk signals, targets). |
| `attempts.py` | 40 | ENT | `record_attempt` — external attempt-recording path (used by CLI, not by orchestrator's inline loop). |
| `repair.py` | 35 | ENT | `decide_next` — pure action decider (`RUN_FAST`/`RETRY_FAST`/`RUN_RECOVERY`/`RETRY_RECOVERY`/`RETURN_TO_PLANNER`/`REVIEW`/`BLOCKED`). |
| `preflight.py` | 49 | ENT | `preflight` — git repo / status / lang markers / codegraph probe. Hard-gates non-git. |
| `hosts.py` | 254 | HST | Host capability metadata, `probe`, Codex agent-file gen, `detect_model` regex, `antigravity_workflow()` markdown relay. |
| `host_runner.py` | 312 | HST | `invoke_role` — legacy-CLI subprocess role invocation per host. **Contains `_require_executable` NameError bug (antigravity).** |
| `process_runner.py` | 313 | HST | `ProcessRunner` — generic subprocess with streaming, heartbeats, timeout, SIGTERM→SIGKILL. |
| `acp_runner.py` | 292 | HST | `invoke_acp_role` — structured ACP (Agent Client Protocol) session via optional `acp` SDK. |
| `adapters.py` | 224 | HST | `ExternalCLIAdapter` (the only `HostAdapter`); dispatches ACP vs legacy; parent-owned artifact extraction (`PROOFLOOP_RESULT_BEGIN/END`). |
| `external_loop.py` | 165 | HST | `run_external_loop` — separate, host-agnostic command-based retry loop (parallel/legacy path). |
| `output_parsers/` | — | HST | `base.py` + `codex/claude/gemini/antigravity.py` — per-host JSONL→`NormalizedHostEvent`. |
| `checks.py` | 152 | PRF | `run_checks` — runs task `required_checks` as subprocesses; PASS/FAIL by exit code; hashes outputs. |
| `truth.py` | 82 | PRF | `build_truth_report` — the single verdict aggregator; `VALID_STATES={PROVEN,UNPROVEN,FAILED,BLOCKED}`. |
| `proof_graph.py` | 105 | PRF | `ProofGraph`/`ProofObligation`/`Evidence` — authority ladder (`MODEL_CLAIM`=0…`EXTERNAL_OBSERVATION`=4) + `STALE_EVIDENCE` on revision mismatch. |
| `assurance.py` | 257 | PRF | `audit_claims` + `audit_simplicity` — claim ledger (SUPPORTED/MISSING/CONTRADICTED) + bloat/overbuild audit. |
| `diff_guard.py` | 211 | PRF | `inspect_diff` — scope/protected-path/test-integrity/budget guard via git-diff regex. |
| `fingerprint.py` | 47 | PRF | `fingerprint_check_report` — stable failure hash for loop-detection. |
| `git_snapshot.py` | 78 | PRF | `snapshot_worktree` (index-isolated ephemeral commit), `changed_source_files`. |
| `repository_context.py` | 75 | PRF | `ensure_codegraph` — drives external `codegraph` index. **`mock=True` fabricates `READY`.** |
| `reconciler.py` | 54 | BRG | `reconcile_proposal` — blocks invented facts/criteria, hidden unknowns, authority widening. **Not wired (tests only).** |
| `live_evidence.py` | 399 | BRG | `validate_bundle` — L1 tamper-resistant evidence-bundle validator; ignores self-claimed verdict. **Not wired.** |
| `capability_contract.py` | 546 | BRG | `evaluate_capability` — 6-axis capability/claim evaluation; attestation states forbidden; S1 always `NOT_EVALUATED`. **Not wired.** |
| `execution_brief.py` | 276 | BRG | `compose_execution_brief` + `validate_execution_brief` — hash-chained shadow brief. **Not wired.** |
| `role_view.py` | 77 | BRG | `project_role_view` — per-role minimal projection. **Not wired; uses short role names.** |
| `task_brief.py` | 147 | HST | `TaskBrief`/`CheckSpec`/`ChangeBudget`/`SimplicityPlan`; `load_task_brief`. |
| `events.py` | 151 | OBS | `EventEmitter` (single-writer append-only `events.jsonl`) + `validate_event` (schemaVersion "1"). |
| `renderers/` | — | OBS | `human/jsonl/quiet` — **event display** renderers (NOT prompt renderers). |
| `trace.py` | 63 | OBS | `summarize_trace` — routing-claim audit over `model-trace.jsonl`. |
| `watch.py` | 110 | OBS | `watch_events` — poll-based tail-follow of `events.jsonl` (not a TUI). |
| `redact.py` | 27 | OBS | `redact_secrets` — heuristic regex over 4 key patterns. |
| `memory.py` | 85 | OBS | `prepare_memory`/`write_memory` — durable markdown memory files. |
| `usage.py` | 337 | OBS | `TokenLedger`, `UsageObservation` (typed) — token/cost normalization + aggregation. |
| `tokscale.py` | 211 | OBS | `TokScaleAdapter` — external token reconciliation CLI. |
| `skill_registry.py` | 544 | PRM | `SkillContract`/`SkillRegistry` — dependency-aware, budgeted skill resolution. |
| `skill_qualification.py` | 282 | PRM | `qualify_domain_packs` — trigger precision/recall eval; behavior eval is a stub. |
| `domain_runtime.py` | 463 | PRM | repo fingerprint, `classify_task_types` (regex), `select_reference_slices`, `run_pack_helper`. |
| `benchmark.py` | 1091 | BMK | multi-arm benchmark runner; paired bootstrap CIs; `build_single_agent_prompt` (its own prompt path). |
| `benchmark_environment.py` | 266 | BMK | SWE-Skills-Bench Docker evaluator; `parse_test_output`, `SWETrialEnvironment`. |
| `swe_skills_bench.py` | 118 | BMK | build/inspect SWE suite from upstream catalog. |
| `io.py` | 28 | LIB | `read_json`/`write_json`/`sha256_file`. |
| `__init__.py` | 3 | LIB | package marker. |

---

## 2. End-to-end execution path (`orchestrate` mode)

Verified from `orchestrator.run()` (`orchestrator.py:269`). Phase transitions via `self.transition(state)`.

```
cli.main() [cli.py:363]  →  orchestrate() [orchestrator.py:2024]  →  ProofLoopOrchestrator.run()
  INIT       start_run [run_state.py:12] → EventEmitter → compile_intent [intent.py:59] → intent-contract.json
  PREFLIGHT  preflight [preflight.py:20]; non-git → OrchestrationError("GIT_REPOSITORY_REQUIRED", BLOCKED)
             snapshot_worktree [git_snapshot.py:23] → baseline commit
  CAPABILITY adapter.probe(); unavailable → OrchestrationError("HOST_CLI_MISSING", BLOCKED)
  CLASSIFY   probe_repository_signals [workload.py:14] → classify_request [strategy.py:80] → strategy.json
             _initialize_proof_graph [orchestrator.py:738]  (obligations: intent-alignment, deterministic-checks,
                                                              scope-integrity, simplicity, + AC-* per criterion)
             _resolve_skills [orchestrator.py:754]  (tier budget T0=20k…T3=360k)
             if REPOSITORY_ANALYSIS and mode!=audit → OrchestrationError("ANALYSIS_ORCHESTRATION_NOT_IMPLEMENTED", BLOCKED)
  CONTEXT    if strategy.context_required: ensure_codegraph [repository_context.py:36] (hard gate)
  PLAN/DIRECT
             if planner_required:  [explorer_fast]? → planner_deep → (HIGH_RISK: reviewer_deep plan review)
             else:                 _run_direct_bootstrap (single implementer_fast)
  (reclassify) _maybe_reclassify_after_diff [orchestrator.py:972] → strategy.reclassify_after_diff (ratchet-up)
  EXECUTE    per task: _execute_task [orchestrator.py:1269]
               implementer_fast → run_checks + inspect_diff → attempt → repair.decide_next
               actions: REVIEW | RETRY_FAST | RUN_RECOVERY(→ tier↑ T2) | RETRY_RECOVERY | RETURN_TO_PLANNER | BLOCKED
  FINAL      _final_verification_and_review [orchestrator.py:1577]
               aggregate_task → run_checks + inspect_diff on full baseline diff (fail → FINAL_VERIFICATION_FAILED, FAILED)
               review: DETERMINISTIC_FAST_LANE stub (adaptive + !reviewer_required)  OR  reviewer_deep
  TRUTH      _finalize_truth [orchestrator.py:1940]
               summarize_trace → claims.json → build_assurance_report → build_truth_report [truth.py:19]
               finalize_run → verdict ∈ {PROVEN, UNPROVEN, FAILED}
  (exception paths bypass truth): OrchestrationError → _finalize_terminal(verdict, code) → {BLOCKED|FAILED}
```

Exit code: `orchestrate`/`goal` → `0 if verdict == "PROVEN" else 2` (`cli.py:443`).

### 2.1 Other entrypoints
- **`goal`** (`converge_goal`): same machine with `GoalFSM` transitions and `build_goal_contract`; `--max-cycles`/`--max-replans`.
- **`run`** (`run_proofloop`): `--mode adaptive|goal|audit`, `--skills enabled|disabled`. `adaptive` enables the `DETERMINISTIC_FAST_LANE` review skip for low tiers.
- **`audit`**: the only path that executes `REPOSITORY_ANALYSIS` (`_run_audit`, `orchestrator.py:1090`) — one read-only `explorer_fast`, returns `PROVEN` if source unmutated (mutation → `AUDIT_SOURCE_MUTATION`, FAILED).
- **`watch`**: `watch_events` tails `events.jsonl`.
- **`benchmark`/`compare`/`qualify-skills`/`swe-*`**: evaluation harnesses (separate prompt path in `benchmark.py`).

---

## 3. Roles and model routing

Canonical role set (`orchestrator.py:40`, `hosts.py`): `planner_deep`, `explorer_fast`, `implementer_fast`, `implementer_recovery`, `reviewer_deep`.

- Model per (controller_host, role) is hardcoded in `runtime.CONTROLLER_ROUTES` (`runtime.py:98`), e.g. codex `implementer_fast`→`gpt-5.6-terra`, claude-code `reviewer_deep`→`opus`, antigravity route model = sentinel `current-session-model`. An account-specific model such as Fable is an explicit routing override, never an assumed default.
- `RuntimeRegistry.resolve` (`runtime.py:208`) picks ACP transport if `acp` SDK + ACP launcher present, else legacy CLI, else falls back to controller host (`fallback=True`).
- **Requested vs observed model** is a first-class distinction: `requestedModel` always recorded; `observedModel` only from parsed host output; mismatch → `routingDivergence`/`MODEL_ROUTING_UNPROVEN` (`truth.py:45`).

---

## 4. Proof / verdict model today

- **Deterministic gates**: `checks.json` (exit-code PASS/FAIL), `diff-guard.json` (scope/protected/test-integrity/budget), `review.json` (APPROVED/FIX_REQUIRED/DESIGN_CONFLICT/CANNOT_VERIFY + simplicityVerdict), `proof-graph.json` (obligation closure), `assurance-report.json` (claim + simplicity audit), `model-trace-summary.json` (routing).
- **Verdict** (`truth.build_truth_report`): any blocker → `FAILED`; else any unproven → `UNPROVEN`; else `PROVEN`. No weighting/quorum. `BLOCKED` is declared in `VALID_STATES` but never returned by this function (only via orchestrator exceptions).
- **Evidence authority ladder** (`proof_graph.py:7`): `MODEL_CLAIM`=0 < `MODEL_REVIEW`=1 < `STATIC_INSPECTION`=`DIFF_GUARD`=2 < `DETERMINISTIC_CHECK`=3 < `EXTERNAL_OBSERVATION`=4. An obligation closes only if evidence authority ≥ required authority, verdict PASS, and `revision` matches (else `STALE_EVIDENCE`).
- **Independent reviewer**: `reviewer_deep` is a *structurally* isolated fresh subprocess reading only the git-snapshot baseline ("Do not trust implementer summaries", `orchestrator.py:1662`). BUT independence is process-level, not guaranteed different-model; and for adaptive low tiers it is replaced by a `DETERMINISTIC_FAST_LANE` **self-approval stub** (`orchestrator.py:1631`) that writes `verdict:"APPROVED"` with no reviewer at all.
- **Staleness**: the *check* exists (`proof_graph.py:78`); the *trigger* that bumps `obligation.revision` after source change was not confirmed `(inferred gap)`.

---

## 5. Observability today

- **Event store**: real single-writer append-only `events.jsonl` via `EventEmitter` (`events.py:53`), schemaVersion `"1"`, monotonic sequence, corruption recovery (`events.corrupt-tail.log`). **No pub/sub Event Bus, no `ProofLoopEvent` dataclass** — events are validated dicts with fields `eventId/runId/timestamp/type/phase/message/level/taskId/data`.
- **Watch**: `watch_events` (`watch.py:39`) is a stdout poll-tail with `--task`/`--level` filters; not a TUI.
- **Display renderers**: `human/jsonl/quiet` (`renderers/`) format events for output only. These are **not** prompt renderers.
- **Typed streams**: only `usage.py` (`UsageObservation`) is dataclass-backed and persisted.
- **Redaction**: `redact_secrets` heuristic; `_print` applies it at CLI output (`cli.py:36`). Whether it runs before `events.jsonl`/`stdout.log` persistence was not confirmed `(inferred open question)`.

---

## 6. Prompting & skills today

- **No Prompt IR, no model-aware prompt renderer.** Role prompts are inline f-strings in `orchestrator.py` (`:1125` planner, `:1164` fast implementer, `:1246`, `:1319`, `:1558` recovery, `:1662` reviewer, `:1769`) and a separate prompt path in `benchmark.py:887` (`build_single_agent_prompt`).
- **Two divergent skill-injection strategies**: orchestrator's `_prompt_with_selected_skills` (`orchestrator.py:927`) appends `SKILL.md` **file paths** ("Read and follow"); `benchmark.build_builtin_domain_context` (`benchmark.py:720`) inlines `SKILL.md` **contents**.
- **Skill resolution is sophisticated** (`skill_registry.py`): `SkillContract` schema, dependency graph, cycle detection, token-budget packing, compatibility vs a repo fingerprint; `domain_runtime.classify_task_types` (regex) selects domain packs; `select_reference_slices` picks reference files under a token cap. This is the most V2-ready subsystem.
- **Skill artifacts absent in sampled runs**: none of 5 inspected `.proofloop/runs/` contained `skill-registry.json`/`skill-resolution.json`/`domain-selection.json` — `--skills` is only exposed on the `run` subcommand `(inferred: goal/orchestrate skip `_resolve_skills` artifact emission)`.

---

## 7. Host abstraction today

- Formal interface: `adapters.HostAdapter(Protocol)` with `probe()` + `invoke(RoleInvocation)`. Only implementation: `ExternalCLIAdapter`.
- **Two parallel invocation mechanisms**: legacy CLI (`host_runner.invoke_role` → `process_runner`) and ACP (`acp_runner.invoke_acp_role`). Selected per role by `RuntimeRegistry.resolve`.
- **One adapter per run** — no `ExecutionBlueprint → Capability Matcher → strategy` step; capability is `hosts.probe()` for the single selected host.
- Host fidelity: Codex and Claude Code have real dual-transport (CLI + ACP) invocation and real parsers. AGY is the sole CLI runtime for Gemini-family models and Antigravity integration; no `gemini` executable is invoked. Antigravity remains `ROLE_ROUTING_ONLY` for its current-session model, while AGY can be selected as a routed worker in goal mode.

---

## 8. Already-built-but-unwired V2 bridge modules (H01/H02/H03 slices)

These are the approved slices from `docs/designs/01|02|03-*.md` (roadmap G-01/G-02/G-03/G-18/G-19). They are **pure validators/composers with unit tests but no caller in `run()`**:

| Module | Maps to V2 | Wired into `run()`? |
|---|---|---|
| `execution_brief.py` | §8 Grounded Prompt Compiler output (RefinedIntentContract), §12 Blueprint | No — `compose_execution_brief` not called by orchestrator |
| `role_view.py` | §15.2 role context bounding, §13 Prompt IR projection | No — short role names mismatch canonical set |
| `reconciler.py` | §8.4/§9 Contract Validator (anti-fabrication) | No — tests only |
| `live_evidence.py` | §21 Evidence, §22 Truth (tamper-resistant validation) | No — tests only |
| `capability_contract.py` | §16 HostCapability, §17 model-selection evidence | No — orchestrator sets ad-hoc evidence strings instead |

---

## 9. Confirmed bugs, stubs, and simulated paths (verified)

1. **`_require_executable` NameError** — `host_runner.py:82` (antigravity branch) references an undefined name; any real antigravity role invocation raises `NameError`. Reachable via `invoke-role --host antigravity` and adapter fallback. (verified: AST scan 1 ref / 0 defs)
2. **`DETERMINISTIC_FAST_LANE` self-approval** — `orchestrator.py:1631` writes `review.json = {verdict:"APPROVED", reviewMode:"DETERMINISTIC_FAST_LANE"}` with no reviewer for adaptive low tiers. (verified)
3. **`ensure_codegraph(mock=True)`** — `repository_context.py:44` fabricates `status:"READY"` by `touch()`-ing a fake db; reachable via `cli.py:400 --mock`. (verified)
4. **Possible dead conditional** — `orchestrator.py:388` checks `context.get("verdict")` but `ensure_codegraph` returns `"status"`, never `"verdict"`. (inferred)
5. **`role_view` role-name mismatch** — `_ROLE_FIELDS` uses `explorer`/`recovery`/`reviewer` vs canonical `explorer_fast`/`implementer_recovery`/`reviewer_deep`; `project_role_view` would raise on canonical names unless a translation layer exists. (inferred)
6. **`gemini` and `antigravity` share launcher `agy`** — `runtime.py:82,92`. Needs confirmation it is intentional. (verified fact / intent inferred)
7. **`capability_contract` unwired** — no runtime call site emits records / calls `evaluate_capability`. (inferred within read scope)
8. **`skill_qualification` behavior eval is a stub** — `PENDING_AGENT_BEHAVIOR_EVAL` (`skill_qualification.py:54`). (verified)
9. **`attempts.record_attempt` hardcodes `classification=None`** — external attempt path can never trigger `RETURN_TO_PLANNER`. (verified)
10. **`_is_ephemeral_generated` duplicated** verbatim in `diff_guard.py` and `git_snapshot.py`. (verified)

STATUS.md self-labels current host E2E tests as `SIMULATED_ORCHESTRATION` / `SIMULATED_HOST_E2E`; the release verdict is `FAIL` pending authenticated host runs.

---

## 10. Run artifact inventory (verified from `.proofloop/runs/<id>/`)

Top-level: `run.json`, `request.json`, `state.json`, `strategy.json`, `preflight.json`, `capability.json`, `repository-context.json`, `repository-fingerprint.json`, `intent-contract.json`, `exploration.json`, `plan.json`, `plan.md`, `review.json`, `diff-guard.json`, `claims.json`, `proof-graph.json`, `truth-report.json`, `assurance-report.json`, `goal-state.json`, `goal-transitions.jsonl`, `transitions.jsonl`, `model-trace.jsonl`, `model-trace-summary.json`, `events.jsonl`.
Subdirs: `checks/` (per-check `.stdout.log`/`.stderr.log`/`checks.json`), `invocations/<NN>-<runtime>-<role>/` (`invocation.json`, `stdout.log`, `stderr.log`), `tasks/TASK-*.json`, `usage/usage-events.jsonl`, `usage/usage-summary.json`.
Variable: top-level `invocations.jsonl`, `usage/usage-reconciliation.json`, `usage/tokscale-raw.json` (only on certain modes).
Absent in sampled runs: `skill-registry.json`, `skill-resolution.json`, `domain-selection.json`.

Compare to V2 §19 target (`.proofloop/runs/<run-id>/`): current is close but lacks `request-envelope.json`, `intent-gate.json`, `grounding-snapshot.json`, `refined-request.json`, `execution-blueprint.json`, `prompt-manifest.jsonl`, `prompt-revisions.jsonl`, `verdict.json`, `evidence/` bundle tree, `failure-fingerprints.jsonl`, `surface-evidence.jsonl`, `cleanup-ledger.jsonl`.
