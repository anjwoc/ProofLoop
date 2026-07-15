from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class PackageTest(unittest.TestCase):
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

    def test_entry_skill_description_is_trigger_focused(self) -> None:
        text = (ROOT / "skills" / "proofloop" / "SKILL.md").read_text(encoding="utf-8")
        description = next(line for line in text.splitlines() if line.startswith("description:"))
        self.assertTrue(description.startswith("description: Use when "), description)

    def test_package_validator(self) -> None:
        completed = subprocess.run(["python3", "scripts/validate_package.py"], cwd=ROOT, capture_output=True, text=True, check=False)
        self.assertEqual(0, completed.returncode, completed.stderr)

    def test_claude_plugin_is_generated_from_single_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "claude"
            subprocess.run(["python3", "scripts/build_claude_plugin.py", "--output", str(output)], cwd=ROOT, check=True, capture_output=True)
            plugin = output / "plugins" / "proofloop"
            self.assertTrue((output / ".claude-plugin" / "marketplace.json").exists())
            self.assertTrue((plugin / ".claude-plugin" / "plugin.json").exists())
            self.assertTrue((plugin / "skills" / "using-proofloop" / "SKILL.md").exists())
            self.assertTrue((plugin / "agents" / "implementer-fast.md").exists())
            self.assertTrue((plugin / "hooks" / "hooks.json").exists())

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
