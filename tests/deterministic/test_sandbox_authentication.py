from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

from proofloop_core.runtimes.xdg_sandbox_runner import XdgSandboxRunner


class SandboxAuthenticationTest(unittest.TestCase):
    def test_credentials_are_available_without_synthetic_keychain_links(self) -> None:
        cases = {
            "codex": ((".codex", "auth.json"), ("config", "codex", "auth.json")),
            "claude-code": ((".claude", ".credentials.json"), ("config", "claude", ".credentials.json")),
            "agy": ((".gemini", "antigravity-cli", "antigravity-oauth-token"), ("home", ".gemini", "antigravity-cli", "antigravity-oauth-token")),
            "antigravity": ((".gemini", "oauth_creds.json"), ("home", ".gemini", "oauth_creds.json")),
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_home = root / "host-home"
            source_home.mkdir()
            keychains = source_home / "Library" / "Keychains"
            keychains.mkdir(parents=True)
            for host, (source_parts, target_parts) in cases.items():
                with self.subTest(host=host):
                    source = source_home.joinpath(*source_parts)
                    source.parent.mkdir(parents=True, exist_ok=True)
                    source.write_text("test credential", encoding="utf-8")
                    invocation = root / host / "invocation"
                    output = invocation / "stdout.log"
                    error = invocation / "stderr.log"
                    result = XdgSandboxRunner(host=host).run(
                        [
                            sys.executable,
                            "-c",
                            (
                                "import os\n"
                                "from pathlib import Path\n"
                                "Path(os.environ['XDG_STATE_HOME']).joinpath('role-state').write_text('sandbox')\n"
                                "print(Path.home())\n"
                            ),
                        ],
                        cwd=root,
                        stdout_path=output,
                        stderr_path=error,
                        env={"HOME": str(source_home)},
                        timeout_seconds=10,
                    )

                    self.assertEqual(0, result.exit_code)
                    target = invocation / "sandbox" / Path(*target_parts)
                    state = invocation / "sandbox" / "state" / "role-state"
                    self.assertTrue(state.is_file())
                    keychain_target = invocation / "sandbox" / "home" / "Library" / "Keychains"
                    self.assertFalse(keychain_target.exists())
                    if sys.platform == "darwin" and host in {"agy", "antigravity"}:
                        self.assertEqual(
                            str(source_home),
                            output.read_text(encoding="utf-8").strip(),
                        )
                        self.assertFalse(target.exists())
                    else:
                        self.assertTrue(target.is_symlink())
                        self.assertEqual(source.resolve(), target.resolve())

    def test_agy_reuses_native_home_on_macos_instead_of_linking_credentials(self) -> None:
        required = (
            "oauth_creds.json",
            "google_accounts.json",
            "antigravity-cli/antigravity-oauth-token",
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_home = root / "host-home"
            for relative in required:
                source = source_home / ".gemini" / relative
                source.parent.mkdir(parents=True, exist_ok=True)
                source.write_text("test credential", encoding="utf-8")
            invocation = root / "invocation"
            result = XdgSandboxRunner(host="agy").run(
                [sys.executable, "-c", "from pathlib import Path; print(Path.home())"],
                cwd=root,
                stdout_path=invocation / "stdout.log",
                stderr_path=invocation / "stderr.log",
                env={"HOME": str(source_home)},
                timeout_seconds=10,
            )

            self.assertEqual(0, result.exit_code)
            if sys.platform == "darwin":
                self.assertEqual(
                    str(source_home),
                    (invocation / "stdout.log").read_text(encoding="utf-8").strip(),
                )
                self.assertFalse(
                    (invocation / "sandbox" / "home" / "Library" / "Keychains").exists()
                )
            else:
                for relative in required:
                    target = invocation / "sandbox" / "home" / ".gemini" / relative
                    self.assertTrue(target.is_symlink(), relative)
                    self.assertEqual(
                        (source_home / ".gemini" / relative).resolve(),
                        target.resolve(),
                    )


if __name__ == "__main__":
    unittest.main()
