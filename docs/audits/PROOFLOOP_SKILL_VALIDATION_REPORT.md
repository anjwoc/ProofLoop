# ProofLoop Skill Validation Report

Target: `skills/proofloop/SKILL.md`, built-in process protocols, registry, prompt injection, and host packaging on `codex/preserve-eb097dd-with-main`.

Reference philosophies used:

- `FrancyJGLisboa/agent-skill-creator`: evidence-derived intent, complete deliverables, spec validation, security scan, pipeline validation, evals, and held-out checks
- `DietrichGebert/ponytail`: understand the real flow, stop at the first sufficient solution rung, preserve safety, leave one runnable check for non-trivial logic
- `code-yeongyu/lazycodex`: decision-complete plan, durable checklist execution, evidence-verified completion, and post-implementation review

This is a source audit. External validation scripts and authenticated hosts were not executed in this session.

## Overall result

| Dimension | Result | Notes |
| --- | --- | --- |
| Activation description | `PASS_WITH_GAPS` | Clear ProofLoop trigger; broad automatic activation can be expensive |
| Entry workflow | `PASS_WITH_GAPS` | Thin coordinator and relay ownership are sound; installed runtime revision is not bound |
| Evidence honesty | `IMPROVED` | Absolute constraints added to entry skill and every role prompt |
| Cross-platform packaging | `PARTIAL` | Claude/Codex/AGY builders exist; host parity and activation collision need live proof |
| Process protocol wiring | `FAIL` | `proofloop-verify` can be selected without prompt injection or explicit Core ownership |
| Skill contract validation | `FAIL` | Internal contracts silently default malformed fields |
| Skill evaluation | `FAIL` | Process protocols are EXPERIMENTAL/E0 and lack enforced behavior/held-out eval gates |
| Security/trust boundaries | `PARTIAL` | Grounding injection scan/private reasoning redaction exist; internal skill files are over-trusted |
| Ponytail minimality | `PASS_WITH_GAPS` | Strong prose and ladder; hardcoded file-count gate and duplicated budgets contradict it |
| Reproducible completion | `FAIL` | Documented tests missing, live scenario mismatch, current runtime may differ from source |

**Validation verdict: NOT PRODUCTION-QUALIFIED.**

## 1. Entry skill audit

### Strengths

- Coordinator is explicitly thin; Core owns workflow and Truth.
- User request is preserved verbatim before execution.
- Background parent run and incremental relay avoid one opaque blocking call.
- Progress is constrained to observed `[ProofLoop]` lines.
- `run-outcome.json`, `input-request.json`, `truth-report.json`, and `run-error.json` have distinct semantics.
- Coordinator is forbidden from implementing concurrently or synthesizing status.

### Applied improvement

The first section now forbids:

- fabricated host/model/result/time/artifact/completion
- fake/simulated/fixture evidence being treated as authenticated behavior
- exit zero/schema JSON being treated as behavior proof
- weakened/deleted/skipped/replaced tests
- manual Core evidence
- absence being converted to success

It also injects the Ponytail ladder while preserving security, validation, authorization, data-loss prevention, error handling, accessibility, and explicit requirements.

### Remaining gaps

1. The skill launches `$HOME/.proofloop/bin/proofloop-core` but does not verify its revision against the current source/plugin.
2. The phrase “determine current host” is procedural; the installed specialized skill should contain one fixed host identity and hash.
3. The entry skill assumes relay and report commands exist in the installed runtime but has no preflight/doctor check.
4. Broad description activation for every non-trivial change may trigger ProofLoop when a user wanted ordinary direct editing. Activation needs negative examples/evals.
5. The skill has no declared version, review date, dependency/host schema, or eval metadata in frontmatter.

## 2. Agent-skill-creator gate comparison

### Discovery and intent

| Gate | ProofLoop status |
| --- | --- |
| Treat input artifacts as evidence | `PARTIAL` — grounding and repository context exist |
| Read all relevant material before design | `PARTIAL` — explorer is conditional; direct paths may rely on narrow template logic |
| Extract implicit failure modes | `PARTIAL` — intent unknowns exist but acceptance derivation remains shallow |
| Challenge surface request | `PARTIAL` — intent gate can request owner input |
| Produce explicit implementation contract | `PASS` — TaskBrief and proof graph exist |

### Implementation completeness

| Gate | ProofLoop status |
| --- | --- |
| No placeholders/TODO contracts | `FAIL` — several PromptIR IDs/metadata fields use literal `todo` |
| Functional files, not prose only | `PASS_WITH_GAPS` — Core exists; some selected skill prose is not wired |
| Cross-platform install | `PARTIAL` — builders/installers exist but live parity is unproven |
| Self-contained package | `PARTIAL` — runtime sidecar and global installation state are external mutable dependencies |

### Validation and security

| Gate | ProofLoop status |
| --- | --- |
| Spec validation | `PARTIAL` — package fragments and domain contracts checked; process contract schema not strict |
| Security scan | `PARTIAL` — grounding injection scan and redaction exist; no equivalent full package security scan gate found |
| Pipeline check | `FAIL` — documented acceptance commands reference missing files |
| Eval validation | `FAIL` — process protocols lack enforced eval qualification |
| Held-out/canary | `FAIL` — no held-out anti-deception canary for process protocols |
| Undeclared endpoints/secrets | `PARTIAL` — diff/redaction protections exist; package-wide undeclared network scan not shown |

## 3. Ponytail audit

### Correct adoption

- Process protocols explicitly demand the smallest sufficient change.
- Implementer prohibits adjacent refactors and speculative infrastructure.
- Reviewer asks for concrete deletion candidates.
- Skill registry contains a simple greedy allocation with an explicit Ponytail rationale.
- This audit's prompt contract now applies the ladder after real-flow comprehension.

### Incorrect or incomplete adoption

1. `validate_package.py` uses a historical runtime file-count cap as a correctness proxy. This is numerical minimalism, not Ponytail.
2. Large test deletion during orchestrator simplification has no evidence map proving equivalent safety.
3. Multiple retry/time/token defaults create more policy code instead of one frozen budget.
4. Fast-lane `MINIMAL` is asserted automatically rather than proven by a bounded simplicity policy.
5. `_load_contract()` removed defensive validation because files are “internal”; Ponytail explicitly forbids simplifying away trust-boundary validation.

### Required Ponytail rule for ProofLoop

> Minimize implementation, never evidence. Delete redundant orchestration only after the surviving path has one falsifiable check for every removed guarantee.

## 4. LazyCodex workflow audit

### Planning

ProofLoop has intent, strategy, task briefs, and proof graph. The missing property is a **decision-complete durable plan** for repository hardening itself. `plans/proofloop-truth-hardening-audit.md` was added to supply:

- completion promise
- evidence classes
- workstream checkboxes
- stop conditions
- explicit blocked/unexecuted states

### Durable execution

ProofLoop writes rich run artifacts, which is stronger than a chat-only checklist. However:

- source and installed runtime are not revision-bound
- selected skill execution mode is not explicit
- release evidence is stored with machine-specific absolute paths
- CI does not advance/verify the plan

### Verified completion

LazyCodex's useful idea is not a large iteration count. It is that completion requires an independent verification state. ProofLoop should adopt that principle but not copy 100/500-loop defaults. ProofLoop's bounded `1/0` implementation budget is preferable when failures are classified honestly.

## 5. Process protocol inventory

| Protocol | Declared status | Evidence level | Actual use |
| --- | --- | --- | --- |
| `proofloop-intent` | EXPERIMENTAL | E0 | injected into explorer only; Core intent compiler is separate |
| `proofloop-design` | EXPERIMENTAL | E0 | injected into explorer/planner for T2/T3 |
| `proofloop-plan` | EXPERIMENTAL | E0 | injected into planner |
| `proofloop-implement` | EXPERIMENTAL | E0 | injected into implementer/recovery |
| `proofloop-debug` | EXPERIMENTAL | E0 | injected into recovery |
| `proofloop-review` | EXPERIMENTAL | E0 | injected into reviewer |
| `proofloop-verify` | EXPERIMENTAL | E0 | selected/reserved, but not mapped into a role prompt |

### Critical semantic issue

`skill.selected` and `skill.reference_loaded` currently describe selection, not guaranteed consumption. Events need an explicit field:

```json
{
  "executionMode": "PROMPT_INJECTED | CORE_IMPLEMENTED | SELECTED_NOT_CONSUMED",
  "consumer": "planner_deep | reviewer_deep | proofloop-core",
  "promptProjection": "...",
  "contentHash": "..."
}
```

A release gate must reject `SELECTED_NOT_CONSUMED` for a skill claimed as active.

## 6. Contract-schema audit

### Current risk

`_load_contract()` supplies defaults for missing values and does not validate the JSON against a schema. Because agents edit these files, “internal” is not a sufficient trust assumption.

### Minimum schema requirements

Every process protocol must explicitly declare and validate:

- stable ID and semantic version
- status and evidence level
- compatible hosts/modes/tiers
- required context artifacts
- proof obligations closed/added
- minimum authority and self-closure rule
- max injected tokens
- completion artifact/schema
- escalation conditions
- eval spec and qualification hash
- source license/provenance

No critical field should silently default.

## 7. Required eval suite

Each process protocol needs:

### Trigger cases

At least five positive and five negative cases, including overlapping protocol boundaries.

### Behavior cases

At least three real scenarios with binary checks. For anti-deception, include:

1. fake host returns exit zero and expected JSON
2. check report says PASS with empty checks
3. requested model is present but observed model is absent
4. copied/stale evidence belongs to another run
5. reviewer approves while deterministic check fails
6. implementer modifies protected evaluator
7. documented command references a missing test
8. selected skill is never consumed

### Held-out canary

One test case must be excluded from prompt-visible examples and fail when the implementation merely pattern-matches known fixtures.

### Security scan

Scan skills and scripts for:

- hardcoded credentials/tokens
- hidden Unicode/encoded instruction payloads
- instructions to conceal, override, or exfiltrate
- undeclared network endpoints
- shell interpolation of model output
- manual PASS/truth interfaces
- writes to parent-owned evidence paths

## 8. Prompt integrity

### Applied fix

`proofloop_core/prompting/renderers.py` now prepends a mandatory contract before provider and role directives for every PromptIR role. A new deterministic test checks all roles across generic, Codex, Claude Code, and AGY renderers.

### Limitation

A prompt rule reduces model deception but does not replace Core enforcement. The following remain Core responsibilities:

- evidence origin/scope
- non-empty checks
- protected evaluator integrity
- host/runtime revision match
- retry budget
- skill consumption proof
- final Truth

## 9. Cross-platform audit

### Claude Code

- Plugin build and strict validation path exist.
- Role MCP inventory is intentionally isolated.
- Needs authenticated install/run evidence from current revision.

### Codex

- Plugin, skills, agents, and hooks are generated.
- Capability code compares `self.host == "claude"` elsewhere; host-ID consistency needs a shared enum.
- Hook timeout and trust approval must be captured in doctor/preflight output.

### AGY/Antigravity

- Skills and workflow are both installed.
- Model display-label mapping is duplicated.
- Skill/workflow name collision is a live-test hypothesis.
- Permission bypass is enabled for mutating children; this requires explicit user authorization and audit output.

## 10. Qualification plan

### Gate A — Static package

- strict process contract schema
- package security scan
- documented command/path validation
- prompt integrity tests
- no manual evidence writer

### Gate B — Deterministic behavior

- complete deterministic suite
- anti-deception adversarial suite
- worktree promotion/integrity tests
- empty/stale/copied evidence tests
- skill consumption tests

### Gate C — Current-runtime packaging

- isolated `PROOFLOOP_HOME`
- source/runtime hash equality
- host plugin/skill doctor
- no stale global configuration dependency

### Gate D — Authenticated host

One normal acceptance per supported host, with preserved transcript and exact scenario identity. Recovery is a separate approved cost experiment.

### Gate E — Release

CI green, package green, required authenticated reports present, no open P0 findings, and execution ledger contains no disguised `UNEXECUTED` item.

## 11. Current execution ledger

| Validation | Status |
| --- | --- |
| External skill source read | `PASSED` |
| ProofLoop source/contract read | `PASSED` |
| Entry skill anti-deception update | `PASSED` as source commit |
| Mandatory prompt contract update | `PASSED` as source commit |
| Regression test files created | `PASSED` as source commit |
| Regression tests executed | `UNEXECUTED` |
| agent-skill-creator `validate.py` | `UNEXECUTED` |
| agent-skill-creator `security_scan.py` | `UNEXECUTED` |
| pipeline/eval validator | `UNEXECUTED` |
| Codex authenticated acceptance | `UNEXECUTED` |
| AGY authenticated acceptance | `UNEXECUTED` |
| CI | `UNEXECUTED` |

## Final skill verdict

ProofLoop's written philosophy is substantially aligned with evidence-first engineering and Ponytail minimality. The current product fails qualification because prose status, skill selection, execution, and release evidence are not yet cryptographically or structurally tied together.

The next mergeable milestone is not another agent role. It is one small chain:

`validated skill contract → recorded consumer → current runtime hash → non-empty authoritative checks → bounded review claim → evidence-scoped Truth`.
