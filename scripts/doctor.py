#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from proofloop_core.hosts import probe, runtime_home


def exists(path: Path) -> dict[str, object]:
    return {"path": str(path), "exists": path.exists()}


home = Path.home()
proofloop_home = runtime_home()
result = {
    "proofloopRoot": str(ROOT),
    "proofloopHome": str(proofloop_home),
    "runtime": exists(proofloop_home / "runtime" / "proofloop_core"),
    "wrapper": exists(proofloop_home / "bin" / "proofloop-core"),
    "hosts": {
        "claude-code": {
            **probe("claude-code"),
            "defaultProofLoopMode": "EXTERNAL_MODEL_ROUTING",
            "entrySkill": exists(home / ".claude" / "plugins" / "proofloop" / "skills" / "proofloop" / "SKILL.md"),
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
            "note": "The default skill calls proofloop-core orchestrate, which launches isolated Codex role processes. Custom agents remain optional native integration artifacts.",
        },
        "antigravity": {
            **probe("antigravity"),
            "defaultProofLoopMode": "ROLE_ROUTING_ONLY",
            "nativeInteractiveMode": "ROLE_ROUTING_ONLY",
            "crossModelRouting": False,
            "globalSkill": exists(home / ".gemini" / "config" / "skills" / "proofloop" / "SKILL.md"),
            "cliSkill": exists(home / ".gemini" / "antigravity-cli" / "skills" / "proofloop" / "SKILL.md"),
            "workflow": exists(home / ".gemini" / "config" / "global_workflows" / "proofloop.md"),
            "invocation": "/proofloop <request>",
            "permissionBypass": {
                "enabled": os.environ.get("PROOFLOOP_ANTIGRAVITY_BYPASS_PERMISSIONS") == "1",
                "optInVariable": "PROOFLOOP_ANTIGRAVITY_BYPASS_PERMISSIONS=1",
            },
            "note": "The workflow launches role-isolated Antigravity processes on the current session model; cross-model routing is not claimed.",
        },
    },
    "truth": {
        "automaticOrchestratorKernel": "PROVEN_BY_SIMULATED_ORCHESTRATION_TESTS",
        "oneCommandCodexProcessLoop": "PROVEN_BY_SIMULATED_HOST_E2E",
        "oneCommandAntigravityProcessLoop": "PROVEN_BY_SIMULATED_HOST_E2E",
        "deterministicVerification": "PROVEN_BY_LOCAL_TESTS",
        "authenticatedCodexLiveE2E": "UNPROVEN_UNTIL_USER_RUN",
        "authenticatedAntigravityLiveE2E": "UNPROVEN_UNTIL_USER_RUN",
        "repositoryAnalysisOrchestration": "NOT_IMPLEMENTED_BLOCKS_HONESTLY",
    },
}
print(json.dumps(result, indent=2, ensure_ascii=False))
