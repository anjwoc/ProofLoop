from __future__ import annotations

import io
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from proofloop_core.runtimes.adapters import ExternalCLIAdapter, RoleInvocation
from proofloop_core.context.events import EventEmitter
from proofloop_core.runtimes.host_runner import invoke_role
from proofloop_core.runtimes.hosts import capability, role_only_trace_summary
from proofloop_core.runtimes.runtime import ACCOUNT_DEFAULT_MODEL
from proofloop_core.contracts.run_state import start_run

ROOT = Path(__file__).resolve().parents[2]


class HostAdapterTest(unittest.TestCase):
    def test_external_adapter_materializes_role_artifact_in_parent_process(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake = root / "codex"
            capture = root / "prompt.txt"
            fake.write_text(
                "#!/usr/bin/env python3\n"
                "import json, os, sys\n"
                "from pathlib import Path\n"
                "Path(os.environ['PROMPT_CAPTURE']).write_text(sys.argv[-1])\n"
                "print(json.dumps({'type':'thread.started','thread_id':'t','model':'gpt-test'}))\n"
                "print('PROOFLOOP_RESULT_BEGIN')\n"
                "print(json.dumps({'verdict':'READY','tasks':[]}))\n"
                "print('PROOFLOOP_RESULT_END')\n",
                encoding="utf-8",
            )
            fake.chmod(0o755)
            result_path = root / "run" / "plan.json"
            adapter = ExternalCLIAdapter("codex", binary=str(fake))

            with patch.dict(os.environ, {"PROMPT_CAPTURE": str(capture)}):
                result = adapter.invoke(
                    RoleInvocation(
                        role="planner_deep",
                        prompt=f"Write JSON to {result_path}",
                        repository=root,
                        run_dir=root / "run",
                        result_path=result_path,
                    )
                )

            self.assertEqual("PASS", result["verdict"])
            self.assertEqual({"verdict": "READY", "tasks": []}, json.loads(result_path.read_text()))
            self.assertNotIn(str(result_path), capture.read_text(encoding="utf-8"))
            self.assertEqual("PARENT_PROCESS", result["artifactOwner"])
            invocation = json.loads((Path(result["invocationDir"]) / "invocation.json").read_text())
            sandbox_index = invocation["command"].index("--sandbox")
            self.assertEqual("read-only", invocation["command"][sandbox_index + 1])

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
            self.assertEqual(
                ["proofloop"],
                sorted(path.parent.name for path in (plugin / "skills").glob("*/SKILL.md")),
            )
            self.assertTrue((plugin / "proofloop_protocols" / "proofloop-design" / "SKILL.md").exists())
            planner = (output / "agents" / "proofloop_planner_deep.toml").read_text(encoding="utf-8")
            fast = (output / "agents" / "proofloop_implementer_fast.toml").read_text(encoding="utf-8")
            self.assertIn('model = "gpt-5.6"', planner)
            self.assertIn('sandbox_mode = "read-only"', planner)
            self.assertIn('model = "gpt-5.6-terra"', fast)
            self.assertIn('sandbox_mode = "workspace-write"', fast)

    def test_entry_skill_requires_an_absolute_repository_root_before_launch(self) -> None:
        entry = (ROOT / "skills" / "proofloop" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("git rev-parse --show-toplevel", entry)
        self.assertIn('cd "$repo_root"', entry)
        self.assertIn('--repo "$repo_root"', entry)
        self.assertIn('--request-file "$request_file"', entry)

    def test_entry_skill_relays_live_parent_events_in_every_host_conversation(self) -> None:
        entry = (ROOT / "skills" / "proofloop" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("nohup", entry)
        self.assertIn('relay_dir="$repo_root/.proofloop/relay/', entry)
        self.assertIn("PROOFLOOP_RELAY_ACTIVE", entry)
        self.assertIn("PROOFLOOP_RELAY_FINISHED", entry)
        self.assertIn("Relay every new `[ProofLoop]` line", entry)
        self.assertIn("expected-output-report.json", entry)

    def test_claude_adapter_layout_contains_the_specialized_entry_skill(self) -> None:
        """Exercise the real Claude package builder, not a hand-built fixture."""
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "claude"
            completed = subprocess.run(
                ["python3", "scripts/build_host_adapter.py", "--host", "claude-code", "--output", str(output)],
                cwd=ROOT, capture_output=True, text=True, check=False,
            )
            self.assertEqual(0, completed.returncode, completed.stderr)
            plugin = output / "plugins" / "proofloop"
            manifest = json.loads((plugin / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
            self.assertEqual("proofloop", manifest["name"])
            entry_skill = plugin / "skills" / "proofloop" / "SKILL.md"
            self.assertTrue(entry_skill.is_file())
            self.assertIn("--host claude-code", entry_skill.read_text(encoding="utf-8"))
            self.assertTrue((plugin / "installed-skills.json").is_file())

    def test_antigravity_adapter_has_recognizable_frontmatter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "antigravity"
            completed = subprocess.run(
                ["python3", "scripts/build_host_adapter.py", "--host", "antigravity", "--output", str(output)],
                cwd=ROOT, capture_output=True, text=True, check=False,
            )
            self.assertEqual(0, completed.returncode, completed.stderr)
            workflow = (output / "workflows" / "proofloop.md").read_text(encoding="utf-8")
            self.assertTrue(workflow.startswith("---\nname: proofloop\ndescription:"))
            self.assertIn("proofloop-core\" run", workflow)
            self.assertIn("--mode adaptive", workflow)
            self.assertNotIn("invoke-role --host antigravity", workflow)
            self.assertIn("nohup", workflow)
            self.assertIn("< /dev/null", workflow)
            self.assertIn("output.log", workflow)
            self.assertIn("pid", workflow)
            self.assertIn("NEXT_LINE", workflow)
            self.assertIn("kill -0", workflow)
            self.assertIn("Relay every new `[ProofLoop]` line", workflow)
            self.assertIn("truth-report.json", workflow)
            self.assertNotIn("Run exactly one bootstrap command", workflow)
            self.assertEqual(
                ["proofloop"],
                sorted(path.parent.name for path in (output / "skills").glob("*/SKILL.md")),
            )
            entry = (output / "skills" / "proofloop" / "SKILL.md").read_text(encoding="utf-8")
            self.assertIn("--host antigravity", entry)
            self.assertIn("--output-format human", entry)
            self.assertIn("--verbosity info", entry)
            self.assertIn("--color never", entry)
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
            home = root / "home"
            fake_bin = root / "bin"
            fake_bin.mkdir()
            log = root / "calls.log"
            codex = fake_bin / "codex"
            codex.write_text("#!/bin/sh\nprintf '%s\\n' \"$*\" >> \"$PROOFLOOP_FAKE_LOG\"\nexit 0\n", encoding="utf-8")
            codex.chmod(0o755)
            env = dict(os.environ)
            env["HOME"] = str(home)
            env["PATH"] = str(fake_bin) + os.pathsep + env.get("PATH", "")
            env["PROOFLOOP_FAKE_LOG"] = str(log)
            env["PROOFLOOP_HOME"] = str(home / ".proofloop")
            agents = home / ".codex" / "agents"
            agents.mkdir(parents=True)
            (agents / "proofloop_stale.toml").write_text("stale", encoding="utf-8")
            (agents / "user_agent.toml").write_text("keep", encoding="utf-8")
            stale_plugin = home / ".codex" / "plugins" / "proofloop"
            stale_plugin.mkdir(parents=True)
            (stale_plugin / "stale.txt").write_text("stale", encoding="utf-8")
            runtime = home / ".proofloop" / "runtime"
            runtime.mkdir(parents=True)
            (runtime / "stale.py").write_text("stale", encoding="utf-8")
            command = ["python3", "scripts/install.py", "--host", "codex", "--scope", "user", "--without-tokscale"]
            for _ in range(2):
                completed = subprocess.run(
                    command,
                    cwd=ROOT, env=env, capture_output=True, text=True, check=False,
                )
                self.assertEqual(0, completed.returncode, completed.stderr)
            call_lines = log.read_text(encoding="utf-8").splitlines()
            calls = "\n".join(call_lines)
            self.assertNotIn("--json", calls)
            self.assertEqual("plugin remove proofloop@proofloop-local", call_lines[0])
            self.assertEqual("plugin marketplace remove proofloop-local", call_lines[1])
            self.assertIn("plugin marketplace add", calls)
            self.assertIn("plugin add proofloop@proofloop-local", calls)
            self.assertFalse((agents / "proofloop_stale.toml").exists())
            self.assertEqual("keep", (agents / "user_agent.toml").read_text(encoding="utf-8"))
            self.assertFalse((stale_plugin / "stale.txt").exists())
            self.assertFalse((runtime / "stale.py").exists())
            self.assertTrue((agents / "proofloop_planner_deep.toml").exists())
            self.assertTrue((stale_plugin / ".codex-plugin" / "plugin.json").exists())
            market = json.loads((home / ".agents" / "plugins" / "marketplace.json").read_text(encoding="utf-8"))
            entry = next(item for item in market["plugins"] if item["name"] == "proofloop")
            self.assertEqual("./.codex/plugins/proofloop", entry["source"]["path"])
            self.assertEqual(1, sum(item["name"] == "proofloop" for item in market["plugins"]))

    def test_antigravity_user_install_writes_both_skill_locations_and_workflow(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env = dict(os.environ)
            env["HOME"] = str(root / "home")
            env["PROOFLOOP_HOME"] = str(root / "home" / ".proofloop")
            home = root / "home"
            skills_root = home / ".gemini" / "config" / "skills"
            (skills_root / "proofloop-obsolete").mkdir(parents=True)
            (skills_root / "proofloop-obsolete" / "stale.txt").write_text("stale", encoding="utf-8")
            (skills_root / "user-skill").mkdir()
            (skills_root / "user-skill" / "keep.txt").write_text("keep", encoding="utf-8")
            command = ["python3", "scripts/install.py", "--host", "antigravity", "--scope", "user", "--without-tokscale"]
            for _ in range(2):
                completed = subprocess.run(
                    command,
                    cwd=ROOT, env=env, capture_output=True, text=True, check=False,
                )
                self.assertEqual(0, completed.returncode, completed.stderr)
            self.assertFalse((skills_root / "proofloop-obsolete").exists())
            self.assertEqual("keep", (skills_root / "user-skill" / "keep.txt").read_text(encoding="utf-8"))
            self.assertTrue((home / ".gemini" / "config" / "skills" / "proofloop" / "SKILL.md").exists())
            self.assertTrue((home / ".gemini" / "antigravity-cli" / "skills" / "proofloop" / "SKILL.md").exists())
            self.assertEqual(
                ["proofloop"],
                sorted(
                    path.name
                    for path in skills_root.iterdir()
                    if path.is_dir() and (path.name.startswith("proofloop") or path.name == "using-proofloop")
                ),
            )
            workflow = home / ".gemini" / "config" / "global_workflows" / "proofloop.md"
            self.assertTrue(workflow.exists())
            self.assertTrue(workflow.read_text(encoding="utf-8").startswith("---\nname: proofloop\ndescription:"))
            self.assertIn("proofloop-core\" run", workflow.read_text(encoding="utf-8"))
            self.assertIn("--mode adaptive", workflow.read_text(encoding="utf-8"))
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

    def test_doctor_resolves_active_claude_plugin_from_install_registry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            install_root = home / ".claude" / "plugins" / "cache" / "proofloop-local" / "proofloop" / "0.4.0-alpha"
            entry = install_root / "skills" / "proofloop" / "SKILL.md"
            entry.parent.mkdir(parents=True)
            entry.write_text("---\nname: proofloop\n---\n", encoding="utf-8")
            registry = home / ".claude" / "plugins" / "installed_plugins.json"
            registry.parent.mkdir(parents=True, exist_ok=True)
            registry.write_text(
                json.dumps(
                    {
                        "version": 2,
                        "plugins": {
                            "proofloop@proofloop-local": [
                                {"scope": "user", "installPath": str(install_root), "version": "0.4.0-alpha"}
                            ]
                        },
                    }
                ),
                encoding="utf-8",
            )
            env = dict(os.environ)
            env["HOME"] = str(home)
            env["PROOFLOOP_HOME"] = str(home / ".proofloop")

            completed = subprocess.run(
                ["python3", "scripts/doctor.py"],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(0, completed.returncode, completed.stderr)
            reported = json.loads(completed.stdout)["hosts"]["claude-code"]["entrySkill"]
            self.assertEqual(str(entry), reported["path"])
            self.assertTrue(reported["exists"])

    def test_antigravity_project_install(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "repo"
            target.mkdir()
            env = dict(os.environ)
            env["PROOFLOOP_HOME"] = str(Path(tmp) / "proofloop-home")
            completed = subprocess.run(
                ["python3", "scripts/install.py", "--host", "antigravity", "--scope", "project", "--target", str(target), "--without-tokscale"],
                cwd=ROOT, env=env, capture_output=True, text=True, check=False,
            )
            self.assertEqual(0, completed.returncode, completed.stderr)
            self.assertTrue((target / ".agents" / "skills" / "proofloop" / "SKILL.md").exists())
            self.assertEqual(
                ["proofloop"],
                sorted(path.name for path in (target / ".agents" / "skills").iterdir() if path.is_dir()),
            )
            workflow = target / ".agent" / "workflows" / "proofloop.md"
            self.assertTrue(workflow.exists())
            self.assertTrue(workflow.read_text(encoding="utf-8").startswith("---\nname: proofloop\ndescription:"))

    def test_antigravity_external_role_invocation_records_requested_model_without_faking_resolution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake = root / "agy"
            capture = root / "capture.json"
            fake.write_text(
                "#!/usr/bin/env python3\n"
                "import json, os, sys\n"
                "from pathlib import Path\n"
                "Path(os.environ['AGY_CAPTURE']).write_text(json.dumps({\n"
                "    'args': sys.argv[1:],\n"
                "}))\n"
                "print('completed', flush=True)\n",
                encoding="utf-8",
            )
            fake.chmod(0o755)
            run_dir = root / "run"
            env = dict(os.environ)
            env["AGY_CAPTURE"] = str(capture)
            completed = subprocess.run(
                ["python3", "-m", "proofloop_core.cli", "invoke-role", "--host", "antigravity", "--role", "implementer_fast", "--repo", str(root), "--run-dir", str(run_dir), "--binary", str(fake)],
                cwd=ROOT, env=env, capture_output=True, text=True, check=False,
            )
            self.assertEqual(0, completed.returncode, completed.stderr)
            captured = json.loads(capture.read_text(encoding="utf-8"))
            prompt_index = captured["args"].index("-p")
            prompt_value = captured["args"][prompt_index + 1]
            self.assertTrue(len(prompt_value) > 0, "prompt must be non-empty")
            self.assertIn("implementer_fast", prompt_value)
            self.assertNotIn("--model", captured["args"])
            self.assertNotIn("--prompt", captured["args"])
            event = json.loads((run_dir / "model-trace.jsonl").read_text(encoding="utf-8").splitlines()[0])
            self.assertEqual("current-session-model", event["requestedModel"])
            self.assertEqual("UNAVAILABLE", event["modelEvidence"])
            self.assertNotIn("--model", event["command"])
            self.assertIn("-p", event["command"])
            summary = json.loads((run_dir / "model-trace-summary.json").read_text(encoding="utf-8"))
            self.assertFalse(summary["routingObserved"])
            self.assertFalse(summary["routingClaimed"])
            self.assertEqual("ROLE_ROUTING_ONLY", summary["capabilityMode"])

    def test_codex_account_default_omits_the_unsupported_model_flag(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake = root / "codex"
            capture = root / "args.json"
            fake.write_text(
                "#!/usr/bin/env python3\n"
                "import json, os, sys\n"
                "from pathlib import Path\n"
                "Path(os.environ['CODEX_ARGS']).write_text(json.dumps(sys.argv[1:]))\n",
                encoding="utf-8",
            )
            fake.chmod(0o755)
            with patch.dict(os.environ, {"CODEX_ARGS": str(capture)}):
                invoke_role(
                    "codex",
                    "implementer_fast",
                    root,
                    root / "run",
                    binary=str(fake),
                    model_override=ACCOUNT_DEFAULT_MODEL,
                )
            self.assertNotIn("--model", json.loads(capture.read_text(encoding="utf-8")))

    def test_antigravity_role_emits_output_and_heartbeat_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake = root / "agy"
            fake.write_text(
                "#!/usr/bin/env python3\n"
                "import sys, time\n"
                "sys.stdin.read()\n"
                "print('working on plan', flush=True)\n"
                "time.sleep(.15)\n",
                encoding="utf-8",
            )
            fake.chmod(0o755)
            run_dir = root / "run"
            emitter = EventEmitter("run-1", run_dir, io.StringIO(), "quiet")

            result = invoke_role(
                "antigravity",
                "planner_deep",
                root,
                run_dir,
                prompt="Plan the requested change.",
                binary=str(fake),
                emitter=emitter,
                phase="PLAN",
                heartbeat_interval_seconds=0.03,
            )

            self.assertEqual("PASS", result["verdict"])
            events = [json.loads(line) for line in (run_dir / "events.jsonl").read_text().splitlines()]
            output = next(event for event in events if event["type"] == "role.output")
            self.assertEqual("stdout", output["data"]["stream"])
            self.assertEqual("working on plan", output["data"]["text"])
            progress = [event for event in events if event["type"] == "role.progress"]
            self.assertGreaterEqual(len(progress), 2)
            self.assertGreater(progress[0]["data"]["processId"], 0)
            self.assertGreater(progress[0]["data"]["elapsedSeconds"], 0)

    def test_host_runner_streams_structured_model_evidence_to_emitter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake = root / "codex"
            fake.write_text(
                "#!/usr/bin/env python3\n"
                "import json, time\n"
                "print(json.dumps({'type':'thread.started','thread_id':'thread-1','model':'gpt-5.6-terra'}), flush=True)\n"
                "time.sleep(.1)\n"
                "print(json.dumps({'type':'turn.completed','thread_id':'thread-1','usage':{'input_tokens':100,'output_tokens':25}}), flush=True)\n",
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
            self.assertEqual("thread-1", result["sessionId"])
            self.assertEqual(125, result["usage"]["rawTotal"])
            self.assertTrue(result["modelEventEmitted"])
            events = [json.loads(line) for line in (run_dir / "events.jsonl").read_text().splitlines()]
            observed = [event for event in events if event["type"] == "role.model_observed"]
            self.assertEqual(1, len(observed))
            self.assertEqual("TASK-001", observed[0]["taskId"])
            self.assertEqual("gpt-5.6-terra", observed[0]["data"]["observedModel"])
            invocation_dir = Path(result["invocationDir"])
            self.assertIn("thread.started", (invocation_dir / "stdout.log").read_text())
            usage_summary = json.loads((run_dir / "usage" / "usage-summary.json").read_text())
            self.assertEqual(125, usage_summary["totals"]["rawTotal"])
            headless = run_dir / "usage" / "tokscale-headless" / "codex" / "01-codex-implementer_fast.jsonl"
            self.assertIn("turn.completed", headless.read_text(encoding="utf-8"))

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

    def test_agy_read_only_role_uses_plan_approval_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake = root / "agy"
            capture = root / "args.json"
            fake.write_text(
                "#!/usr/bin/env python3\n"
                "import json, os, sys\n"
                "from pathlib import Path\n"
                "Path(os.environ['GEMINI_ARGS']).write_text(json.dumps(sys.argv[1:]))\n",
                encoding="utf-8",
            )
            fake.chmod(0o755)
            with patch.dict(os.environ, {"GEMINI_ARGS": str(capture)}):
                result = invoke_role(
                    "agy",
                    "explorer_fast",
                    root,
                    root / "run",
                    prompt="Inspect only.",
                    binary=str(fake),
                    access_mode="read-only",
                )

            self.assertEqual("PASS", result["verdict"])
            args = json.loads(capture.read_text(encoding="utf-8"))
            approval_index = args.index("--approval-mode")
            self.assertEqual("plan", args[approval_index + 1])
            self.assertIn("stream-json", args)

    def test_claude_read_only_role_is_noninteractive_and_denies_write_tools(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake = root / "claude"
            capture = root / "args.json"
            fake.write_text(
                "#!/usr/bin/env python3\n"
                "import json, os, sys\n"
                "from pathlib import Path\n"
                "Path(os.environ['CLAUDE_ARGS']).write_text(json.dumps(sys.argv[1:]))\n",
                encoding="utf-8",
            )
            fake.chmod(0o755)
            with patch.dict(os.environ, {"CLAUDE_ARGS": str(capture)}):
                result = invoke_role(
                    "claude-code",
                    "explorer_fast",
                    root,
                    root / "run",
                    prompt="Inspect only.",
                    binary=str(fake),
                    access_mode="read-only",
                )

            self.assertEqual("PASS", result["verdict"])
            args = json.loads(capture.read_text(encoding="utf-8"))
            permission_index = args.index("--permission-mode")
            self.assertEqual("dontAsk", args[permission_index + 1])
            denied_index = args.index("--disallowedTools")
            self.assertEqual("Edit,Write,NotebookEdit", args[denied_index + 1])
            strict_index = args.index("--strict-mcp-config")
            self.assertEqual("--mcp-config", args[strict_index + 1])
            config = Path(args[strict_index + 2])
            self.assertEqual({"mcpServers": {}}, json.loads(config.read_text(encoding="utf-8")))
            self.assertNotIn("plan", args)

    def test_host_runner_redacts_private_reasoning_from_persisted_host_logs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake = root / "claude"
            fake.write_text(
                "#!/usr/bin/env python3\n"
                "import json\n"
                "print(json.dumps({'type':'assistant','message':{'content':[{'type':'thinking','thinking':'private chain','signature':'opaque'},{'type':'text','text':'visible update'}]}}))\n",
                encoding="utf-8",
            )
            fake.chmod(0o755)
            result = invoke_role(
                "claude-code",
                "explorer_fast",
                root,
                root / "run",
                prompt="Inspect only.",
                binary=str(fake),
                access_mode="read-only",
            )

            transcript = (Path(result["invocationDir"]) / "stdout.log").read_text(encoding="utf-8")
            self.assertNotIn("private chain", transcript)
            self.assertNotIn("opaque", transcript)
            self.assertIn('"redacted":true', transcript)
            self.assertIn("visible update", transcript)

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
                self.assertIn("proofloop-core run", text)
                self.assertIn("--mode <adaptive-or-goal-or-audit>", text)
                self.assertIn(expected, text)
                self.assertIn("--output-format human", text)
                self.assertIn("--verbosity info", text)
                self.assertIn("--color never", text)
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
