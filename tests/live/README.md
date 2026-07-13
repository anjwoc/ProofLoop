# Authenticated live acceptance tests

The live runner uses the user's installed and authenticated host CLI.

```bash
python3 scripts/run_host_live.py --host codex --scenario normal --keep-workspace
python3 scripts/run_host_live.py --host codex --scenario recovery --keep-workspace
python3 scripts/run_host_live.py --host antigravity --scenario normal --keep-workspace
python3 scripts/run_host_live.py --host antigravity --scenario recovery --keep-workspace
```

A normal run requires a `PROVEN` orchestrator truth report.

A recovery run additionally requires a real `implementer_recovery` invocation after objective failed checks. If the fast model succeeds immediately, the result is `UNPROVEN / RECOVERY_NOT_OBSERVED` for recovery capability even though the implementation may be correct.

Reports are copied to:

```text
reports/live/<host>-<scenario>/
```

A release cannot pass from static or simulated evidence alone.
