---
name: proofloop-repair
description: Repair a failed ProofLoop implementation using exact check logs and bounded escalation. Retry once with a fresh fast implementer, switch to the recovery model after a repeated fingerprint or exhausted fast budget, and return design conflicts to the planner.
---

# ProofLoop Repair

A repair requires new evidence. Never ask the same model to "try again" without logs, diff, and a narrower hypothesis.

## Record each attempt

Record:

- role and observed model when available;
- changed files;
- check verdict;
- diff-guard verdict;
- failure fingerprint;
- classification;
- links to stdout and stderr.

Generate the next action from actual check and diff evidence:

```bash
$HOME/.proofloop/bin/proofloop-core record-attempt \
  --task <task.json> \
  --run-dir <run-dir> \
  --role implementer_fast
```

For recovery use `--role implementer_recovery`. The script writes `attempts.jsonl` and `next-action.json`.

## Policy

- First fast failure: dispatch a fresh fast implementer.
- Same fingerprint twice, or fast budget exhausted: dispatch the recovery implementer.
- Design, specification, or contract conflict: return to the deep planner.
- Recovery budget exhausted: stop as `BLOCKED`.
- Never broaden scope, weaken tests, or silently revise the task brief.

## External bridge

When role models are invoked through shell commands or official CLIs, the sidecar may own the full bounded loop:

```bash
$HOME/.proofloop/bin/proofloop-core external-loop \
  --task <task.json> \
  --repo . \
  --run-dir <run-dir> \
  --fast-command-json '["..."]' \
  --recovery-command-json '["..."]'
```

This proves external orchestration mechanics only. Native host routing still requires an observed host trace.
