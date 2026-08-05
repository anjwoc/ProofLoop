import asyncio

from mcp.server.fastmcp import FastMCP

from proofloop_core.mcp_server import _get_client_name, mcp


def test_mcp_server_initialization():
    assert isinstance(mcp, FastMCP)
    assert mcp.name == "proofloop-core"


def test_tools_registered():
    tools = asyncio.run(mcp.list_tools())
    tools_names = [tool.name for tool in tools]
    assert "proofloop_plan_work" in tools_names
    assert "proofloop_execute_checks" in tools_names
    assert "proofloop_commit_verdict" in tools_names


def test_get_client_name_fallback():
    class DummyCtx:
        pass

    assert _get_client_name(DummyCtx()) == "unknown"
