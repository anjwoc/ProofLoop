from mcp.server import Server
from mcp.types import InitializeRequest

app = Server("proofloop")

@app.request_handlers.setdefault(InitializeRequest)
async def handle_init(request: InitializeRequest):
    print(request)
