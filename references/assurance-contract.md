# Epistemic and simplicity assurance contract

ProofLoop treats model language as an untrusted claim until an artifact supports it.

## Epistemic states

- `FACT`: machine-checkable evidence is required.
- `INFERENCE`: evidence and explicit reasoning are required.
- `UNKNOWN`: uncertainty is preserved and may not be restated as fact.

Facts use run-relative artifact assertions:

```json
{
  "artifact": "checks/checks.json",
  "jsonPointer": "/verdict",
  "equals": "PASS"
}
```

Optional `sha256` pins exact artifact bytes. Artifact paths cannot escape the run directory.

A missing artifact or pointer is unsupported. A mismatched expected value or hash is contradicted. Contradicted material facts fail the run.

## Required claim categories

- `CHECK_RESULT`
- `CHANGE_SCOPE`
- `REVIEW_RESULT`
- `SIMPLICITY`
- `MODEL_ROUTING` when cross-model routing is claimed

## Simplicity assurance

Planning selects the earliest sufficient solution rung and sets a strict change budget. The deterministic diff guard measures tracked and untracked changes. It checks:

- changed files;
- added lines;
- new files;
- dependency manifests and lock files;
- scope and protected paths;
- test deletion, disabling, assertion removal, and suspicious timeout increases.

The reviewer independently returns `MINIMAL`, `OVERBUILT`, or `CANNOT_VERIFY` and a delete list. Safety and correctness controls cannot be traded away for fewer lines.
