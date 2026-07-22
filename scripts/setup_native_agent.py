#!/usr/bin/env python3
import json
import os
from pathlib import Path
import sys

def main():
    repo_root = Path(__file__).resolve().parents[1]
    mcp_script = repo_root / "proofloop_core" / "mcp_server.py"
    
    server_config = {
        "command": sys.executable,
        "args": [str(mcp_script)]
    }

    print("Configuring Antigravity IDE (mcp.json)...")
    antigravity_mcp_path = Path.home() / ".gemini" / "config" / "mcp.json"
    ag_config = {}
    if antigravity_mcp_path.exists():
        try:
            ag_config = json.loads(antigravity_mcp_path.read_text())
        except Exception:
            pass
    
    if "mcpServers" not in ag_config:
        ag_config["mcpServers"] = {}
        
    ag_config["mcpServers"]["proofloop-core"] = server_config
    antigravity_mcp_path.parent.mkdir(parents=True, exist_ok=True)
    antigravity_mcp_path.write_text(json.dumps(ag_config, indent=2))
    print(f" -> Updated {antigravity_mcp_path}")

    print("\nConfiguring Claude Code (claude.json)...")
    claude_config_path = repo_root / "claude.json"
    claude_config = {}
    if claude_config_path.exists():
        try:
            claude_config = json.loads(claude_config_path.read_text())
        except Exception:
            pass
            
    if "mcpServers" not in claude_config:
        claude_config["mcpServers"] = {}
        
    claude_config["mcpServers"]["proofloop-core"] = server_config
    claude_config_path.write_text(json.dumps(claude_config, indent=2))
    print(f" -> Updated {claude_config_path}")

    print("\nConfiguring Codex (.codex/mcp.json)...")
    codex_dir = repo_root / ".codex"
    codex_dir.mkdir(parents=True, exist_ok=True)
    codex_mcp_path = codex_dir / "mcp.json"
    
    codex_config = {}
    if codex_mcp_path.exists():
        try:
            codex_config = json.loads(codex_mcp_path.read_text())
        except Exception:
            pass
            
    if "mcpServers" not in codex_config:
        codex_config["mcpServers"] = {}
        
    codex_config["mcpServers"]["proofloop-core"] = server_config
    codex_mcp_path.write_text(json.dumps(codex_config, indent=2))
    print(f" -> Updated {codex_mcp_path}")
    
    print("\nSuccess! The ProofLoop MCP server is now registered across all 3 platforms.")

if __name__ == "__main__":
    main()
