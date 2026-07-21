from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .runtime import CONTROLLER_ROUTES, RuntimeRegistry, runtime_spec


def _host_capability(host: str) -> dict[str, Any]:
    spec = runtime_spec(host)
    mode = "NATIVE_MODEL_ROUTING"
    roles = {
        role: {
            "model": route.model,
            "reasoning": route.reasoning,
            "sandbox": route.access_mode,
            "runtime": route.runtime_id,
        }
        for role, route in CONTROLLER_ROUTES[host].items()
    }
    return {
        "binary": spec.launcher.command,
        "mode": mode,
        "transport": "auto" if spec.supports_acp else "legacy-cli",
        "supportsACP": spec.supports_acp,
        "roles": roles,
    }


HOST_CAPABILITIES: dict[str, dict[str, Any]] = {
    host: _host_capability(host) for host in CONTROLLER_ROUTES
}


def capability(host: str) -> dict[str, Any]:
    if host not in HOST_CAPABILITIES:
        raise ValueError(f"unsupported host: {host}")
    return json.loads(json.dumps(HOST_CAPABILITIES[host]))


def probe(host: str) -> dict[str, Any]:
    config = capability(host)
    binary = str(config["binary"])
    executable = shutil.which(binary)
    if not executable:
        for path in ["/usr/local/bin", "/opt/homebrew/bin", "/usr/bin"]:
            candidate = Path(path) / binary
            if candidate.exists() and os.access(candidate, os.X_OK):
                executable = str(candidate)
                break
    result: dict[str, Any] = {
        "host": host,
        "mode": config["mode"],
        "roles": config["roles"],
        "externalMode": config.get("externalMode"),
        "externalRoles": config.get("externalRoles"),
        "available": executable is not None,
        "path": executable,
        "version": None,
        "modelRoutingStatus": "CONFIGURED_UNPROVEN" if config["mode"] == "NATIVE_MODEL_ROUTING" else "ROLE_ROUTING_ONLY",
        "runtimeCatalog": RuntimeRegistry().catalog(),
    }
    if executable:
        completed = subprocess.run([executable, "--version"], text=True, capture_output=True, check=False)
        result["version"] = (completed.stdout or completed.stderr).strip() or None
        result["versionExitCode"] = completed.returncode
    return result


_AGENT_INSTRUCTIONS = {
    "planner_deep": """Act only as ProofLoop's deep planner. Inspect real repository evidence, choose the smallest sufficient solution, define acceptance criteria, required checks, allowed paths, protected paths, change budgets, and explicit escalation conditions. Do not edit production code. Create an executable task brief and distinguish facts, inferences, and unknowns.""",
    "explorer_fast": """Act only as ProofLoop's read-only explorer. Map the smallest relevant execution path, impacted callers, existing tests, constraints, and open risks. Do not edit source and do not propose implementation beyond evidence.""",
    "implementer_fast": """Act only as ProofLoop's bounded fast implementer. Work on one approved task brief. Use TDD for behavior changes, make the minimum change inside allowed paths, do not broaden scope, and never claim checks passed. Run ProofLoop deterministic checks and leave evidence for the coordinator.""",
    "implementer_recovery": """Act as ProofLoop's recovery implementer after repeated objective failures. Use the task brief, exact failing command output, fingerprint, and current diff. Fix the root cause without expanding the contract. Return to the planner instead of redesigning public APIs, schemas, or architecture without approval.""",
    "reviewer_deep": """Act as an isolated ProofLoop owner-level reviewer. Review the task brief, source diff, deterministic check evidence, test integrity, and simplicity budget. Return APPROVED, FIX_REQUIRED, DESIGN_CONFLICT, or CANNOT_VERIFY plus simplicityVerdict MINIMAL, OVERBUILT, or CANNOT_VERIFY. Never trust the implementer's summary.""",
}


def render_codex_agent(role: str) -> str:
    config = capability("codex")["roles"][role]
    description = {
        "planner_deep": "Deep read-only planner for evidence-based minimal implementation plans.",
        "explorer_fast": "Fast read-only explorer for repository and impact evidence.",
        "implementer_fast": "Fast bounded implementer for one approved ProofLoop task.",
        "implementer_recovery": "High-capability recovery implementer for repeated objective failures.",
        "reviewer_deep": "Independent owner-level reviewer for correctness, evidence, and simplicity.",
    }[role]
    return (
        f'name = "proofloop_{role}"\n'
        f'description = "{description}"\n'
        f'model = "{config["model"]}"\n'
        f'model_reasoning_effort = "{config["reasoning"]}"\n'
        f'sandbox_mode = "{config["sandbox"]}"\n'
        'developer_instructions = """\n'
        f'{_AGENT_INSTRUCTIONS[role]}\n'
        'Use $HOME/.proofloop/bin/proofloop-core for deterministic ProofLoop commands.\n'
        '"""\n'
    )


def write_codex_agents(output: str | Path) -> list[str]:
    root = Path(output)
    root.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    for role in capability("codex")["roles"]:
        path = root / f"proofloop_{role}.toml"
        path.write_text(render_codex_agent(role), encoding="utf-8")
        written.append(str(path))
    return written


def _walk_strings(value: Any) -> list[str]:
    values: list[str] = []
    if isinstance(value, str):
        values.append(value)
    elif isinstance(value, dict):
        for item in value.values():
            values.extend(_walk_strings(item))
    elif isinstance(value, list):
        for item in value:
            values.extend(_walk_strings(item))
    return values


def detect_model(value: Any) -> str | None:
    if isinstance(value, dict):
        for key in ("resolved_model", "resolvedModel", "model", "model_id", "modelId"):
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
    pattern = re.compile(r"(?:\bgpt-5\.6(?:-(?:sol|terra|luna))?\b|\bgpt-5\.[0-9][\w.-]*\b|\bclaude-[\w.-]+\b|Gemini\s+[0-9.]+\s+(?:Pro|Flash)(?:\s*\([^)]*\))?|Claude\s+(?:Opus|Sonnet|Haiku)\s+[0-9.]+(?:\s*\([^)]*\))?)", re.I)
    for text in _walk_strings(value):
        match = pattern.search(text)
        if match:
            return match.group(0)
    return None


def role_from_agent_type(value: str | None) -> str | None:
    if not value:
        return None
    normalized = value.lower().replace("-", "_")
    for role in ("planner_deep", "explorer_fast", "implementer_fast", "implementer_recovery", "reviewer_deep"):
        if role in normalized:
            return role
    if "planner" in normalized:
        return "planner_deep"
    if "recovery" in normalized:
        return "implementer_recovery"
    if "implement" in normalized:
        return "implementer_fast"
    if "review" in normalized:
        return "reviewer_deep"
    return None


def parse_codex_transcript(path: str | Path | None) -> dict[str, Any]:
    if not path:
        return {"observedModel": None, "eventCount": 0}
    source = Path(path).expanduser()
    if not source.exists() or not source.is_file():
        return {"observedModel": None, "eventCount": 0}
    model: str | None = None
    count = 0
    try:
        for line in source.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.strip():
                continue
            count += 1
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                item = line
            model = detect_model(item) or model
    except OSError:
        pass
    return {"observedModel": model, "eventCount": count}


def agy_workflow() -> str:
    return r"""---
name: proofloop
description: Run ProofLoop while continuously relaying observed planner, implementer, check, recovery, review, and truth progress in the AGY conversation.
---

# ProofLoop

Do not simulate the workflow in this AGY session.

1. Preserve the complete user request following `/proofloop` in `.proofloop/requests/` as a UTF-8 text file.
2. Tell the user that the external ProofLoop orchestrator is launching and that observed progress will be relayed.
3. Start the `proofloop-core orchestrate` command in a detached background process. Replace `<absolute-request-file>` before running this block:

```bash
RELAY_DIR="$(pwd)/.proofloop/relay/$(date -u +%Y%m%dT%H%M%SZ)-$$"
mkdir -p "$RELAY_DIR"
printf '1\n' > "$RELAY_DIR/next-line"
PROOFLOOP_AGY_BYPASS_PERMISSIONS=1 nohup "$HOME/.proofloop/bin/proofloop-core" run \
  --mode adaptive \
  --host agy \
  --repo . \
  --request-file <absolute-request-file> \
  --output-format human \
  --verbosity info \
  --color never \
  > "$RELAY_DIR/output.log" 2>&1 < /dev/null &
printf '%s\n' "$!" > "$RELAY_DIR/pid"
printf 'RELAY_DIR=%s\nPID=%s\n' "$RELAY_DIR" "$(cat "$RELAY_DIR/pid")"
```

4. Retain the absolute `RELAY_DIR`. Re-run the following command in separate terminal tool calls until it prints `PROOFLOOP_RELAY_FINISHED`. Do not keep one terminal call blocked for the whole run, and do not return control to the user while it is active:

```bash
"$HOME/.proofloop/bin/proofloop-core" relay --relay-dir "$RELAY_DIR" --wait-seconds 3
```

5. Relay every new `[ProofLoop]` line to the user between polling tool calls. The command prints every new observable line exactly once. Present the observed role, phase, elapsed time, PID, check, recovery, review, and host output lines. Do not invent progress or expose provider private reasoning or the submitted prompt.
6. When the relay finishes, extract the run ID from the first `ProofLoop run` line in `output.log`, read `.proofloop/runs/<run-id>/truth-report.json`, and present its `PROVEN`, `UNPROVEN`, `FAILED`, or `BLOCKED` status exactly. Requested model names are not proof of resolved models.
"""


def role_only_trace_summary(host: str) -> dict[str, Any]:
    """Compatibility projection for legacy host capabilities.

    Current supported hosts use external model routing, but old run artifacts
    can still be replayed through this branch.  Keeping the projection generic
    avoids retaining a removed host name in the public contract.
    """
    return {
        "schemaVersion": "2.0",
        "host": host,
        "capabilityMode": "ROLE_ROUTING_ONLY",
        "routingClaimed": False,
        "routingObserved": False,
        "requiredRoles": [],
        "observedModelsByRole": {},
        "missingRoles": [],
        "eventCount": 0,
        "note": "Role separation is enabled, but cross-model routing is neither claimed nor proven.",
    }


def runtime_home() -> Path:
    return Path(os.environ.get("PROOFLOOP_HOME", Path.home() / ".proofloop"))
