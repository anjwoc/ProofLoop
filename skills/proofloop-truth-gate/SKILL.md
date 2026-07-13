---
name: proofloop-truth-gate
description: Mandatory hallucination, truth, simplicity, and completion gate for ProofLoop coding work. Combines actual command results, diff-integrity and change-budget evidence, independent review, machine-checkable claims, and observed model traces. Returns only PROVEN, UNPROVEN, FAILED, or BLOCKED.
---

# ProofLoop Truth Gate

Do not say "completed" before this gate.

## Required evidence

- command evidence produced by `run_checks.py`;
- diff, test-integrity, and change-budget evidence produced by `diff_guard.py`;
- independent review with both implementation and simplicity verdicts;
- observed model trace when cross-model routing is claimed;
- `<run-dir>/claims.json` containing the factual claims intended for the final response.

## Claim ledger

Every claim must be labeled `FACT`, `INFERENCE`, or `UNKNOWN`.

```json
{
  "schemaVersion": "1.0",
  "claims": [
    {
      "id": "checks-pass",
      "category": "CHECK_RESULT",
      "kind": "FACT",
      "statement": "All required checks passed.",
      "evidence": [
        {
          "artifact": "checks/checks.json",
          "jsonPointer": "/verdict",
          "equals": "PASS"
        }
      ]
    }
  ]
}
```

Required supported categories:

- `CHECK_RESULT`
- `CHANGE_SCOPE`
- `REVIEW_RESULT`
- `SIMPLICITY`
- `MODEL_ROUTING` when routing is claimed

Rules:

- a fact without evidence is `UNPROVEN`;
- a fact whose assertion disagrees with the artifact is `FAILED`;
- an inference needs evidence plus explicit reasoning;
- unknowns must remain visibly unknown;
- evidence paths must stay inside the run directory.

## Simplicity review

`review.json` must contain:

```json
{
  "verdict": "APPROVED",
  "simplicityVerdict": "MINIMAL",
  "deletionCandidates": []
}
```

Allowed simplicity verdicts:

- `MINIMAL`
- `OVERBUILT`
- `CANNOT_VERIFY`

`OVERBUILT` fails the run. `CANNOT_VERIFY` keeps it unproven.

## Final verification

Normalize model trace:

```bash
$HOME/.proofloop/bin/proofloop-core summarize-trace \
  --trace <model-trace.jsonl> \
  --output <run-dir>/model-trace-summary.json
```

Generate assurance and truth reports:

```bash
$HOME/.proofloop/bin/proofloop-core verify-run \
  --run-dir <run-dir> \
  --output <run-dir>/truth-report.json
```

This also writes `<run-dir>/assurance-report.json`.

## Allowed verdicts

- `PROVEN`: all required evidence and claims are supported; implementation is minimal.
- `UNPROVEN`: checks may pass, but a material claim, review, simplicity judgment, or routing claim lacks evidence.
- `FAILED`: deterministic checks, integrity, budget, claim contradiction, overbuild review, or implementation review failed.
- `BLOCKED`: bounded repair or required capability is exhausted.

Never translate `UNPROVEN`, `FAILED`, or `BLOCKED` into success.
