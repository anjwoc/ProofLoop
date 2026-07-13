# Task brief contract

ProofLoop machine-readable task briefs use JSON so the deterministic sidecar has no YAML dependency.

```json
{
  "id": "TASK-001",
  "objective": "Describe one independently verifiable behavior change.",
  "allowedPaths": ["src/**", "tests/**"],
  "protectedPaths": ["package-lock.json", "migrations/**"],
  "simplicity": {
    "selectedRung": "DIRECT_CHANGE",
    "rationale": "The existing service boundary can satisfy the behavior without a new abstraction or dependency.",
    "considered": [
      "reuse existing validation helper",
      "standard library parsing"
    ]
  },
  "changeBudget": {
    "maxChangedFiles": 4,
    "maxAddedLines": 120,
    "maxNewFiles": 1,
    "allowDependencyChanges": false
  },
  "requiredChecks": [
    {
      "name": "target-tests",
      "command": ["python3", "-m", "unittest", "tests.test_feature"],
      "timeoutSeconds": 300
    }
  ],
  "budgets": {
    "maxFastAttempts": 2,
    "maxRecoveryAttempts": 1
  }
}
```

Allowed simplicity rungs:

```text
SKIP_NOT_NEEDED
REUSE_EXISTING
STDLIB
PLATFORM_NATIVE
INSTALLED_DEPENDENCY
DIRECT_CHANGE
MINIMAL_NEW_CODE
```

The human-readable plan beside the JSON task must also state invariants, non-goals, forbidden contract changes, and escalation conditions. Change budgets may be increased only by returning to the planner with evidence; the implementer cannot silently expand them.
