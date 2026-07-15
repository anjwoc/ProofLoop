---
name: using-proofloop
description: Compatibility alias for the ProofLoop automatic coding harness. Use when a user explicitly says using-proofloop or asks to use ProofLoop. Delegate immediately to the proofloop entry skill instead of reproducing the workflow manually.
---

# Using ProofLoop Compatibility Alias

Invoke the `proofloop` skill with the user's complete request.

Do not manually simulate role routing, repair loops, checks, reviews, or truth decisions. The `proofloop` skill must launch `proofloop-core goal`, which owns the complete workflow.
