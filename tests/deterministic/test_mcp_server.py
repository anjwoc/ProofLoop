import pytest
from mcp.server.fastmcp import FastMCP
from proofloop_core.mcp_server import mcp, _get_client_name

def test_mcp_server_initialization():
    assert isinstance(mcp, FastMCP)
    assert mcp.name == "proofloop-core"

@pytest.mark.asyncio
async def test_tools_registered():
    tools = await mcp.list_tools()
    tools_names = [t.name for t in tools]
    assert "proofloop_plan_work" in tools_names
    assert "proofloop_execute_checks" in tools_names
    assert "proofloop_commit_verdict" in tools_names

def test_get_client_name_fallback():
    class DummyCtx:
        pass
    
    assert _get_client_name(DummyCtx()) == "unknown"
