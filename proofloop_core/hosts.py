from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

HOST_CAPABILITIES: dict[str, dict[str, Any]] = {
    "claude-code": {
        "binary": "claude",
        "mode": "NATIVE_MODEL_ROUTING",
        "roles": {
            "planner_deep": {"model": "opus", "reasoning": "high", "sandbox": "read-only"},
            "implementer_fast": {"model": "haiku", "reasoning": "medium", "sandbox": "workspace-write"},
            "implementer_recovery": {"model": "sonnet", "reasoning": "high", "sandbox": "workspace-write"},
            "reviewer_deep": {"model": "fable", "reasoning": "high", "sandbox": "read-only"},
        },
    },
    "codex": {
        "binary": "codex",
        "mode": "NATIVE_MODEL_ROUTING",
        "roles": {
            "planner_deep": {"model": "gpt-5.6", "reasoning": "high", "sandbox": "read-only"},
            "implementer_fast": {"model": "gpt-5.6-terra", "reasoning": "medium", "sandbox": "workspace-write"},
            "implementer_recovery": {"model": "gpt-5.6", "reasoning": "high", "sandbox": "workspace-write"},
            "reviewer_deep": {"model": "gpt-5.6", "reasoning": "high", "sandbox": "read-only"},
        },
    },
    "antigravity": {
        "binary": "agy",
        "mode": "ROLE_ROUTING_ONLY",
        "externalMode": "EXTERNAL_MODEL_ROUTING_EXPERIMENTAL",
        "externalRoles": {
            "planner_deep": {"model": "Gemini 3.1 Pro (High)", "reasoning": "high", "sandbox": "host-managed"},
            "implementer_fast": {"model": "Gemini 3.5 Flash (Low)", "reasoning": "low", "sandbox": "host-managed"},
            "implementer_recovery": {"model": "Gemini 3.1 Pro (High)", "reasoning": "high", "sandbox": "host-managed"},
            "reviewer_deep": {"model": "Gemini 3.1 Pro (High)", "reasoning": "high", "sandbox": "host-managed"},
        },
        "roles": {
            "planner_deep": {"model": "current-session-model", "reasoning": None, "sandbox": "host-managed"},
            "implementer_fast": {"model": "current-session-model", "reasoning": None, "sandbox": "host-managed"},
            "implementer_recovery": {"model": "current-session-model", "reasoning": None, "sandbox": "host-managed"},
            "reviewer_deep": {"model": "current-session-model", "reasoning": None, "sandbox": "host-managed"},
        },
    },
}


def capability(host: str) -> dict[str, Any]:
    if host not in HOST_CAPABILITIES:
        raise ValueError(f"unsupported host: {host}")
    return json.loads(json.dumps(HOST_CAPABILITIES[host]))


def probe(host: str) -> dict[str, Any]:
    config = capability(host)
    executable = shutil.which(str(config["binary"]))
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
    }
    if executable:
        completed = subprocess.run([executable, "--version"], text=True, capture_output=True, check=False)
        result["version"] = (completed.stdout or completed.stderr).strip() or None
        result["versionExitCode"] = completed.returncode
    return result


_AGENT_INSTRUCTIONS = {
    "planner_deep": """Act only as ProofLoop's deep planner. Inspect real repository evidence, choose the smallest sufficient solution, define acceptance criteria, required checks, allowed paths, protected paths, change budgets, and explicit escalation conditions. Do not edit production code. Create an executable task brief and distinguish facts, inferences, and unknowns.""",
    "implementer_fast": """Act only as ProofLoop's bounded fast implementer. Work on one approved task brief. Use TDD for behavior changes, make the minimum change inside allowed paths, do not broaden scope, and never claim checks passed. Run ProofLoop deterministic checks and leave evidence for the coordinator.""",
    "implementer_recovery": """Act as ProofLoop's recovery implementer after repeated objective failures. Use the task brief, exact failing command output, fingerprint, and current diff. Fix the root cause without expanding the contract. Return to the planner instead of redesigning public APIs, schemas, or architecture without approval.""",
    "reviewer_deep": """Act as an isolated ProofLoop owner-level reviewer. Review the task brief, source diff, deterministic check evidence, test integrity, and simplicity budget. Return APPROVED, FIX_REQUIRED, DESIGN_CONFLICT, or CANNOT_VERIFY plus simplicityVerdict MINIMAL, OVERBUILT, or CANNOT_VERIFY. Never trust the implementer's summary.""",
}


def render_codex_agent(role: str) -> str:
    config = capability("codex")["roles"][role]
    description = {
        "planner_deep": "Deep read-only planner for evidence-based minimal implementation plans.",
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
    for role in ("planner_deep", "implementer_fast", "implementer_recovery", "reviewer_deep"):
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


def antigravity_workflow() -> str:
    return """---
description: Run the automatic ProofLoop coding harness. One workflow invocation launches the orchestrator, which owns role allocation, real verification, bounded repair, independent review, anti-bloat checks, and truth-gated completion.
---

# ProofLoop

Do not simulate the workflow in this Antigravity session.

1. Preserve the complete user request following `/proofloop` in `.proofloop/requests/` as a UTF-8 text file.
2. Run exactly one bootstrap command:

```bash
$HOME/.proofloop/bin/proofloop-core orchestrate \
  --host antigravity \
  --repo . \
  --request-file <absolute-request-file>
```

3. The orchestrator will start isolated Antigravity CLI role processes, run actual checks, calculate failure fingerprints, retry or escalate, request review, and build the truth report.
4. Do not call `invoke-role`, `record-attempt`, or `verify-run` manually.
5. Report `PROVEN`, `UNPROVEN`, `FAILED`, or `BLOCKED` exactly as returned. Requested model names are not proof of resolved models.
"""


def role_only_trace_summary(host: str = "antigravity") -> dict[str, Any]:
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
