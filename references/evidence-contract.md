# Evidence contract

ProofLoop distinguishes four states:

- `CONFIGURED`: a role or model is declared in a file.
- `SIMULATED`: a fixture exercised orchestration mechanics.
- `OBSERVED`: an actual command, model call, or trace was captured.
- `PROVEN`: all required observed evidence satisfies the truth gate.

A command is observed only when the report contains its argument vector, working directory, exit code, timestamps, and immutable stdout/stderr references.

Model routing is observed only when a host or external bridge records the role, actual model identifier, invocation identifier, and time range. Expected bindings are not observed bindings.

A retry is observed only when a failed check is followed by a distinct implementation invocation and a subsequent deterministic check.
