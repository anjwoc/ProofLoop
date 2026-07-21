from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


def make_repo(root: Path) -> None:
    git(root, "init")
    git(root, "config", "user.email", "test@example.com")
    git(root, "config", "user.name", "Test")
    (root / "src").mkdir()
    (root / "tests").mkdir()
    (root / "src" / "value.py").write_text('def get_value():\n    return "broken"\n', encoding="utf-8")
    (root / "tests" / "test_value.py").write_text(
        "import unittest\nfrom src.value import get_value\n\n"
        "class T(unittest.TestCase):\n"
        "    def test_value(self): self.assertEqual('fixed', get_value())\n",
        encoding="utf-8",
    )
    git(root, "add", ".")
    git(root, "commit", "-m", "baseline")


FAKE_HOST = r'''#!/usr/bin/env python3
import json, os, re, sys
from pathlib import Path

if "--version" in sys.argv:
    print("fake-host 1.0")
    raise SystemExit(0)

args = sys.argv[1:]
model = "unknown-model"
if "--model" in args:
    model = args[args.index("--model") + 1]
prompt = args[-1]
if Path(sys.argv[0]).name == "agy" and not prompt:
    prompt = sys.stdin.read()
repo = Path.cwd()

if "read-only ProofLoop explorer" in prompt:
    result_payload = {
        "schemaVersion": "1.0", "entryPoints": ["src/value.py"],
        "impactedFiles": ["src/value.py"], "tests": ["tests/test_value.py"],
        "constraints": ["bounded fixture"], "openRisks": []
    }
elif "deep planner" in prompt:
    plan = {
        "schemaVersion": "1.0", "verdict": "READY", "summary": "bounded fixture plan",
        "tasks": [{
            "id": "TASK-001", "objective": "fix value",
            "allowedPaths": ["src/**", "tests/**"], "protectedPaths": [],
            "requiredChecks": [{"name": "unit", "command": ["python3", "-m", "unittest", "discover", "-s", "tests"], "timeoutSeconds": 30}],
            "changeBudget": {"maxChangedFiles": 2, "maxAddedLines": 20, "maxNewFiles": 0, "allowDependencyChanges": False},
            "simplicity": {"selectedRung": "DIRECT_CHANGE", "rationale": "one function", "considered": ["reuse existing"]},
            "budgets": {"maxFastAttempts": 2, "maxRecoveryAttempts": 1}
        }]
    }
    result_payload = plan
elif "fast implementer for a direct verified change" in prompt:
    (repo / "src" / "value.py").write_text('def get_value():\n    return "fixed"\n', encoding="utf-8")
    result_payload = {
        "id": "TASK-001", "objective": "fix value",
        "allowedPaths": ["src/**", "tests/**"], "protectedPaths": [],
        "requiredChecks": [{"name": "unit", "command": ["python3", "-m", "unittest", "discover", "-s", "tests"], "timeoutSeconds": 30}],
        "changeBudget": {"maxChangedFiles": 2, "maxAddedLines": 20, "maxNewFiles": 0, "allowDependencyChanges": False},
        "simplicity": {"selectedRung": "DIRECT_CHANGE", "rationale": "one function", "considered": ["reuse existing"]},
        "budgets": {"maxFastAttempts": 2, "maxRecoveryAttempts": 1}
    }
elif "Role: implementer_fast" in prompt:
    count_path = repo / ".proofloop" / "fake-fast-count"
    count_path.parent.mkdir(parents=True, exist_ok=True)
    count = int(count_path.read_text() or "0") + 1 if count_path.exists() else 1
    count_path.write_text(str(count), encoding="utf-8")
    if os.environ.get("FAKE_PROOFLOOP_RECOVERY") != "1":
        (repo / "src" / "value.py").write_text('def get_value():\n    return "fixed"\n', encoding="utf-8")
    result_payload = {"status":"DONE","classification":"LOCAL_IMPLEMENTATION"}
elif "Role: implementer_recovery" in prompt:
    (repo / "src" / "value.py").write_text('def get_value():\n    return "fixed"\n', encoding="utf-8")
    result_payload = {"status":"DONE","classification":"LOCAL_IMPLEMENTATION"}
elif "final reviewer" in prompt:
    contracts = sorted((repo / ".proofloop" / "runs").glob("*/goal-contract.json"))
    criteria = []
    if contracts:
        contract = json.loads(contracts[-1].read_text(encoding="utf-8"))
        criteria = [
            {"id": item["criterion_id"], "status": "SATISFIED", "evidence": ["fixture"]}
            for item in contract.get("criteria", [])
        ]
    result_payload = {"verdict":"APPROVED","simplicityVerdict":"MINIMAL","criteria":criteria,"findings":[],"deletionCandidates":[]}
else:
    print("unknown role prompt", file=sys.stderr)
    raise SystemExit(3)

print("PROOFLOOP_RESULT_BEGIN")
print(json.dumps(result_payload))
print("PROOFLOOP_RESULT_END")
if Path(sys.argv[0]).name == "codex":
    print(json.dumps({"type": "thread.started", "model": model}))
    print(json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "fixture live output"}}))
else:
    print(json.dumps({"event": "model_resolved", "resolvedModel": model}))
'''


class OrchestrateCLITest(unittest.TestCase):
    """SIMULATED_HOST_E2E: host CLIs are deterministic child-process fixtures."""

    def _run(
        self,
        host: str,
        recovery: bool = False,
        output_format: str | None = None,
        command_name: str = "orchestrate",
        watch: bool = False,
        skills_enabled: bool = True,
    ) -> tuple[subprocess.CompletedProcess[str], Path]:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        repo = root / "repo"
        repo.mkdir()
        make_repo(repo)
        bin_dir = root / "bin"
        bin_dir.mkdir()
        binary_name = "codex" if host == "codex" else "agy"
        binary = bin_dir / binary_name
        binary.write_text(FAKE_HOST, encoding="utf-8")
        binary.chmod(0o755)
        env = dict(os.environ)
        env["PATH"] = str(bin_dir) + os.pathsep + env.get("PATH", "")
        env["PYTHONPATH"] = str(ROOT)
        if recovery:
            env["FAKE_PROOFLOOP_RECOVERY"] = "1"
        if command_name == "goal":
            routes = {
                role: [{"runtime": "codex", "model": model, "reasoning": "high", "accessMode": access}]
                for role, model, access in (
                    ("planner_deep", "gpt-5.6", "read-only"),
                    ("explorer_fast", "gpt-5.6-terra", "read-only"),
                    ("implementer_fast", "gpt-5.6-terra", "workspace-write"),
                    ("implementer_recovery", "gpt-5.6", "workspace-write"),
                    ("reviewer_deep", "gpt-5.6", "read-only"),
                )
            }
            env["PROOFLOOP_ROLE_ROUTING_JSON"] = json.dumps(routes)
        command = [sys.executable, "-m", "proofloop_core.cli", command_name, "--host", host, "--repo", str(repo), "--request", "Implement the bounded value behavior", "--strategy", "planned", "--timeout-seconds", "30"]
        if output_format is not None:
            command.extend(["--output-format", output_format, "--verbosity", "info", "--color", "never"])
        if watch:
            command.append("--watch")
        if command_name == "run" and not skills_enabled:
            command.extend(["--skills", "disabled"])
        completed = subprocess.run(
            command,
            cwd=ROOT, env=env, capture_output=True, text=True, check=False, timeout=90,
        )
        return completed, repo

    def test_goal_command_explores_and_converges(self) -> None:
        completed, repo = self._run("codex", output_format="human", command_name="goal")
        self.assertEqual(0, completed.returncode, completed.stderr + completed.stdout)
        run = sorted((repo / ".proofloop" / "runs").iterdir())[-1]
        state = json.loads((run / "goal-state.json").read_text(encoding="utf-8"))
        roles = [json.loads(line)["role"] for line in (run / "invocations.jsonl").read_text().splitlines()]
        self.assertEqual("CONVERGED", state["state"])
        self.assertEqual(["explorer_fast", "planner_deep", "implementer_fast", "reviewer_deep"], roles)
        self.assertTrue((run / "goal-contract.json").exists())
        self.assertIn("explorer_fast: fixture live output", completed.stdout)
        self.assertIn("model changed", completed.stdout)

    def test_codex_one_command_runs_full_normal_loop(self) -> None:
        completed, repo = self._run("codex")
        self.assertEqual(0, completed.returncode, completed.stderr + completed.stdout)
        result = json.loads(completed.stdout)
        self.assertEqual("PROVEN", result["verdict"])
        run = Path(result["runDir"])
        roles = [json.loads(line)["role"] for line in (run / "invocations.jsonl").read_text().splitlines()]
        self.assertEqual(["planner_deep", "implementer_fast", "reviewer_deep"], roles)
        self.assertIn('return "fixed"', (repo / "src" / "value.py").read_text())

    def test_codex_one_command_runs_real_process_recovery_sequence(self) -> None:
        completed, _ = self._run("codex", recovery=True)
        self.assertEqual(0, completed.returncode, completed.stderr + completed.stdout)
        result = json.loads(completed.stdout)
        run = Path(result["runDir"])
        roles = [json.loads(line)["role"] for line in (run / "invocations.jsonl").read_text().splitlines()]
        self.assertEqual(["planner_deep", "implementer_fast", "implementer_fast", "implementer_recovery", "reviewer_deep"], roles)

    def test_antigravity_one_command_runs_full_external_loop(self) -> None:
        completed, _ = self._run("antigravity")
        self.assertEqual(0, completed.returncode, completed.stderr + completed.stdout)
        result = json.loads(completed.stdout)
        self.assertEqual("PROVEN", result["verdict"])
        trace = json.loads((Path(result["runDir"]) / "model-trace-summary.json").read_text())
        self.assertFalse(trace["routingClaimed"])
        self.assertFalse(trace["routingObserved"])
        self.assertEqual("ROLE_ROUTING_ONLY", trace["capabilityMode"])
        events = [
            json.loads(line)
            for line in (Path(result["runDir"]) / "events.jsonl").read_text(encoding="utf-8").splitlines()
        ]
        started = next(event for event in events if event["type"] == "role.started")
        self.assertEqual("current-session-model", started["data"]["requestedModel"])

    def test_jsonl_output_contains_only_standard_events(self) -> None:
        completed, _ = self._run("codex", output_format="jsonl")
        self.assertEqual(0, completed.returncode, completed.stderr + completed.stdout)
        events = [json.loads(line) for line in completed.stdout.splitlines()]
        self.assertTrue(events)
        self.assertTrue(all(event["schemaVersion"] == "1" for event in events))
        self.assertEqual("run.started", events[0]["type"])
        self.assertEqual("run.completed", events[-1]["type"])
        self.assertNotIn("truthReport", events[-1])

    def test_human_output_contains_live_status_without_final_json_document(self) -> None:
        completed, _ = self._run("codex", output_format="human")
        self.assertEqual(0, completed.returncode, completed.stderr + completed.stdout)
        self.assertIn("[ProofLoop][INIT]", completed.stdout)
        self.assertIn("requested: gpt-5.6", completed.stdout)
        self.assertIn("observed: gpt-5.6", completed.stdout)
        self.assertIn("TRUTH PROVEN", completed.stdout)
        self.assertNotIn('"truthReport":', completed.stdout)

    def test_run_watch_renders_event_bus_panels(self) -> None:
        completed, _ = self._run(
            "codex",
            output_format="human",
            command_name="run",
            watch=True,
            skills_enabled=False,
        )

        self.assertEqual(0, completed.returncode, completed.stderr + completed.stdout)
        self.assertIn("[ProofLoop Watch]", completed.stdout)
        self.assertIn("status: PROVEN", completed.stdout)
        self.assertIn("proof:", completed.stdout)
        self.assertIn("budget:", completed.stdout)

    def test_run_watch_keeps_jsonl_stdout_machine_readable(self) -> None:
        completed, _ = self._run(
            "codex",
            output_format="jsonl",
            command_name="run",
            watch=True,
            skills_enabled=False,
        )

        self.assertEqual(0, completed.returncode, completed.stderr + completed.stdout)
        events = [json.loads(line) for line in completed.stdout.splitlines()]
        self.assertTrue(events)
        self.assertTrue(all(event["schemaVersion"] == "1" for event in events))
        self.assertIn("[ProofLoop Watch]", completed.stderr)
        self.assertIn("status: PROVEN", completed.stderr)


if __name__ == "__main__":
    unittest.main()
