from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class PackageTest(unittest.TestCase):
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
                "#!/bin/sh\nprintf '%s\\n' \"$*\" >> \"$PROOFLOOP_FAKE_LOG\"\nexit 0\n",
                encoding="utf-8",
            )
            fake.chmod(0o755)
            env = dict(__import__("os").environ)
            env["PATH"] = str(fake_dir) + __import__("os").pathsep + env.get("PATH", "")
            env["PROOFLOOP_FAKE_LOG"] = str(log)
            env["HOME"] = str(fake_dir / "home")
            env["PROOFLOOP_HOME"] = str(fake_dir / "home" / ".proofloop")
            completed = subprocess.run(["python3", "scripts/install.py", "--host", "claude-code", "--scope", "user"], cwd=ROOT, env=env, capture_output=True, text=True, check=False)
            self.assertEqual(0, completed.returncode, completed.stderr)
            calls = log.read_text(encoding="utf-8")
            self.assertNotIn("--json", calls)
            self.assertIn("plugin marketplace add", calls)
            self.assertIn("plugin install proofloop@proofloop-local", calls)


if __name__ == "__main__":
    unittest.main()
