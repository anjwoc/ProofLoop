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
match = re.search(r"exact absolute path before finishing: (.+?)\. Do not write", prompt, re.S)
result_path = Path(match.group(1).strip()) if match else None
repo = Path.cwd()

if "deep planner" in prompt:
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
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(json.dumps(plan), encoding="utf-8")
elif "Role: implementer_fast" in prompt:
    count_path = repo / ".proofloop" / "fake-fast-count"
    count_path.parent.mkdir(parents=True, exist_ok=True)
    count = int(count_path.read_text() or "0") + 1 if count_path.exists() else 1
    count_path.write_text(str(count), encoding="utf-8")
    if os.environ.get("FAKE_PROOFLOOP_RECOVERY") != "1":
        (repo / "src" / "value.py").write_text('def get_value():\n    return "fixed"\n', encoding="utf-8")
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(json.dumps({"status":"DONE","classification":"LOCAL_IMPLEMENTATION"}), encoding="utf-8")
elif "Role: implementer_recovery" in prompt:
    (repo / "src" / "value.py").write_text('def get_value():\n    return "fixed"\n', encoding="utf-8")
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(json.dumps({"status":"DONE","classification":"LOCAL_IMPLEMENTATION"}), encoding="utf-8")
elif "final reviewer" in prompt:
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(json.dumps({"verdict":"APPROVED","simplicityVerdict":"MINIMAL","findings":[],"deletionCandidates":[]}), encoding="utf-8")
else:
    print("unknown role prompt", file=sys.stderr)
    raise SystemExit(3)

if Path(sys.argv[0]).name == "codex":
    print(json.dumps({"type": "thread.started", "model": model}))
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
        command = [sys.executable, "-m", "proofloop_core.cli", "orchestrate", "--host", host, "--repo", str(repo), "--request", "Implement the bounded value behavior", "--strategy", "planned", "--timeout-seconds", "30"]
        if output_format is not None:
            command.extend(["--output-format", output_format, "--verbosity", "info", "--color", "never"])
        completed = subprocess.run(
            command,
            cwd=ROOT, env=env, capture_output=True, text=True, check=False, timeout=90,
        )
        return completed, repo

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
        self.assertTrue(trace["routingObserved"])
        self.assertEqual("EXTERNAL_MODEL_ROUTING", trace["capabilityMode"])

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


if __name__ == "__main__":
    unittest.main()
