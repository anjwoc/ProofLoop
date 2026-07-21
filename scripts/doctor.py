#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from proofloop_core.hosts import probe, runtime_home  # noqa: E402
from proofloop_core.tokscale import TokScaleAdapter  # noqa: E402


def exists(path: Path) -> dict[str, object]:
    return {"path": str(path), "exists": path.exists()}


def claude_entry_skill(home: Path) -> Path:
    direct = home / ".claude" / "plugins" / "proofloop" / "skills" / "proofloop" / "SKILL.md"
    registry = home / ".claude" / "plugins" / "installed_plugins.json"
    if registry.exists():
        try:
            installs = json.loads(registry.read_text(encoding="utf-8"))["plugins"]["proofloop@proofloop-local"]
            for install in reversed(installs):
                candidate = Path(install["installPath"]) / "skills" / "proofloop" / "SKILL.md"
                if candidate.exists():
                    return candidate
        except (KeyError, TypeError, ValueError, OSError):
            pass
    return direct


home = Path.home()
proofloop_home = runtime_home()
result = {
    "proofloopRoot": str(ROOT),
    "proofloopHome": str(proofloop_home),
    "runtime": exists(proofloop_home / "runtime" / "proofloop_core"),
    "wrapper": exists(proofloop_home / "bin" / "proofloop-core"),
    "tokscale": TokScaleAdapter().status(),
    "hosts": {
        "claude-code": {
            **probe("claude-code"),
            "defaultProofLoopMode": "EXTERNAL_MODEL_ROUTING",
            "entrySkill": exists(claude_entry_skill(home)),
            "invocation": "/proofloop <request>",
        },
        "codex": {
            **probe("codex"),
            "defaultProofLoopMode": "EXTERNAL_MODEL_ROUTING",
            "plugin": exists(home / ".codex" / "plugins" / "proofloop"),
            "entrySkill": exists(home / ".codex" / "plugins" / "proofloop" / "skills" / "proofloop" / "SKILL.md"),
            "agents": exists(home / ".codex" / "agents" / "proofloop_planner_deep.toml"),
            "marketplace": exists(home / ".agents" / "plugins" / "marketplace.json"),
            "invocation": "$proofloop <request> or /skills",
            "note": "The default skill calls proofloop-core run --mode adaptive, which selects bounded roles from the workload profile and proof gaps. Explicit goal mode continues until convergence or budget exhaustion.",
        },
        "agy": {
            **probe("agy"),
            "defaultProofLoopMode": "EXTERNAL_MODEL_ROUTING",
            "crossModelRouting": True,
            "globalSkill": exists(home / ".gemini" / "config" / "skills" / "proofloop" / "SKILL.md"),
            "cliSkill": exists(home / ".gemini" / "antigravity-cli" / "skills" / "proofloop" / "SKILL.md"),
            "workflow": exists(home / ".gemini" / "config" / "global_workflows" / "proofloop.md"),
            "invocation": "/proofloop <request>",
            "permissionBypass": {
                "enabled": os.environ.get("PROOFLOOP_AGY_BYPASS_PERMISSIONS") == "1",
                "optInVariable": "PROOFLOOP_AGY_BYPASS_PERMISSIONS=1",
            },
            "note": "The workflow launches role-isolated AGY processes using the configured per-role model routing policy.",
        },
    },
    "truth": {
        "automaticOrchestratorKernel": "PROVEN_BY_SIMULATED_ORCHESTRATION_TESTS",
        "oneCommandCodexProcessLoop": "PROVEN_BY_SIMULATED_HOST_E2E",
        "oneCommandAntigravityProcessLoop": "PROVEN_BY_SIMULATED_HOST_E2E",
        "deterministicVerification": "PROVEN_BY_LOCAL_TESTS",
        "authenticatedCodexLiveE2E": "UNPROVEN_UNTIL_USER_RUN",
        "authenticatedAntigravityLiveE2E": "UNPROVEN_UNTIL_USER_RUN",
        "repositoryAuditMode": "IMPLEMENTED_READ_ONLY",
        "legacyAnalysisStrategy": "BLOCKED_OUTSIDE_AUDIT_MODE",
    },
}
print(json.dumps(result, indent=2, ensure_ascii=False))
