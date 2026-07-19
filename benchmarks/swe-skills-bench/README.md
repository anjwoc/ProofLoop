# ProofLoop SWE-Skills-Bench bridge

This profile pins nine official SWE-Skills-Bench tasks at upstream commit `95b3ce519fcb58d0b19e90a5b6e5165211dc6dd1`: three backend, three frontend, and three DevOps tasks. It measures a single-model baseline against ProofLoop `adaptive` and `full` policies; skill documents remain provenance inputs, not trusted proof.

Generate and inspect a suite from an official checkout:

```bash
proofloop-core import-swe-bench --upstream /path/to/SWE-Skills-Bench --output /tmp/proofloop-swe-suite.json
proofloop-core inspect-swe-bench --suite /tmp/proofloop-swe-suite.json
```

The official tasks require their pinned repositories, copied evaluator tests, Docker images, and model credentials. `inspect-swe-bench` validates coverage and provenance without claiming a performance result. Actual trials must run in the upstream isolated Docker environments; a local suite inspection is only a smoke gate.
