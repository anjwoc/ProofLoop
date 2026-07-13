from __future__ import annotations

import io
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from proofloop_core.adapters import ExternalCLIAdapter, RoleInvocation
from proofloop_core.events import EventEmitter
from proofloop_core.hosts import capability, role_only_trace_summary
from proofloop_core.run_state import start_run

ROOT = Path(__file__).resolve().parents[2]


class HostAdapterTest(unittest.TestCase):
    def test_codex_adapter_layout_and_models(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "codex"
            completed = subprocess.run(
                ["python3", "scripts/build_host_adapter.py", "--host", "codex", "--output", str(output)],
                cwd=ROOT, capture_output=True, text=True, check=False,
            )
            self.assertEqual(0, completed.returncode, completed.stderr)
            plugin = output / "plugins" / "proofloop"
            manifest = json.loads((plugin / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
            self.assertEqual("./skills/", manifest["skills"])
            self.assertTrue((plugin / "hooks" / "hooks.json").exists())
            self.assertTrue((output / ".agents" / "plugins" / "marketplace.json").exists())
            self.assertFalse((plugin / "scripts").exists(), "Codex plugin must not duplicate repository-only scripts")
            planner = (output / "agents" / "proofloop_planner_deep.toml").read_text(encoding="utf-8")
            fast = (output / "agents" / "proofloop_implementer_fast.toml").read_text(encoding="utf-8")
            self.assertIn('model = "gpt-5.6"', planner)
            self.assertIn('sandbox_mode = "read-only"', planner)
            self.assertIn('model = "gpt-5.6-terra"', fast)
            self.assertIn('sandbox_mode = "workspace-write"', fast)

    def test_antigravity_adapter_has_recognizable_frontmatter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "antigravity"
            completed = subprocess.run(
                ["python3", "scripts/build_host_adapter.py", "--host", "antigravity", "--output", str(output)],
                cwd=ROOT, capture_output=True, text=True, check=False,
            )
            self.assertEqual(0, completed.returncode, completed.stderr)
            workflow = (output / "workflows" / "proofloop.md").read_text(encoding="utf-8")
            self.assertTrue(workflow.startswith("---\ndescription:"))
            self.assertIn("proofloop-core orchestrate", workflow)
            self.assertNotIn("invoke-role --host antigravity", workflow)
            self.assertTrue((output / "skills" / "using-proofloop" / "SKILL.md").exists())
            entry = (output / "skills" / "proofloop" / "SKILL.md").read_text(encoding="utf-8")
            self.assertIn("--host antigravity", entry)
            self.assertIn("--output-format human", entry)
            self.assertIn("--verbosity info", entry)
            self.assertIn("--color auto", entry)
            self.assertNotIn("invoke-role", entry)
            built_capability = json.loads((output / "capability.json").read_text(encoding="utf-8"))
            self.assertEqual("ROLE_ROUTING_ONLY", built_capability["mode"])
            self.assertFalse(built_capability["crossModelRouting"])

    def test_codex_subagent_hook_records_active_model(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            active = start_run(repo, "test")
            transcript = repo / "subagent.jsonl"
            transcript.write_text('{"type":"thread.started","model":"gpt-5.6-terra"}\n', encoding="utf-8")
            payload = {
                "cwd": str(repo),
                "hook_event_name": "SubagentStop",
                "model": "gpt-5.6-terra",
                "agent_type": "proofloop_implementer_fast",
                "agent_id": "agent-1",
                "agent_transcript_path": str(transcript),
                "turn_id": "turn-1",
                "session_id": "session-1",
            }
            completed = subprocess.run(
                ["python3", "scripts/host_trace_hook.py", "--host", "codex"],
                cwd=ROOT, input=json.dumps(payload), text=True, capture_output=True, check=False,
            )
            self.assertEqual(0, completed.returncode, completed.stderr)
            event_text = (Path(active["runDir"]) / "model-trace.jsonl").read_text(encoding="utf-8")
            self.assertIn("gpt-5.6-terra", event_text)
            self.assertIn("implementer_fast", event_text)

    def test_antigravity_role_only_does_not_fake_model_switch(self) -> None:
        summary = role_only_trace_summary()
        self.assertFalse(summary["routingClaimed"])
        self.assertFalse(summary["routingObserved"])
        self.assertEqual("ROLE_ROUTING_ONLY", summary["capabilityMode"])

    def test_host_capability_table(self) -> None:
        codex = capability("codex")
        antigravity = capability("antigravity")
        self.assertEqual("NATIVE_MODEL_ROUTING", codex["mode"])
        self.assertEqual("gpt-5.6-terra", codex["roles"]["implementer_fast"]["model"])
        self.assertEqual("ROLE_ROUTING_ONLY", antigravity["mode"])
        self.assertNotIn("externalMode", antigravity)
        self.assertNotIn("externalRoles", antigravity)
        with patch(
            "proofloop_core.adapters.probe",
            return_value={"host": "antigravity", "available": True, "mode": "ROLE_ROUTING_ONLY"},
        ):
            self.assertEqual("ROLE_ROUTING_ONLY", ExternalCLIAdapter("antigravity").probe()["mode"])

    def test_codex_installer_uses_plain_mutating_commands_and_direct_copy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            log = root / "calls.log"
            codex = fake_bin / "codex"
            codex.write_text("#!/bin/sh\nprintf '%s\\n' \"$*\" >> \"$PROOFLOOP_FAKE_LOG\"\nexit 0\n", encoding="utf-8")
            codex.chmod(0o755)
            env = dict(os.environ)
            env["HOME"] = str(root / "home")
            env["PATH"] = str(fake_bin) + os.pathsep + env.get("PATH", "")
            env["PROOFLOOP_FAKE_LOG"] = str(log)
            env["PROOFLOOP_HOME"] = str(root / "home" / ".proofloop")
            completed = subprocess.run(
                ["python3", "scripts/install.py", "--host", "codex", "--scope", "user"],
                cwd=ROOT, env=env, capture_output=True, text=True, check=False,
            )
            self.assertEqual(0, completed.returncode, completed.stderr)
            calls = log.read_text(encoding="utf-8")
            self.assertNotIn("--json", calls)
            self.assertIn("plugin marketplace add", calls)
            self.assertIn("plugin add proofloop@proofloop-local", calls)
            self.assertTrue((root / "home" / ".codex" / "agents" / "proofloop_planner_deep.toml").exists())
            self.assertTrue((root / "home" / ".codex" / "plugins" / "proofloop" / ".codex-plugin" / "plugin.json").exists())
            market = json.loads((root / "home" / ".agents" / "plugins" / "marketplace.json").read_text(encoding="utf-8"))
            entry = next(item for item in market["plugins"] if item["name"] == "proofloop")
            self.assertEqual("./.codex/plugins/proofloop", entry["source"]["path"])

    def test_antigravity_user_install_writes_both_skill_locations_and_workflow(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env = dict(os.environ)
            env["HOME"] = str(root / "home")
            env["PROOFLOOP_HOME"] = str(root / "home" / ".proofloop")
            completed = subprocess.run(
                ["python3", "scripts/install.py", "--host", "antigravity", "--scope", "user"],
                cwd=ROOT, env=env, capture_output=True, text=True, check=False,
            )
            self.assertEqual(0, completed.returncode, completed.stderr)
            home = root / "home"
            self.assertTrue((home / ".gemini" / "config" / "skills" / "using-proofloop" / "SKILL.md").exists())
            self.assertTrue((home / ".gemini" / "config" / "skills" / "proofloop" / "SKILL.md").exists())
            self.assertTrue((home / ".gemini" / "antigravity-cli" / "skills" / "using-proofloop" / "SKILL.md").exists())
            self.assertTrue((home / ".gemini" / "antigravity-cli" / "skills" / "proofloop" / "SKILL.md").exists())
            workflow = home / ".gemini" / "config" / "global_workflows" / "proofloop.md"
            self.assertTrue(workflow.exists())
            self.assertTrue(workflow.read_text(encoding="utf-8").startswith("---\ndescription:"))
            self.assertTrue((home / ".proofloop" / "bin" / "proofloop-core").exists())
            result = json.loads(completed.stdout[completed.stdout.index('{\n  "runtime"'):])
            adapter = result["adapters"][0]
            self.assertEqual("ROLE_ROUTING_ONLY", adapter["mode"])
            self.assertFalse(adapter["crossModelRouting"])

    def test_doctor_reports_antigravity_as_role_only(self) -> None:
        completed = subprocess.run(
            ["python3", "scripts/doctor.py"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(0, completed.returncode, completed.stderr)
        antigravity = json.loads(completed.stdout)["hosts"]["antigravity"]
        self.assertEqual("ROLE_ROUTING_ONLY", antigravity["defaultProofLoopMode"])
        self.assertFalse(antigravity["crossModelRouting"])

    def test_antigravity_project_install(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "repo"
            target.mkdir()
            env = dict(os.environ)
            env["PROOFLOOP_HOME"] = str(Path(tmp) / "proofloop-home")
            completed = subprocess.run(
                ["python3", "scripts/install.py", "--host", "antigravity", "--scope", "project", "--target", str(target)],
                cwd=ROOT, env=env, capture_output=True, text=True, check=False,
            )
            self.assertEqual(0, completed.returncode, completed.stderr)
            self.assertTrue((target / ".agents" / "skills" / "using-proofloop" / "SKILL.md").exists())
            self.assertTrue((target / ".agents" / "skills" / "proofloop" / "SKILL.md").exists())
            workflow = target / ".agent" / "workflows" / "proofloop.md"
            self.assertTrue(workflow.exists())
            self.assertTrue(workflow.read_text(encoding="utf-8").startswith("---\ndescription:"))

    def test_antigravity_external_role_invocation_records_requested_model_without_faking_resolution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake = root / "agy"
            fake.write_text("#!/bin/sh\necho completed\nexit 0\n", encoding="utf-8")
            fake.chmod(0o755)
            run_dir = root / "run"
            completed = subprocess.run(
                ["python3", "-m", "proofloop_core.cli", "invoke-role", "--host", "antigravity", "--role", "implementer_fast", "--repo", str(root), "--run-dir", str(run_dir), "--binary", str(fake)],
                cwd=ROOT, capture_output=True, text=True, check=False,
            )
            self.assertEqual(0, completed.returncode, completed.stderr)
            event = json.loads((run_dir / "model-trace.jsonl").read_text(encoding="utf-8").splitlines()[0])
            self.assertEqual("current-session-model", event["requestedModel"])
            self.assertEqual("UNAVAILABLE", event["modelEvidence"])
            self.assertNotIn("--model", event["command"])
            self.assertIn("-p", event["command"])
            summary = json.loads((run_dir / "model-trace-summary.json").read_text(encoding="utf-8"))
            self.assertFalse(summary["routingObserved"])
            self.assertFalse(summary["routingClaimed"])
            self.assertEqual("ROLE_ROUTING_ONLY", summary["capabilityMode"])

    def test_host_runner_streams_structured_model_evidence_to_emitter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake = root / "codex"
            fake.write_text(
                "#!/usr/bin/env python3\n"
                "import json, time\n"
                "print(json.dumps({'type':'thread.started','model':'gpt-5.6-terra'}), flush=True)\n"
                "time.sleep(.1)\n"
                "print(json.dumps({'type':'turn.completed'}), flush=True)\n",
                encoding="utf-8",
            )
            fake.chmod(0o755)
            run_dir = root / "run"
            emitter = EventEmitter("run-1", run_dir, io.StringIO(), "quiet")
            adapter = ExternalCLIAdapter("codex", binary=str(fake))

            result = adapter.invoke(
                RoleInvocation(
                    role="implementer_fast",
                    prompt="Implement the task.",
                    repository=root,
                    run_dir=run_dir,
                    emitter=emitter,
                    phase="EXECUTE",
                    task_id="TASK-001",
                    attempt=1,
                )
            )

            self.assertEqual("PASS", result["verdict"])
            self.assertEqual("gpt-5.6-terra", result["observedModel"])
            self.assertEqual("HOST_OUTPUT", result["modelEvidence"])
            self.assertTrue(result["modelEventEmitted"])
            events = [json.loads(line) for line in (run_dir / "events.jsonl").read_text().splitlines()]
            observed = [event for event in events if event["type"] == "role.model_observed"]
            self.assertEqual(1, len(observed))
            self.assertEqual("TASK-001", observed[0]["taskId"])
            self.assertEqual("gpt-5.6-terra", observed[0]["data"]["observedModel"])
            invocation_dir = Path(result["invocationDir"])
            self.assertIn("thread.started", (invocation_dir / "stdout.log").read_text())

    def test_host_runner_emits_requested_only_when_model_is_unobserved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake = root / "agy"
            fake.write_text("#!/bin/sh\necho completed\n", encoding="utf-8")
            fake.chmod(0o755)
            run_dir = root / "run"
            emitter = EventEmitter("run-1", run_dir, io.StringIO(), "quiet")
            adapter = ExternalCLIAdapter("antigravity", binary=str(fake))

            result = adapter.invoke(
                RoleInvocation(
                    role="implementer_fast",
                    prompt="Implement the task.",
                    repository=root,
                    run_dir=run_dir,
                    emitter=emitter,
                    phase="EXECUTE",
                    task_id="TASK-001",
                    attempt=1,
                )
            )

            self.assertIsNone(result["observedModel"])
            self.assertEqual("current-session-model", result["requestedModel"])
            self.assertEqual("UNAVAILABLE", result["modelEvidence"])
            event = json.loads((run_dir / "events.jsonl").read_text().splitlines()[-1])
            self.assertEqual("role.model_observed", event["type"])
            self.assertIsNone(event["data"]["observedModel"])
            self.assertEqual("UNAVAILABLE", event["data"]["evidenceLevel"])
            invocation = json.loads((Path(result["invocationDir"]) / "invocation.json").read_text(encoding="utf-8"))
            self.assertNotIn("--model", invocation["command"])

    def test_built_entry_skills_call_fixed_orchestrator_host(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for host, output_name, expected in (
                ("codex", "codex", "--host codex"),
                ("antigravity", "antigravity", "--host antigravity"),
                ("claude-code", "claude", "--host claude-code"),
            ):
                output = root / output_name
                completed = subprocess.run(
                    ["python3", "scripts/build_host_adapter.py", "--host", host, "--output", str(output)],
                    cwd=ROOT, capture_output=True, text=True, check=False,
                )
                self.assertEqual(0, completed.returncode, completed.stderr)
                if host == "codex":
                    skill = output / "plugins" / "proofloop" / "skills" / "proofloop" / "SKILL.md"
                elif host == "claude-code":
                    skill = output / "plugins" / "proofloop" / "skills" / "proofloop" / "SKILL.md"
                else:
                    skill = output / "skills" / "proofloop" / "SKILL.md"
                text = skill.read_text(encoding="utf-8")
                self.assertIn("proofloop-core orchestrate", text)
                self.assertIn(expected, text)
                self.assertIn("--output-format human", text)
                self.assertIn("--verbosity info", text)
                self.assertIn("--color auto", text)
                self.assertNotIn("--host <current-host>", text)
                self.assertNotIn("invoke-role", text)

    def test_antigravity_permission_bypass_is_opt_in(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake = root / "agy"
            log = root / "args.json"
            fake.write_text(
                "#!/usr/bin/env python3\nimport json, os, sys\nfrom pathlib import Path\nPath(os.environ['ARGS_LOG']).write_text(json.dumps(sys.argv[1:]))\nprint('done')\n",
                encoding="utf-8",
            )
            fake.chmod(0o755)
            env = dict(os.environ)
            env["ARGS_LOG"] = str(log)
            env.pop("PROOFLOOP_ANTIGRAVITY_BYPASS_PERMISSIONS", None)
            completed = subprocess.run(
                ["python3", "-m", "proofloop_core.cli", "invoke-role", "--host", "antigravity", "--role", "implementer_fast", "--repo", str(root), "--run-dir", str(root / "run"), "--binary", str(fake)],
                cwd=ROOT, env=env, capture_output=True, text=True, check=False,
            )
            self.assertEqual(0, completed.returncode, completed.stderr)
            args = json.loads(log.read_text(encoding="utf-8"))
            self.assertNotIn("--dangerously-skip-permissions", args)
            self.assertNotIn("--model", args)
            env["PROOFLOOP_ANTIGRAVITY_BYPASS_PERMISSIONS"] = "1"
            completed = subprocess.run(
                ["python3", "-m", "proofloop_core.cli", "invoke-role", "--host", "antigravity", "--role", "implementer_fast", "--repo", str(root), "--run-dir", str(root / "run2"), "--binary", str(fake)],
                cwd=ROOT, env=env, capture_output=True, text=True, check=False,
            )
            self.assertEqual(0, completed.returncode, completed.stderr)
            args = json.loads(log.read_text(encoding="utf-8"))
            self.assertIn("--dangerously-skip-permissions", args)
            self.assertNotIn("--model", args)


if __name__ == "__main__":
    unittest.main()
