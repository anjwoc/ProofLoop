import asyncio
from mcp.server.fastmcp import FastMCP, Context
from mcp.types import InitializeRequest, ClientCapabilities, Implementation

app = FastMCP("test")

@app.tool()
def test_tool(ctx: Context) -> str:
    # how to access client info?
    client_name = "unknown"
    if hasattr(ctx, "session") and hasattr(ctx.session, "request_context"):
        client_info = getattr(ctx.session.request_context.init_options, "client_info", None)
        if client_info:
            client_name = client_info.name
    
    # Try request_context
    if hasattr(ctx, "request_context") and hasattr(ctx.request_context, "session"):
        if hasattr(ctx.request_context.session, "client_info"):
            client_name = ctx.request_context.session.client_info.name
            
    # Try just standard ctx internals
    return str(dir(ctx.request_context.session))

async def main():
    print("Testing...")

if __name__ == "__main__":
    asyncio.run(main())
