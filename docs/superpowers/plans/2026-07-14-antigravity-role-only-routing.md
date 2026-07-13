# Antigravity Role-Only Routing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make ProofLoop execute installed Antigravity CLI versions without unsupported model flags or false model-routing claims.

**Architecture:** Keep Antigravity on its declared `ROLE_ROUTING_ONLY` capability and construct its invocation from the role-only model table. Codex and Claude Code continue using external model selection unchanged.

**Tech Stack:** Python standard library, Git, `unittest`, fake CLI process fixtures

## Global Constraints

- Never claim a model was requested or resolved when `agy` received no model argument.
- Preserve the opt-in `PROOFLOOP_ANTIGRAVITY_BYPASS_PERMISSIONS=1` behavior.
- Preserve Codex and Claude Code command construction.
- Add no dependency and no speculative Antigravity flag detection.

---

### Task 1: Honest Antigravity role-only execution

**Files:**
- Modify: `proofloop_core/adapters.py:46-56`
- Modify: `proofloop_core/host_runner.py:55-83, 91-95, 192-195`
- Modify: `proofloop_core/hosts.py:32-47`
- Modify: `proofloop_core/orchestrator.py:207-211`
- Modify: `scripts/build_host_adapter.py:123-143`
- Modify: `scripts/install.py:132-170`
- Modify: `scripts/doctor.py:42-55`
- Modify: `tests/deterministic/test_host_adapters.py:166-182, 226-254, 285-312`
- Modify: `tests/orchestration/test_orchestrate_cli.py:143-150`

**Interfaces:**
- Consumes: `ExternalCLIAdapter.probe() -> dict[str, Any]`, `invoke_role(...) -> dict[str, Any]`
- Produces: Antigravity role-only capability, invocation command, and evidence contract

- [x] **Step 1: Write failing tests**

Add assertions that Antigravity probe remains `ROLE_ROUTING_ONLY`, fake `agy` arguments exclude `--model`, the requested model is `current-session-model`, model evidence is `UNAVAILABLE`, and the E2E trace does not claim observed routing.

- [x] **Step 2: Verify RED**

Run:

```bash
python3 -m unittest \
  tests.deterministic.test_host_adapters.HostAdapterTest.test_antigravity_external_role_invocation_records_requested_model_without_faking_resolution \
  tests.deterministic.test_host_adapters.HostAdapterTest.test_host_runner_emits_requested_only_when_model_is_unobserved \
  tests.deterministic.test_host_adapters.HostAdapterTest.test_antigravity_permission_bypass_is_opt_in \
  tests.orchestration.test_orchestrate_cli.OrchestrateCLITest.test_antigravity_one_command_runs_full_external_loop -v
```

Expected: assertions expose `EXTERNAL_MODEL_ROUTING`, `Gemini ...`, `CLI_REQUESTED_ONLY`, or `--model`.

- [x] **Step 3: Implement the minimum change**

Keep Antigravity probe mode unchanged, choose `roles` for its invocation and orchestrator display, omit `--model`, initialize model evidence as `UNAVAILABLE`, and write `ROLE_ROUTING_ONLY` to its trace summary.

Also remove the unsupported external role table and keep adapter build metadata, installer results, and doctor output aligned on `ROLE_ROUTING_ONLY` with `crossModelRouting: false`.

- [x] **Step 4: Verify GREEN and full regression safety**

Run:

```bash
python3 -m unittest tests.deterministic.test_host_adapters tests.orchestration.test_orchestrate_cli -v
python3 -m unittest discover -s tests -v
python3 scripts/validate_package.py
```

Expected: all tests and package validation pass.

- [x] **Step 5: Reinstall and verify**

Run:

```bash
codegraph sync .
python3 scripts/install.py --host all --scope user
cmp proofloop_core/host_runner.py "$HOME/.proofloop/runtime/proofloop_core/host_runner.py"
```

Expected: all host adapters install successfully and the shared runtime matches source.

- [ ] **Step 6: Commit and push `main`**

```bash
git add docs/superpowers/specs/2026-07-14-antigravity-role-only-routing-design.md \
  docs/superpowers/plans/2026-07-14-antigravity-role-only-routing.md \
  proofloop_core/adapters.py proofloop_core/host_runner.py proofloop_core/hosts.py proofloop_core/orchestrator.py \
  scripts/build_host_adapter.py scripts/install.py scripts/doctor.py \
  tests/deterministic/test_host_adapters.py tests/orchestration/test_orchestrate_cli.py
git commit -m "fix: support Antigravity role-only execution"
git push origin main
```
