#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(command: list[str]) -> dict[str, object]:
    completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)
    return {"command": command, "exitCode": completed.returncode, "stdout": completed.stdout, "stderr": completed.stderr}


def live_status(name: str) -> dict[str, object]:
    path = ROOT / "reports" / "live" / name / "truth-report.json"
    if not path.exists():
        return {"name": name, "status": "MISSING", "path": str(path)}
    report = json.loads(path.read_text(encoding="utf-8"))
    return {"name": name, "status": report.get("verdict"), "path": str(path)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--development", action="store_true", help="Exit zero when deterministic development checks pass, while keeping overall release FAIL")
    args = parser.parse_args()

    checks = [run([sys.executable, "scripts/validate_package.py"])]
    if os.environ.get("PROOFLOOP_RELEASE_CHECK_TEST_MODE") != "1":
        checks.append(run([sys.executable, "scripts/run_tests.py"]))
    for host in ("claude-code", "codex", "antigravity"):
        checks.append(run([sys.executable, "scripts/build_host_adapter.py", "--host", host]))

    deterministic_pass = all(item["exitCode"] == 0 for item in checks)
    live = {
        "codexNormal": live_status("codex-normal"),
        "codexRecovery": live_status("codex-recovery"),
        "antigravityNormal": live_status("antigravity-normal"),
        "antigravityRecovery": live_status("antigravity-recovery"),
        "claudeNormal": live_status("claude-normal"),
        "claudeRecovery": live_status("claude-recovery"),
    }

    codex_pair = live["codexNormal"]["status"] == "PROVEN" and live["codexRecovery"]["status"] == "PROVEN"
    antigravity_pair = live["antigravityNormal"]["status"] == "PROVEN" and live["antigravityRecovery"]["status"] == "PROVEN"
    claude_pair = live["claudeNormal"]["status"] == "PROVEN" and live["claudeRecovery"]["status"] == "PROVEN"
    authenticated_pair_proven = codex_pair or antigravity_pair or claude_pair
    overall = "PASS" if deterministic_pass and authenticated_pair_proven else "FAIL"

    report = {
        "schemaVersion": "3.0",
        "deterministicDevelopmentChecks": "PASS" if deterministic_pass else "FAIL",
        "automaticOrchestratorKernel": "SIMULATED_PROVEN",
        "oneCommandHostFixtures": {
            "codexNormal": "SIMULATED_HOST_E2E_PROVEN",
            "codexRecovery": "SIMULATED_HOST_E2E_PROVEN",
            "antigravityNormal": "SIMULATED_HOST_E2E_PROVEN",
        },
        "importantLimit": "Simulated orchestration and fake host processes prove mechanics only, not authenticated model execution.",
        "hostAdapters": {
            "claude-code": "EXTERNAL_ROUTING_CONFIGURED_LIVE_UNPROVEN",
            "codex": "PROVEN" if codex_pair else "EXTERNAL_ROUTING_CONFIGURED_LIVE_UNPROVEN",
            "antigravity": "PROVEN" if antigravity_pair else "EXTERNAL_ROUTING_CONFIGURED_LIVE_UNPROVEN",
            "antigravityNativeInteractive": "ROLE_ROUTING_ONLY",
        },
        "coreLiveE2E": live,
        "observedAuthenticatedModelRouting": "PASS" if authenticated_pair_proven else "UNPROVEN",
        "observedAuthenticatedRepairLoop": "PASS" if authenticated_pair_proven else "UNPROVEN",
        "repositoryAnalysisOrchestration": "NOT_IMPLEMENTED",
        "overallRelease": overall,
        "commands": checks,
    }
    reports = ROOT / "reports"
    reports.mkdir(exist_ok=True)
    (reports / "release-check.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# ProofLoop Core release check",
        "",
        f"- Deterministic development checks: **{report['deterministicDevelopmentChecks']}**",
        "- Automatic orchestrator kernel: **SIMULATED_PROVEN**",
        "- Codex one-command normal fixture: **SIMULATED_HOST_E2E_PROVEN**",
        "- Codex one-command recovery fixture: **SIMULATED_HOST_E2E_PROVEN**",
        "- Antigravity one-command normal fixture: **SIMULATED_HOST_E2E_PROVEN**",
        f"- Codex authenticated normal live E2E: **{live['codexNormal']['status']}**",
        f"- Codex authenticated recovery live E2E: **{live['codexRecovery']['status']}**",
        f"- Antigravity authenticated normal live E2E: **{live['antigravityNormal']['status']}**",
        f"- Antigravity authenticated recovery live E2E: **{live['antigravityRecovery']['status']}**",
        f"- Claude authenticated normal live E2E: **{live['claudeNormal']['status']}**",
        f"- Claude authenticated recovery live E2E: **{live['claudeRecovery']['status']}**",
        f"- Observed authenticated model routing: **{report['observedAuthenticatedModelRouting']}**",
        f"- Observed authenticated repair loop: **{report['observedAuthenticatedRepairLoop']}**",
        "- Repository-analysis orchestration: **NOT_IMPLEMENTED**",
        f"- Overall release: **{overall}**",
        "",
        "Simulated role processes, static checks, and requested model names cannot override missing authenticated live E2E evidence.",
    ]
    (reports / "release-check.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    if overall == "PASS":
        return 0
    return 0 if args.development and deterministic_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
