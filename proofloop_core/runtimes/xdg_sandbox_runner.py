from __future__ import annotations

import os
import sys
import threading
from pathlib import Path
from typing import Mapping

from .process_runner import ProcessRunner, ProcessResult, LineCallback, HeartbeatCallback, OutputFilter

class XdgSandboxRunner:
    """
    A runner that isolates the agent's configuration and state from the host machine
    by hijacking XDG environment variables and redirecting them to a temporary directory.
    """
    def __init__(
        self,
        *,
        host: str | None = None,
        terminate_grace_seconds: float = 2.0,
        drain_grace_seconds: float = 2.0,
        poll_interval: float = 0.05,
        max_queued_lines: int = 1024,
    ) -> None:
        self.host = host
        self.process_runner = ProcessRunner(
            terminate_grace_seconds=terminate_grace_seconds,
            drain_grace_seconds=drain_grace_seconds,
            poll_interval=poll_interval,
            max_queued_lines=max_queued_lines,
        )

    @staticmethod
    def _link_auth_file(source: Path, target: Path) -> None:
        """Expose one existing credential without copying it into run evidence."""
        if not source.is_file() or target.exists() or target.is_symlink():
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        target.symlink_to(source)

    @staticmethod
    def _link_auth_directory(source: Path, target: Path) -> None:
        """Expose an OS credential store without copying its contents."""
        if not source.is_dir() or target.exists() or target.is_symlink():
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        target.symlink_to(source, target_is_directory=True)

    def _preserve_host_authentication(
        self,
        sandbox_home: Path,
        sandbox_config: Path,
        parent_env: Mapping[str, str],
        sandbox_env: dict[str, str],
    ) -> None:
        """Make a host's existing login available while retaining isolated state."""
        source_home = Path(parent_env.get("HOME") or Path.home()).expanduser()
        if sys.platform == "darwin":
            self._link_auth_directory(source_home / "Library" / "Keychains", sandbox_home / "Library" / "Keychains")
        if self.host == "codex":
            source = Path(parent_env.get("CODEX_HOME") or source_home / ".codex") / "auth.json"
            self._link_auth_file(source, sandbox_config / "codex" / "auth.json")
        elif self.host == "claude-code":
            source_config = Path(parent_env.get("CLAUDE_CONFIG_DIR") or source_home / ".claude")
            sandbox_env["CLAUDE_CONFIG_DIR"] = str(sandbox_config / "claude")
            self._link_auth_file(source_config / ".credentials.json", sandbox_config / "claude" / ".credentials.json")
        elif self.host in {"agy", "antigravity"}:
            source_gemini = source_home / ".gemini"
            for relative_path in (
                "oauth_creds.json",
                "google_accounts.json",
                "antigravity-cli/antigravity-oauth-token",
            ):
                self._link_auth_file(source_gemini / relative_path, sandbox_home / ".gemini" / relative_path)

    def run(
        self,
        command: list[str] | tuple[str, ...],
        *,
        cwd: str | Path,
        stdout_path: str | Path,
        stderr_path: str | Path,
        env: Mapping[str, str] | None = None,
        timeout_seconds: float | None = None,
        initial_output_timeout_seconds: float | None = None,
        on_line: LineCallback | None = None,
        output_filter: OutputFilter | None = None,
        stdin_data: str | bytes | None = None,
        on_heartbeat: HeartbeatCallback | None = None,
        heartbeat_interval_seconds: float = 5.0,
        cancel_event: threading.Event | None = None,
    ) -> ProcessResult:
        
        # 1. Use the existing invocation directory inside .proofloop instead of /tmp
        # ProofLoop already isolates outputs by run_dir/invocations/invocation_id
        # stdout_path is <run_dir>/invocations/<invocation_id>/stdout.log
        call_dir = Path(stdout_path).parent
        sandbox_dir = call_dir / "sandbox"
        
        try:
            # 2. Setup XDG subdirectories
            xdg_config = sandbox_dir / "config"
            xdg_data = sandbox_dir / "data"
            xdg_cache = sandbox_dir / "cache"
            xdg_state = sandbox_dir / "state"
            home_dir = sandbox_dir / "home"
            
            for d in (xdg_config, xdg_data, xdg_cache, xdg_state, home_dir):
                d.mkdir(parents=True, exist_ok=True)
                
            # 3. Hijack Environment Variables
            sandbox_env = dict(env) if env else dict(os.environ)
            sandbox_env.update({
                "XDG_CONFIG_HOME": str(xdg_config),
                "XDG_DATA_HOME": str(xdg_data),
                "XDG_CACHE_HOME": str(xdg_cache),
                "XDG_STATE_HOME": str(xdg_state),
                "HOME": str(home_dir),
                # Agent-specific overrides to ensure they don't use host configs
                "CODEX_HOME": str(xdg_config / "codex"),
                "OPENCODE_DISABLE_AUTOUPDATE": "1",
            })
            self._preserve_host_authentication(
                home_dir,
                xdg_config,
                env or os.environ,
                sandbox_env,
            )
            
            # 4. Delegate to underlying ProcessRunner with sandboxed environment
            return self.process_runner.run(
                command=command,
                cwd=cwd,
                stdout_path=stdout_path,
                stderr_path=stderr_path,
                env=sandbox_env,
                timeout_seconds=timeout_seconds,
                initial_output_timeout_seconds=initial_output_timeout_seconds,
                on_line=on_line,
                output_filter=output_filter,
                stdin_data=stdin_data,
                on_heartbeat=on_heartbeat,
                heartbeat_interval_seconds=heartbeat_interval_seconds,
                cancel_event=cancel_event,
            )
        finally:
            # 5. We no longer auto-delete the sandbox.
            # Leaving it inside .proofloop/run/<id>/invocations/<id>/sandbox 
            # allows users to inspect exactly what the agent did or corrupted.
            pass
