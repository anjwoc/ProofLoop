from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
import json


ROOT = Path(__file__).resolve().parents[2]


class PackageTest(unittest.TestCase):
    def test_adapter_cleanup_retries_transient_directory_not_empty_error(self) -> None:
        import shutil
        from unittest.mock import patch
        from scripts import build_host_adapter

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "adapter"
            target.mkdir()
            (target / "file").write_text("x")
            real_rmtree = shutil.rmtree
            calls = 0

            def flaky_rmtree(path: Path) -> None:
                nonlocal calls
                calls += 1
                if calls == 1:
                    raise OSError(66, "Directory not empty")
                real_rmtree(path)

            with patch.object(build_host_adapter.shutil, "rmtree", side_effect=flaky_rmtree):
                build_host_adapter.remove_tree(target)

            self.assertEqual(2, calls)
            self.assertFalse(target.exists())

    def test_public_skill_surface_contains_only_proofloop(self) -> None:
        public_skills = sorted(
            path.parent.name
            for path in (ROOT / "skills").glob("*/SKILL.md")
        )
        self.assertEqual(["proofloop"], public_skills)

    def test_internal_process_protocols_are_not_public_skills(self) -> None:
        protocol_root = ROOT / "proofloop_protocols"
        protocols = sorted(path.parent.name for path in protocol_root.glob("*/SKILL.md"))
        self.assertEqual(
            [
                "proofloop-debug",
                "proofloop-design",
                "proofloop-implement",
                "proofloop-intent",
                "proofloop-plan",
                "proofloop-review",
                "proofloop-verify",
            ],
            protocols,
        )
        self.assertTrue(all((protocol_root / name / "proofloop.skill.json").is_file() for name in protocols))

    def test_builtin_domain_packs_are_generic_workflows_not_framework_skills(self) -> None:
        domain_root = ROOT / "proofloop_domain_packs"
        packs = sorted(path.parent.name for path in domain_root.glob("*/SKILL.md"))
        self.assertEqual(
            ["backend-development", "code-review", "devops-delivery", "frontend-development", "test-engineering"],
            packs,
        )
        self.assertNotIn("django", packs)
        self.assertTrue((domain_root / "backend-development" / "references" / "django-5.md").is_file())

    def test_root_installer_defaults_to_all_hosts_and_forwards_options(self) -> None:
        installer = ROOT / "install.sh"
        self.assertTrue(installer.exists())
        self.assertTrue(installer.stat().st_mode & 0o111)
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(__import__("os").environ)
            env["HOME"] = tmp
            env["PROOFLOOP_HOME"] = str(Path(tmp) / ".proofloop")
            env["PYTHON"] = sys.executable
            completed = subprocess.run(
                [str(installer), "--dry-run"],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(0, completed.returncode, completed.stderr)
        payload = completed.stdout[completed.stdout.index('{\n  "runtime"'):]
        hosts = [item["host"] for item in __import__("json").loads(payload)["adapters"]]
        self.assertEqual(["claude-code", "codex", "antigravity"], hosts)

    def test_python_compatibility_entry_and_npm_scripts_are_available(self) -> None:
        package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
        self.assertIn("proofloop:install", package["scripts"])
        self.assertIn("proofloop:build", package["scripts"])
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(__import__("os").environ)
            env["HOME"] = tmp
            env["PROOFLOOP_HOME"] = str(Path(tmp) / ".proofloop")
            completed = subprocess.run(
                ["python3", "script/install.py", "--host", "antigravity", "--dry-run", "--without-tokscale"],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(0, completed.returncode, completed.stderr)

    def test_entry_skill_description_is_trigger_focused(self) -> None:
        text = (ROOT / "skills" / "proofloop" / "SKILL.md").read_text(encoding="utf-8")
        description = next(line for line in text.splitlines() if line.startswith("description:"))
        self.assertTrue(description.startswith("description: Use when "), description)

    def test_package_validator(self) -> None:
        completed = subprocess.run(["python3", "scripts/validate_package.py"], cwd=ROOT, capture_output=True, text=True, check=False)
        self.assertEqual(0, completed.returncode, completed.stderr)



    def test_runtime_install_contains_skill_contracts_and_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(__import__("os").environ)
            env["HOME"] = tmp
            env["PROOFLOOP_HOME"] = str(Path(tmp) / ".proofloop")
            completed = subprocess.run(
                ["python3", "scripts/install.py", "--host", "codex", "--build-only", "--without-tokscale"],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(0, completed.returncode, completed.stderr)
            runtime = Path(tmp) / ".proofloop" / "runtime"
            self.assertEqual(
                ["proofloop"],
                sorted(path.parent.name for path in (runtime / "skills").glob("*/SKILL.md")),
            )
            self.assertTrue((runtime / "proofloop_protocols" / "proofloop-verify" / "proofloop.skill.json").exists())
            self.assertTrue((runtime / "proofloop_domain_packs" / "backend-development" / "proofloop.skill.json").exists())
            self.assertTrue((runtime / "benchmarks" / "swe-skills-bench" / "catalog.json").exists())
            manifest = json.loads((Path(tmp) / ".proofloop" / "install-manifest.json").read_text())
            self.assertEqual(12, len(manifest["skills"]))

    def test_installer_uses_plain_cli_arguments(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fake_dir = Path(tmp)
            log = fake_dir / "calls.log"
            fake = fake_dir / "claude"
            fake.write_text(
                "#!/bin/sh\n"
                "printf '%s\\n' \"$*\" >> \"$PROOFLOOP_FAKE_LOG\"\n"
                "case \"$*\" in\n"
                "  *'plugin uninstall'*|*'marketplace remove'*) exit 1 ;;\n"
                "esac\n"
                "exit 0\n",
                encoding="utf-8",
            )
            fake.chmod(0o755)
            env = dict(__import__("os").environ)
            env["PATH"] = str(fake_dir) + __import__("os").pathsep + env.get("PATH", "")
            env["PROOFLOOP_FAKE_LOG"] = str(log)
            env["HOME"] = str(fake_dir / "home")
            env["PROOFLOOP_HOME"] = str(fake_dir / "home" / ".proofloop")
            command = [
                "python3",
                "scripts/install.py",
                "--host",
                "claude-code",
                "--scope",
                "user",
                "--without-tokscale",
            ]
            for _ in range(2):
                completed = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True, check=False)
                self.assertEqual(0, completed.returncode, completed.stderr)
            call_lines = log.read_text(encoding="utf-8").splitlines()
            calls = "\n".join(call_lines)
            self.assertNotIn("--json", calls)
            self.assertEqual("plugin validate " + str(ROOT / "dist" / "claude") + " --strict", call_lines[0])
            self.assertEqual("plugin uninstall proofloop@proofloop-local --scope user --yes", call_lines[1])
            self.assertEqual("plugin marketplace remove proofloop-local --scope user", call_lines[2])
            self.assertIn("plugin marketplace add", calls)
            self.assertIn("plugin install proofloop@proofloop-local", calls)


if __name__ == "__main__":
    unittest.main()
