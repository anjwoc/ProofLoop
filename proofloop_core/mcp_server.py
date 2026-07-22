import json
import logging
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP, Context
import subprocess

logger = logging.getLogger(__name__)

mcp = FastMCP("proofloop-core")

def _get_client_name(ctx: Context) -> str:
    """Safely extract the MCP client name from the session context."""
    try:
        if hasattr(ctx, "request_context") and ctx.request_context:
            session = getattr(ctx.request_context, "session", None)
            if session:
                client_info = getattr(session, "client_info", None)
                if client_info:
                    name = getattr(client_info, "name", "")
                    if name:
                        return name.lower()
    except Exception:
        pass
    return "unknown"


def _build_repo_context(request_text: str) -> dict[str, str]:
    """Resolve the repository context for ProofLoop."""
    try:
        repo_root = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"], text=True
        ).strip()
    except subprocess.CalledProcessError:
        repo_root = str(Path.cwd())
        
    return {
        "repo_root": repo_root,
        "request_text": request_text,
    }

@mcp.tool()
def proofloop_plan_work(request_text: str, ctx: Context) -> str:
    """Analyze the user request, evaluate intent, and emit a bounding blueprint.
    
    Call this first to establish the allowed scope and constraints before making code changes.
    """
    client_name = _get_client_name(ctx)
    context = _build_repo_context(request_text)
    repo = Path(context["repo_root"])
    
    run_dir = repo / ".proofloop" / "runs" / "current"
    run_dir.mkdir(parents=True, exist_ok=True)
    
    # Save request
    (run_dir / "request.txt").write_text(request_text, encoding="utf-8")
    
    # Simulate planning output (in reality this hooks into ProofLoop's engine)
    blueprint = {
        "status": "READY",
        "client_detected": client_name,
        "repo": str(repo),
        "allowed_scope": ["src/", "tests/"],
        "required_checks": [
            "pytest"
        ]
    }
    
    (run_dir / "blueprint.json").write_text(json.dumps(blueprint, indent=2))
    
    return f"""ProofLoop Plan Established!
Client Detected: {client_name}
Repository: {repo}

ALLOWED SCOPE: {blueprint['allowed_scope']}
REQUIRED CHECKS: {blueprint['required_checks']}

You may now proceed to implement changes within the allowed scope.
When you are ready to verify, use the `proofloop_execute_checks` tool.
"""

@mcp.tool()
def proofloop_execute_checks(test_command: str, ctx: Context) -> str:
    """Run verification checks inside the ProofLoop sandbox and capture evidence.
    
    Call this after implementing changes to prove they work.
    """
    client_name = _get_client_name(ctx)
    repo_root = _build_repo_context("")["repo_root"]
    
    try:
        result = subprocess.run(
            test_command, 
            shell=True, 
            cwd=repo_root,
            capture_output=True, 
            text=True, 
            timeout=120
        )
        status = "PASS" if result.returncode == 0 else "FAIL"
        
        return f"""[ProofLoop Evidence Captured for {client_name}]
Command: {test_command}
Status: {status}
Exit Code: {result.returncode}

--- STDOUT ---
{result.stdout[-2000:] if result.stdout else '(empty)'}

--- STDERR ---
{result.stderr[-2000:] if result.stderr else '(empty)'}
"""
    except Exception as e:
        return f"Error executing check: {e}"

@mcp.tool()
def proofloop_commit_verdict(verdict: str, summary: str, ctx: Context) -> str:
    """Commit the final verdict (PROVEN or FAILED) and conclude the ProofLoop run.
    
    Call this when you have successfully executed the required checks or hit a hard blocker.
    """
    client_name = _get_client_name(ctx)
    repo_root = _build_repo_context("")["repo_root"]
    
    run_dir = Path(repo_root) / ".proofloop" / "runs" / "current"
    run_dir.mkdir(parents=True, exist_ok=True)
    
    report = {
        "verdict": verdict,
        "summary": summary,
        "client": client_name,
    }
    (run_dir / "truth-report.json").write_text(json.dumps(report, indent=2))
    
    return f"""ProofLoop Truth Report Committed.
Verdict: {verdict}
Client: {client_name}
Summary: {summary}

The ProofLoop session has concluded natively within your agent UI.
"""

if __name__ == "__main__":
    mcp.run()
