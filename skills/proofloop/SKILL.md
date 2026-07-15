---
name: proofloop
description: Use when the user invokes ProofLoop or requests non-trivial feature work, bug fixes, refactors, or risky code changes that should run through ProofLoop's automatic evidence-driven coding harness.
---

# ProofLoop Entry Skill

This skill is a thin bootstrap. The deterministic orchestrator owns the workflow.

## Required behavior

1. Capture the user's complete request verbatim in a UTF-8 text file under `.proofloop/requests/`.
2. Determine the current host as exactly one of `claude-code`, `codex`, or `antigravity`.
3. Run one command:

```bash
$HOME/.proofloop/bin/proofloop-core goal \
  --host <current-host> \
  --repo . \
  --request-file <absolute-request-file> \
  --output-format human \
  --verbosity info \
  --color auto
```

4. Do not implement the task in the coordinator session while the command runs.
5. Do not synthesize planning, role, verification, retry, recovery, review, or truth status. Display the orchestrator stream as the system status source.
6. Present the returned `truth-report.json` status exactly. Never upgrade `UNPROVEN`, `FAILED`, or `BLOCKED` to success.

## Host invocation names

- Claude Code: `/proofloop <request>`
- Codex: select `proofloop` through `/skills` or invoke `$proofloop <request>`
- Antigravity: `/proofloop <request>`

Internal role execution is an orchestrator implementation detail and must not be shown as a user step.
