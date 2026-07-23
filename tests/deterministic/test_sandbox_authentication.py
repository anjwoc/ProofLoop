from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

from proofloop_core.runtimes.xdg_sandbox_runner import XdgSandboxRunner


class SandboxAuthenticationTest(unittest.TestCase):
    def test_host_credentials_are_linked_without_reusing_host_home(self) -> None:
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
                            "from pathlib import Path; Path.home().joinpath('.role-state').write_text('sandbox')",
                        ],
                        cwd=root,
                        stdout_path=output,
                        stderr_path=error,
                        env={"HOME": str(source_home)},
                        timeout_seconds=10,
                    )

                    self.assertEqual(0, result.exit_code)
                    target = invocation / "sandbox" / Path(*target_parts)
                    self.assertTrue(target.is_symlink())
                    self.assertEqual(source.resolve(), target.resolve())
                    self.assertTrue((invocation / "sandbox" / "home" / ".role-state").is_file())
                    self.assertFalse((source_home / ".role-state").exists())
                    keychain_target = invocation / "sandbox" / "home" / "Library" / "Keychains"
                    if sys.platform == "darwin":
                        self.assertTrue(keychain_target.is_symlink())
                        self.assertEqual(keychains.resolve(), keychain_target.resolve())

    def test_agy_links_each_required_google_credential(self) -> None:
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
            XdgSandboxRunner(host="agy").run(
                [sys.executable, "-c", "print('ok')"],
                cwd=root,
                stdout_path=invocation / "stdout.log",
                stderr_path=invocation / "stderr.log",
                env={"HOME": str(source_home)},
                timeout_seconds=10,
            )

            for relative in required:
                target = invocation / "sandbox" / "home" / ".gemini" / relative
                self.assertTrue(target.is_symlink(), relative)
                self.assertEqual((source_home / ".gemini" / relative).resolve(), target.resolve())


if __name__ == "__main__":
    unittest.main()
