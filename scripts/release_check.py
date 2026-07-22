#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from proofloop_core.context.io import read_json


def run(command: list[str]) -> dict[str, object]:
    completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)
    return {"command": command, "exitCode": completed.returncode, "stdout": completed.stdout, "stderr": completed.stderr}


def live_status(name: str, *, expected_host: str, expected_scenario: str) -> dict[str, object]:
    path = ROOT / "reports" / "live" / name / "truth-report.json"
    if not path.exists():
        return {"name": name, "status": "MISSING", "path": str(path)}
    try:
        report = read_json(path)
    except ValueError:
        return {"name": name, "status": "INVALID_ARTIFACT", "path": str(path), "reason": "INVALID_JSON"}
    required = {
        "source": "AUTHENTICATED_HOST_RUN",
        "host": expected_host,
        "scenario": expected_scenario,
        "hostExitCode": 0,
    }
    mismatches = [key for key, value in required.items() if report.get(key) != value]
    original = path.parent / "orchestrator-truth-report.json"
    if not original.is_file():
        mismatches.append("orchestratorTruthReport")
    else:
        try:
            original_report = read_json(original)
        except ValueError:
            mismatches.append("orchestratorTruthReport")
        else:
            if original_report.get("verdict") != "PROVEN":
                mismatches.append("orchestratorTruthVerdict")
    required_artifacts = ("events.jsonl", "invocations.jsonl", "usage/usage-summary.json", "expected-output-report.json")
    missing_artifacts = [item for item in required_artifacts if not (path.parent / item).is_file()]
    expected_output = path.parent / "expected-output-report.json"
    if expected_output.is_file():
        try:
            experience = read_json(expected_output)
        except ValueError:
            mismatches.append("expectedOutputReport")
        else:
            if experience.get("status") != "PASS" or experience.get("requireTerminal") is not True:
                mismatches.append("expectedOutputContract")
    if mismatches or missing_artifacts:
        return {
            "name": name,
            "status": "INVALID_ARTIFACT",
            "path": str(path),
            "mismatches": mismatches,
            "missingArtifacts": missing_artifacts,
        }
    return {"name": name, "status": report.get("verdict"), "path": str(path)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--development", action="store_true", help="Exit zero when deterministic development checks pass, while keeping overall release FAIL")
    args = parser.parse_args()

    checks = [run([sys.executable, "scripts/validate_package.py"])]
    if os.environ.get("PROOFLOOP_RELEASE_CHECK_TEST_MODE") != "1":
        checks.append(run([sys.executable, "scripts/run_tests.py"]))
    for host in ("claude-code", "codex", "agy"):
        checks.append(run([sys.executable, "scripts/build_host_adapter.py", "--host", host]))

    deterministic_pass = all(item["exitCode"] == 0 for item in checks)
    live = {
        "codexNormal": live_status("codex-normal", expected_host="codex", expected_scenario="normal"),
        "codexRecovery": live_status("codex-recovery", expected_host="codex", expected_scenario="recovery"),
        "agyNormal": live_status("agy-normal", expected_host="agy", expected_scenario="normal"),
        "agyRecovery": live_status("agy-recovery", expected_host="agy", expected_scenario="recovery"),
        "claudeNormal": live_status("claude-normal", expected_host="claude-code", expected_scenario="normal"),
        "claudeRecovery": live_status("claude-recovery", expected_host="claude-code", expected_scenario="recovery"),
    }

    codex_pair = live["codexNormal"]["status"] == "PROVEN" and live["codexRecovery"]["status"] == "PROVEN"
    agy_pair = live["agyNormal"]["status"] == "PROVEN" and live["agyRecovery"]["status"] == "PROVEN"
    claude_pair = live["claudeNormal"]["status"] == "PROVEN" and live["claudeRecovery"]["status"] == "PROVEN"
    authenticated_pairs_proven = codex_pair and agy_pair and claude_pair
    overall = "PASS" if deterministic_pass and authenticated_pairs_proven else "FAIL"

    report = {
        "schemaVersion": "3.0",
        "deterministicDevelopmentChecks": "PASS" if deterministic_pass else "FAIL",
        "automaticOrchestratorKernel": "SIMULATED_MECHANICS_PROVEN",
        "oneCommandHostFixtures": {
            "codexNormal": "SIMULATED_HOST_E2E_PROVEN",
            "codexRecovery": "SIMULATED_HOST_E2E_PROVEN",
            "agyNormal": "SIMULATED_HOST_E2E_PROVEN",
        },
        "importantLimit": "Simulated orchestration and fake host processes prove mechanics only, not authenticated model execution.",
        "hostAdapters": {
            "claude-code": "EXTERNAL_ROUTING_CONFIGURED_LIVE_UNPROVEN",
            "codex": "PROVEN" if codex_pair else "EXTERNAL_ROUTING_CONFIGURED_LIVE_UNPROVEN",
            "agy": "PROVEN" if agy_pair else "EXTERNAL_ROUTING_CONFIGURED_LIVE_UNPROVEN",
        },
        "coreLiveE2E": live,
        "observedAuthenticatedModelRouting": "PASS" if authenticated_pairs_proven else "UNPROVEN",
        "observedAuthenticatedRepairLoop": "PASS" if authenticated_pairs_proven else "UNPROVEN",
        "repositoryAuditMode": "IMPLEMENTED_READ_ONLY",
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
        "- Automatic orchestrator kernel: **SIMULATED_MECHANICS_PROVEN**",
        "- Codex one-command normal fixture: **SIMULATED_HOST_E2E_PROVEN**",
        "- Codex one-command recovery fixture: **SIMULATED_HOST_E2E_PROVEN**",
        "- AGY one-command normal fixture: **SIMULATED_HOST_E2E_PROVEN**",
        f"- Codex authenticated normal live E2E: **{live['codexNormal']['status']}**",
        f"- Codex authenticated recovery live E2E: **{live['codexRecovery']['status']}**",
        f"- AGY authenticated normal live E2E: **{live['agyNormal']['status']}**",
        f"- AGY authenticated recovery live E2E: **{live['agyRecovery']['status']}**",
        f"- Claude authenticated normal live E2E: **{live['claudeNormal']['status']}**",
        f"- Claude authenticated recovery live E2E: **{live['claudeRecovery']['status']}**",
        f"- Observed authenticated model routing: **{report['observedAuthenticatedModelRouting']}**",
        f"- Observed authenticated repair loop: **{report['observedAuthenticatedRepairLoop']}**",
        "- Repository audit mode: **IMPLEMENTED_READ_ONLY**",
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
