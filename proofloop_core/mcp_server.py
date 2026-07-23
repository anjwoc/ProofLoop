"""MCP control plane for a real ProofLoop run.

The server only starts runs and exposes Core-owned artifacts.  It never lets
an MCP client invent verification evidence or commit a Truth verdict.
"""

from __future__ import annotations

import json
import logging
import subprocess
import threading
import uuid
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import Context, FastMCP

from proofloop_core.engine.orchestrator import ProofLoopOrchestrator

logger = logging.getLogger(__name__)
mcp = FastMCP("proofloop-core")
_sessions: dict[str, dict[str, Any]] = {}
_sessions_lock = threading.Lock()


def _get_client_name(ctx: Context) -> str:
    """Safely extract the MCP client name from the session context."""
    try:
        session = getattr(getattr(ctx, "request_context", None), "session", None)
        name = getattr(getattr(session, "client_info", None), "name", "")
        if name:
            return str(name).lower()
    except Exception:
        pass
    return "unknown"


def _repository_root(repository: str | None) -> Path:
    root = Path(repository).resolve() if repository else Path.cwd().resolve()
    result = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise ValueError(f"repository must be a Git worktree: {root}")
    return Path(result.stdout.strip()).resolve()


def _build_repo_context(request_text: str) -> dict[str, str]:
    """Compatibility helper for clients that inspect the bound repository."""
    return {"repo_root": str(_repository_root(None)), "request_text": request_text}


def _read_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _events_after(run_dir: Path | None, after: int) -> tuple[list[dict[str, Any]], int]:
    if run_dir is None or after < 0:
        return [], max(after, 0)
    try:
        lines = (run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
    except OSError:
        return [], after
    events: list[dict[str, Any]] = []
    for line in lines[after : after + 100]:
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if isinstance(item, dict):
            events.append(item)
    return events, min(len(lines), after + 100)


def _session_payload(session_id: str, *, after: int) -> dict[str, Any]:
    with _sessions_lock:
        state = _sessions.get(session_id)
        if state is None:
            raise ValueError(f"unknown ProofLoop session: {session_id}")
        orchestrator = state["orchestrator"]
        status = state["status"]
        result = state.get("result")
        error = state.get("error")
        client = state["client"]
    run_dir = getattr(orchestrator, "run_dir", None)
    events, next_event = _events_after(run_dir, after)
    outcome = _read_object(run_dir / "run-outcome.json") if isinstance(run_dir, Path) else {}
    return {
        "schemaVersion": "1.0",
        "sessionId": session_id,
        "status": status,
        "client": client,
        "runDir": str(run_dir) if isinstance(run_dir, Path) else None,
        "runId": outcome.get("runId") or (result or {}).get("runId"),
        "events": events,
        "nextEvent": next_event,
        "outcome": outcome or result,
        "error": error,
    }


def _run_session(session_id: str) -> None:
    with _sessions_lock:
        state = _sessions[session_id]
        orchestrator = state["orchestrator"]
        state["status"] = "RUNNING"
    try:
        result = orchestrator.run()
    except Exception as exc:
        logger.exception("ProofLoop MCP session %s failed", session_id)
        with _sessions_lock:
            state["status"] = "FAILED"
            state["error"] = f"{type(exc).__name__}: {exc}"
    else:
        with _sessions_lock:
            state["status"] = "COMPLETED"
            state["result"] = result


@mcp.tool()
def proofloop_start_run(
    request_text: str,
    host: str,
    ctx: Context,
    *,
    repository: str | None = None,
    mode: str = "adaptive",
) -> str:
    """Start one real ProofLoop run and return a session id for event polling.

    ``host`` is explicit because it may invoke that host's authenticated CLI.
    """
    if not request_text.strip():
        raise ValueError("request_text must be non-empty")
    if not host.strip():
        raise ValueError("host must be non-empty")
    if mode not in {"adaptive", "orchestrate", "goal", "audit"}:
        raise ValueError(f"unsupported ProofLoop mode: {mode}")
    repo = _repository_root(repository)
    orchestrator = ProofLoopOrchestrator(host, repo, request_text, mode=mode)
    session_id = uuid.uuid4().hex
    with _sessions_lock:
        _sessions[session_id] = {
            "client": _get_client_name(ctx),
            "orchestrator": orchestrator,
            "status": "QUEUED",
        }
    threading.Thread(target=_run_session, args=(session_id,), daemon=True).start()
    return json.dumps(_session_payload(session_id, after=0), ensure_ascii=False)


@mcp.tool()
def proofloop_plan_work(request_text: str, ctx: Context) -> str:
    """Compatibility hint; use ``proofloop_start_run`` for a real run."""
    del request_text, ctx
    return json.dumps(
        {
            "schemaVersion": "1.0",
            "status": "MIGRATED",
            "message": "Use proofloop_start_run with an explicit host; only a real run can create a plan or Truth verdict.",
        },
        ensure_ascii=False,
    )


@mcp.tool()
def proofloop_execute_checks(test_command: str, ctx: Context) -> str:
    """Compatibility hint; Core executes only its frozen verification plan."""
    del test_command, ctx
    return json.dumps(
        {
            "schemaVersion": "1.0",
            "status": "MIGRATED",
            "message": "A client cannot run arbitrary checks. Poll proofloop_run_status for Core-owned check evidence.",
        },
        ensure_ascii=False,
    )


@mcp.tool()
def proofloop_commit_verdict(verdict: str, summary: str, ctx: Context) -> str:
    """Compatibility hint; only the Core truth gate can issue a verdict."""
    del verdict, summary, ctx
    return json.dumps(
        {
            "schemaVersion": "1.0",
            "status": "MIGRATED",
            "message": "A client cannot commit a verdict. Poll proofloop_run_status for run-outcome.json.",
        },
        ensure_ascii=False,
    )


@mcp.tool()
def proofloop_run_status(session_id: str, ctx: Context, *, after: int = 0) -> str:
    """Read new Core-emitted events and the current terminal outcome for a run."""
    del ctx
    return json.dumps(_session_payload(session_id, after=after), ensure_ascii=False)


if __name__ == "__main__":
    mcp.run()
