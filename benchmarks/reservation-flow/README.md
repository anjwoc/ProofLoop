# ReservationFlow greenfield benchmark

ReservationFlow is the T3 greenfield fixture for measuring whether ProofLoop earns its overhead on a project-sized task. The target is a standard-library Python reservation service with persistence, idempotency, capacity enforcement, cancellation, and concurrent callers.

Create a clean benchmark repository from `seed/`, initialize Git, then run the normal ProofLoop benchmark with `suite.json`. Use at least five paired repetitions and compare `single-model`, `adaptive`, and `full` policies. The suite verifier is a protected benchmark artifact and must remain byte-identical.

```bash
cp -R benchmarks/reservation-flow/seed /tmp/reservation-flow
cd /tmp/reservation-flow
git init
git add .
git commit -m baseline
proofloop-core benchmark --suite /path/to/ProofLoop/benchmarks/reservation-flow/suite.json --repo . --mode system --policy both --repetitions 5 --baseline-host codex --baseline-model gpt-5.6
```

This fixture complements SWE-Skills-Bench: SWE-Skills-Bench provides real repository/domain breadth, while ReservationFlow tests long-horizon greenfield convergence and recovery under one stable external contract.
