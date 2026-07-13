---
name: proofloop
description: Run ProofLoop's automatic evidence-driven coding harness. Use for non-trivial feature work, bug fixes, refactors, risky code changes, or whenever the user invokes ProofLoop. The skill launches one orchestrator command; it must not manually simulate planning, retries, model switching, verification, or completion.
---

# ProofLoop Entry Skill

This skill is a thin bootstrap. The deterministic orchestrator owns the workflow.

## Required behavior

1. Capture the user's complete request verbatim in a UTF-8 text file under `.proofloop/requests/`.
2. Determine the current host as exactly one of `claude-code`, `codex`, or `antigravity`.
3. Run one command:

```bash
$HOME/.proofloop/bin/proofloop-core orchestrate \
  --host <current-host> \
  --repo . \
  --request-file <absolute-request-file>
```

4. Do not implement the task in the coordinator session while the command runs.
5. Do not manually call `invoke-role`, `record-attempt`, `run-checks`, `diff-guard`, or `verify-run` unless the orchestrator explicitly reports an internal diagnostic instruction.
6. Present the returned `truth-report.json` status exactly. Never upgrade `UNPROVEN`, `FAILED`, or `BLOCKED` to success.

## Host invocation names

- Claude Code: `/proofloop <request>`
- Codex: select `proofloop` through `/skills` or invoke `$proofloop <request>`
- Antigravity: `/proofloop <request>`

The internal role commands are implementation details and must not be shown as normal user steps.
