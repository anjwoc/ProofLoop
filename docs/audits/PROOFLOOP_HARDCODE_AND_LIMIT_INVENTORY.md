# ProofLoop Hardcode and Execution-Limit Inventory

Target: `codex/preserve-eb097dd-with-main`  
Scope: limits and hardcoded behavior found in the inspected pipeline, host runtime, skills, package validation, live harness, and CLI.  
Classification:

- `SAFETY_BOUNDARY`: protects resources/processes and should remain, but must be visible
- `OPERATIONAL_DEFAULT`: reasonable default that must be overrideable and recorded
- `TASK_CONTRACT`: frozen per task/run and enforced as acceptance policy
- `TEST_ONLY`: fixture/test harness behavior; cannot prove production
- `UNJUSTIFIED_HARDCODE`: historical or hidden constant without a current evidence basis
- `CONTRADICTORY`: multiple defaults/policies govern the same behavior

## Summary

The repository does not have one budget authority. Effective limits come from:

1. CLI defaults
2. orchestrator constructor defaults
3. task brief defaults/model output
4. repair function defaults
5. skill metadata
6. environment variables
7. host-specific CLI flags
8. verifier-internal timeouts
9. live harness defaults
10. package/release scripts

Several values are defensible safety boundaries. The defect is that they are not all frozen into one run artifact and some contradict the published policy.

## Run and role execution

| Phase | Source / symbol | Value | Override | Classification | Finding |
| --- | --- | ---: | --- | --- | --- |
| Parent run | `ProofLoopOrchestrator.__init__` | `timeout_seconds=1200` | CLI `--timeout-seconds` | `OPERATIONAL_DEFAULT` | Repeated in multiple CLI commands and `RoleInvocation` |
| Parent run | CLI `orchestrate/run/goal` | `1200s` | explicit flag | `OPERATIONAL_DEFAULT` | Should be written once to `execution-budget.json` |
| Role | `_role_time_budget_seconds` | parent timeout | `PROOFLOOP_ROLE_TIMEOUT_SECONDS` | `OPERATIONAL_DEFAULT` | Invalid/nonpositive values silently fall back |
| Role | `_invoke` | `min(run, role)` | environment/run flag | `SAFETY_BOUNDARY` | Effective value is emitted, which is good |
| Role runner | `invoke_role` | `1200s` default | invocation arg | `OPERATIONAL_DEFAULT` | Duplicates orchestrator/CLI defaults |
| AGY role | host CLI `--print-timeout` | role timeout | derived | `SAFETY_BOUNDARY` | Provider-side timeout and parent timeout may report different reasons |
| AGY initial output | `_agy_initial_output_timeout_seconds` | none by default; minimum `15s` when set | `PROOFLOOP_AGY_INITIAL_OUTPUT_TIMEOUT_SECONDS` | `SAFETY_BOUNDARY` | Minimum clamp is hidden unless artifact inspected |
| Heartbeat | `invoke_role` | `5s` | function arg | `OPERATIONAL_DEFAULT` | Display/progress only |
| Process heartbeat | `ProcessRunner.run` | `5s` | arg | `OPERATIONAL_DEFAULT` | Duplicate default |
| Process polling | `ProcessRunner.__init__` | `0.05s` | constructor | `SAFETY_BOUNDARY` | Internal runtime detail |
| Termination grace | `ProcessRunner.__init__` | `2s` | constructor | `SAFETY_BOUNDARY` | Preserve |
| Drain grace | `ProcessRunner.__init__` | `2s` | constructor | `SAFETY_BOUNDARY` | Preserve |
| Stream queue | `ProcessRunner.__init__` | `1024` lines | constructor | `SAFETY_BOUNDARY` | Queue backpressure behavior should be documented |
| Output chunk | `_read_stream` | `65536` bytes | none | `SAFETY_BOUNDARY` | Internal framing boundary |

## Attempts, cycles, replans, and review

| Policy | Source | Value | Classification | Finding |
| --- | --- | ---: | --- | --- |
| Fast attempts | `TaskBrief` default | `1` | `TASK_CONTRACT` | Matches pipeline guide |
| Recovery attempts | `TaskBrief` default | `0` | `TASK_CONTRACT` | Matches pipeline guide |
| Repair helper fast default | `decide_next()` | `2` | `CONTRADICTORY` | Different from TaskBrief, dangerous when called without task values |
| Repair helper recovery default | `decide_next()` | `1` | `CONTRADICTORY` | Different from TaskBrief |
| Same fingerprint block | `decide_next()` | `3` repeats | `UNJUSTIFIED_HARDCODE` | No frozen policy field or evidence basis |
| Goal cycles | orchestrator/CLI | `8` | `OPERATIONAL_DEFAULT` | Must be in budget artifact |
| Replans | orchestrator/CLI | `2` | `OPERATIONAL_DEFAULT` | TaskExecutor contains additional tier behavior |
| Replan special branch | TaskExecutor | if configured `1`, expand to T3=`3`, else=`2` | `CONTRADICTORY` | A requested lower bound can become higher |
| Final review cycles | `_final_verification_and_review` | exactly `2` | `UNJUSTIFIED_HARDCODE` | Not represented in task recovery budget |
| Final review repair | same function | one recovery call after first rejection | `CONTRADICTORY` | Can spend recovery despite task `maxRecoveryAttempts=0` |
| Planner task count | `materialize_plan` | `1..4` | `OPERATIONAL_DEFAULT` | Reasonable bounded scope; should be explicit in strategy artifact |
| Domain task types considered | `resolve_skills` | first `3` | `OPERATIONAL_DEFAULT` | Truncation may hide a relevant domain pack |
| Domain selection policy artifact | `primary=1`, `maxAdjunct=2` | `1/2` | `OPERATIONAL_DEFAULT` | Current code does not visibly enforce exactly this policy in the same block |

## Token budgets and skill budgets

| Tier / skill | Value | Source | Classification | Finding |
| --- | ---: | --- | --- | --- |
| T0 | `20,000` | `engine/skills.py` | `OPERATIONAL_DEFAULT` | Hardcoded in code, not configuration |
| T1 | `60,000` | same | `OPERATIONAL_DEFAULT` | Same |
| T2 | `180,000` | same | `OPERATIONAL_DEFAULT` | Same |
| T3 | `360,000` | same | `OPERATIONAL_DEFAULT` | Same |
| Cache-read accounting | `10%` weighting | orchestrator budget event/accounting | `OPERATIONAL_DEFAULT` | Must be documented as cost policy, not provider usage fact |
| Protocol max tokens | varies (`1k` to `30k`) | each `proofloop.skill.json` | `TASK_CONTRACT` metadata | Selected/reserved even when a skill is not injected |
| Protocol max seconds | `30/600/900...` | skill contracts | `CONTRADICTORY` | Pipeline guide says skill metadata does not terminate execution |
| Protocol max invocations | `1..8` | skill contracts | `CONTRADICTORY` | Registry loads values but orchestrator does not enforce them as the sole invocation budget |
| Domain reference injection | per-pack `maxInjectedTokens` | contract | `TASK_CONTRACT` | Reasonable if measured and reported |

## Verification and browser limits

| Check | Value | Source | Classification | Finding |
| --- | ---: | --- | --- | --- |
| Generic check timeout | none unless `CheckSpec.timeoutSeconds` | task contract | `TASK_CONTRACT` | Good direction; planner can omit it |
| Browser load | `15s` | static-web verifier, documented | `SAFETY_BOUNDARY` | Must remain check-specific |
| JavaScript syntax | `30s` | static-web verifier, documented | `SAFETY_BOUNDARY` | Must remain check-specific |
| Animation observation | virtual time `0.1s` and `1.5s` | static-web verifier, documented | `TEST_ONLY` observation points | Proves screen change only, not semantic correctness |
| Failed/output tail | `20` lines | `checks.run_checks` deque | `SAFETY_BOUNDARY` | Raw logs are preserved; acceptable |
| Check output event | full line | events/debug | `SAFETY_BOUNDARY` concern | Host output has 4k cap but check output event path may be noisier |
| Host output event | `4,000` chars | `host_runner` | `SAFETY_BOUNDARY` | Raw artifact remains, good |
| Required checks empty | vacuous `all([])` before audit | `checks.py` | `UNJUSTIFIED_HARDCODE/LOGIC` | Truth now blocks `CHECK_EVIDENCE_EMPTY`; report layer still needs correction |
| Empty proof stage | `SKIPPED`, `expectationMet=true` | `run_proof_stage` | `OPERATIONAL_DEFAULT` | Correct only for optional stage; must not satisfy required acceptance |

## Live harness and UI defaults

| Area | Value | Source | Classification | Finding |
| --- | ---: | --- | --- | --- |
| Live host timeout | `1800s` | `run_host_live.py` | `OPERATIONAL_DEFAULT` | Separate from ProofLoop run timeout `1200s` |
| Background relay poll | `2s` | live runner | `OPERATIONAL_DEFAULT` | Harness only |
| User relay wait | `3s` | entry skill / CLI | `OPERATIONAL_DEFAULT` | Repeated in docs and CLI |
| Live AGY default model | `gemini-3.5-flash-medium` | live runner | `OPERATIONAL_DEFAULT` | Must be recorded as requested, not observed |
| Live Claude default model | `opus` | live runner | `OPERATIONAL_DEFAULT` | Same |
| Live scenario names | `normal`, `recovery` | live runner | `UNJUSTIFIED_HARDCODE` | Too generic; current `normal` does not match advertised static-web scenario |
| Usage viewer port | `8400` | CLI | `OPERATIONAL_DEFAULT` | Harmless, overrideable |
| Benchmark repetitions | `5` | CLI | `OPERATIONAL_DEFAULT` | Cost-bearing; should require explicit confirmation for live models |
| Benchmark seed | `0` | CLI | `TEST_ONLY` | Good for reproducibility |
| Qualification behavior repetitions | `0` | CLI | `OPERATIONAL_DEFAULT` | Means no behavior run unless requested; visible status must not imply qualification |

## Packaging, installation, and retention

| Constraint | Value | Source | Classification | Finding |
| --- | ---: | --- | --- | --- |
| Runtime file budget | `185` files | `scripts/validate_package.py` | `UNJUSTIFIED_HARDCODE` | Historical source-count proxy; unrelated to behavior |
| Expected agent models | planner/reviewer `opus`, implementer `haiku`, recovery `sonnet` | package validator | `UNJUSTIFIED_HARDCODE` | Can drift from runtime route registry |
| Required text fragments | fixed strings | package validator | `OPERATIONAL_DEFAULT` | Syntax presence, not semantic validation |
| Install/remove attempts | `5` | install/build scripts | `SAFETY_BOUNDARY` | Fine; duplicated |
| Remove retry delay | `0.05 * attempt` | install/build scripts | `SAFETY_BOUNDARY` | Fine |
| Codex hooks | `10s` | generated hooks JSON | `SAFETY_BOUNDARY` | Hook timeout can truncate truth/trace checks; raw outcome should expose it |
| TokScale version | `4.5.3` | install script | `OPERATIONAL_DEFAULT` | Intentional pin; needs update policy |
| Record retention | last `30` runs/relay/requests | `run_state._prune_old_records` | `OPERATIONAL_DEFAULT` | Can delete evidence needed for audits; should be configurable and never prune referenced release evidence |
| Run ID entropy | timestamp + first `8` UUID hex | run state | `OPERATIONAL_DEFAULT` | Reasonable local ID |

## Host/model parsing hardcodes

| Item | Source | Classification | Finding |
| --- | --- | --- | --- |
| AGY model-label map | host runner and live runner | `OPERATIONAL_DEFAULT` | Duplicated mapping can drift |
| Model-detection regex | `runtimes/hosts.py` | `UNJUSTIFIED_HARDCODE` | New/renamed model output may become unobserved |
| Supported host set | many CLI/parser locations | `OPERATIONAL_DEFAULT` | Repeated; should derive from runtime registry |
| Claude capability comparison | adapter compares `self.host == "claude"` | `LOGIC_DEFECT` | Supported ID is `claude-code`, so capability flags can be false |
| Codex manifest Sol/Terra wording | build script | `UNJUSTIFIED_HARDCODE` | Marketing text can contradict actual routing |

## Documentation-only limits that are not enforced consistently

| Documented statement | Actual implementation issue |
| --- | --- |
| default model calls `1`, recovery `0` | final review repair can add recovery outside task budget |
| role-specific 300s cap removed | skill metadata still carries 30/600/900 second values |
| skill maxSeconds only recorded | UI/events may suggest selected budgets are operational, but enforcement is split |
| one model call for static web | missing documented tests prevent proof of this promise |
| live normal proves expected static web | normal fixture is concurrency work |

## Required consolidation

Create one immutable `execution-budget.json` before the first mutating role:

```json
{
  "schemaVersion": "1.0",
  "runDeadlineSeconds": 1200,
  "roleDeadlineSeconds": 1200,
  "initialOutputDeadlineSeconds": null,
  "goalCycles": 8,
  "replans": 2,
  "reviewCycles": 1,
  "fastAttempts": 1,
  "recoveryAttempts": 0,
  "tokenBudget": 180000,
  "limitsSource": {
    "runDeadlineSeconds": "CLI_DEFAULT",
    "fastAttempts": "TASK_CONTRACT"
  }
}
```

Every role, repair, review repair, and final Truth report should read this artifact. No helper function should retain a conflicting default.

## Removal/retention recommendation

### Remove or replace

- historical runtime file-count gate
- `decide_next()` defaults that differ from TaskBrief
- tier-expanded replan branch that overrides an explicit lower value
- generic `normal/recovery` scenario identity
- duplicated AGY model labels
- stale model names in manifest prose

### Keep but expose

- process termination/drain grace
- queue/chunk/output-tail bounds
- browser/check-specific deadlines
- event display truncation with raw logs preserved
- token budgets after they move to one artifact
- retained-run pruning after it becomes configurable and release artifacts are exempt

## Verification status

This inventory is based on static source evidence. It is not a runtime assertion that every branch above was exercised. Values requiring live confirmation are explicitly labelled operational or hypothetical rather than passed behavior.
