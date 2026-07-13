# ProofLoop recovery live fixture

Fix `VersionedSingleFlight` without changing its public API.

Requirements:

- concurrent callers for the same key and generation execute the operation once;
- failures are neither cached nor left as poisoned in-flight entries;
- invalidation creates a new generation immediately;
- a stale in-flight result must never replace or satisfy the new generation;
- different keys must progress independently;
- do not weaken or delete tests and do not add dependencies.

This fixture counts as recovery evidence only when the authenticated run records a real `implementer_recovery` invocation after objective failed checks. First-attempt success is a valid normal run but not recovery proof.
