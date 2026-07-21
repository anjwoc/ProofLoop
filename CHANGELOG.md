# Changelog

## 0.4.0-alpha — Automatic orchestrator kernel

- Implemented G-01: Execution Brief schema & shadow synthesizer.
- Implemented G-02: Role View projector and prompt envelope.
- Implemented G-03: T2/T3 refinement proposal reconciler.
- Implemented G-06: Model/session/usage evidence normalization and coverage.
- Implemented G-07: Docker official evaluator (read-only, clean container).
- Implemented G-08: 6-arm benchmark runner (resume, paired key, timeout, partial failures).
- Implemented G-09: ReservationFlow repeatable benchmark support.
- Implemented G-10: Workload telemetry (T0-T3 tier tracking).
- Implemented G-11: Fingerprint-based recovery bounds (UNRECOVERABLE after repeated failures).
- Implemented G-12: Goal resume, cancel, and crash recovery.
- Implemented G-13: 90-paired trial runner for Domain Pack evaluation.
- Implemented G-14: Domain trigger sets implementation.
- Implemented G-15: Clean install isolation verification (`scripts/verify_clean_install.py`).
- Implemented G-16: CI artifact integrity report via release checks.
- Implemented G-17: CLI log realtime redaction for secrets (OpenAI, Anthropic, GCP, GitHub).
- Added the user-hidden `proofloop-core orchestrate` command.
- Added direct, planned, high-risk, and honestly blocked analysis strategies.
- Moved role order, verification, retry, recovery, review repair, and truth completion into the core runtime.
- Added a thin visible `proofloop` skill for Claude Code, Codex, and Antigravity.
- Added external CLI adapters with requested-versus-observed model evidence.
- Added one-command simulated-host E2E tests for Codex and Antigravity.
- Added normal and recovery authenticated acceptance runners.
- Removed Antigravity permission bypass from the default path; it is now explicit opt-in.
- Fixed untracked/cache files causing false anti-bloat failures.
- Kept the release gate failed until authenticated normal and recovery E2E evidence exists.

## 0.3.0-alpha — Codex and Antigravity adapters

- Added a Codex plugin with five ProofLoop skills, four custom agents, plugin hooks, installer support, and a real `codex exec --json` acceptance runner.
- Configured Codex planning/recovery/review on `gpt-5.6` and bounded fast implementation on `gpt-5.6-terra`.
- Added Codex `SubagentStop` evidence capture using agent type, transcript path, and host-exposed model fields.
- Added Stop truth-gate enforcement for active ProofLoop runs.
- Added an Antigravity Skill and Workflow adapter with mandatory YAML description frontmatter.
- Declared Antigravity interactive execution as `ROLE_ROUTING_ONLY` rather than pretending native cross-model routing.
- Added experimental external Antigravity role processes with Pro planning/recovery/review and Flash implementation requests.
- Distinguished requested-model evidence from observed/resolved-model evidence in trace summaries.
- Added host capability probes, `invoke-role`, Codex/Antigravity installers, host live runners, and host-specific release statuses.
- Kept generated adapters out of the source of truth and removed repository-only scripts from the Codex plugin payload.
- Release remains FAIL until authenticated live normal and recovery traces are proven.

## 0.2.0-alpha — Epistemic and anti-bloat assurance

- Added a deterministic claim ledger audit with `FACT`, `INFERENCE`, and `UNKNOWN` states.
- Added machine-checkable artifact assertions with JSON Pointer, expected values, and optional SHA-256 pins.
- Added contradiction handling: unsupported claims remain `UNPROVEN`; contradicted factual claims fail the run.
- Added required claim categories for checks, scope, review, simplicity, and claimed model routing.
- Added a minimum-solution planning ladder inspired by the principle that the best safe code is often code not written.
- Added per-task budgets for changed files, added lines, new files, and dependency changes.
- Fixed diff inspection to include untracked new files rather than only Git-tracked diffs.
- Added independent reviewer simplicity verdicts: `MINIMAL`, `OVERBUILT`, and `CANNOT_VERIFY`.
- Added assurance reports to the final Truth Gate.
- Preserved the runtime source budget below 50 files; no new workflow engine was introduced.

## 0.1.0-dev — Skill-first reboot milestone

- Replaced the generic workflow platform with five composable coding skills.
- Added explicit Opus, Haiku, Sonnet, and Fable role agents for the Claude reference host.
- Added exit-code-owned command verification; removed manual PASS input.
- Added scope and test-integrity diff guards.
- Added deterministic failure fingerprints and bounded fast-to-recovery decisions.
- Added a runtime-owned external repair loop and labeled it `SIMULATED_ORCHESTRATION` in tests.
- Added CodeGraph context preparation without reintroducing a generic state machine.
- Added Claude `Agent` trace capture using the host's resolved model field.
- Added a Stop hook requiring a truth report for active runs.
- Added a live Claude acceptance runner that fails if the skill does not create real run artifacts.
- Added a release gate that stays FAIL until normal and recovery live E2E reports are both PROVEN.
