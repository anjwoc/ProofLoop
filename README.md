# ProofLoop Skill-First Core

ProofLoop is an installable software-engineering skill harness. One visible skill invocation launches an orchestrator that owns task classification, role allocation, real verification, bounded repair, independent review, hallucination checks, anti-bloat enforcement, and truth-gated completion.

**v0.4.0-alpha is a development build.** The automatic kernel and deterministic evidence layer are implemented. Authenticated Codex and Antigravity model-routing/recovery runs still need to be proven in the user's environment, so the overall release gate remains `FAIL`.

## Use

```text
Codex:       $proofloop <request>   or select proofloop from /skills
Antigravity: /proofloop <request>
Claude Code: /proofloop <request>
```

The user never runs `invoke-role`, `record-attempt`, or `verify-run` manually.

## Flow

```text
visible proofloop skill
→ proofloop-core goal
→ preflight and Git snapshot
→ strategy selection
→ isolated role processes
→ real checks and diff guard
→ fingerprint-based retry/recovery
→ independent review
→ claim, truth, and anti-bloat gates
→ PROVEN | UNPROVEN | FAILED | BLOCKED
```

Mutation strategies implemented in this alpha:

- `DIRECT_VERIFIED_CHANGE`
- `PLANNED_IMPLEMENTATION`
- `HIGH_RISK_ENGINEERING`

Repository-analysis orchestration is intentionally blocked with `ANALYSIS_ORCHESTRATION_NOT_IMPLEMENTED` rather than simulated.

## Live execution visibility

Installed host skills use the human stream automatically. The screen shows phases, roles, requested and observed models, attempts, real check results, recovery reasons, review findings, and the final truth state. The same event objects are appended to `.proofloop/runs/<run-id>/events.jsonl`.

```bash
proofloop-core goal --host codex --repo . --request-file request.txt \
  --output-format human --verbosity info --color auto
```

Machine consumers can request pure JSON Lines. The backward-compatible default `quiet` mode prints only the final JSON result.

```bash
proofloop-core goal --host codex --repo . --request-file request.txt --output-format jsonl
proofloop-core goal --host codex --repo . --request-file request.txt --output-format quiet
```

Replay or follow a run from another terminal:

```bash
proofloop-core watch --run latest --repo . --format human
proofloop-core watch --run-dir .proofloop/runs/<run-id> --format jsonl --task TASK-001 --level warning
```

An unobserved model is displayed as requested-only and keeps model routing `UNPROVEN`. Complete stdout and stderr remain in the run's invocation and check artifacts.

## Install

```bash
./install.sh
python3 scripts/doctor.py
```

`./install.sh` selects `python3` automatically and clean-installs all hosts at user scope. Pass the
same options as the Python installer to narrow the target, for example
`./install.sh --host codex --scope user`. `make install` and
`python3 ./scripts/install.py` are equivalent. An npm package is not required.

Installation is a clean, idempotent reinstall. It validates generated adapters, removes only
ProofLoop-managed runtime, plugin, agent, skill, workflow, and marketplace entries, then installs
the fresh build. Unrelated host plugins, agents, skills, and settings are preserved.

Antigravity permission bypass is disabled by default. It can be explicitly enabled for isolated unattended testing:

```bash
export PROOFLOOP_ANTIGRAVITY_BYPASS_PERMISSIONS=1
```

## Authenticated acceptance

```bash
python3 scripts/run_host_live.py --host codex --scenario normal --keep-workspace
python3 scripts/run_host_live.py --host codex --scenario recovery --keep-workspace
python3 scripts/run_host_live.py --host antigravity --scenario normal --keep-workspace
python3 scripts/run_host_live.py --host antigravity --scenario recovery --keep-workspace
```

A recovery run passes only when a real `implementer_recovery` invocation is observed after objective failed checks. First-attempt success does not prove recovery.

```bash
python3 scripts/release_check.py
```

Static tests and simulated host processes cannot override missing authenticated live evidence.
