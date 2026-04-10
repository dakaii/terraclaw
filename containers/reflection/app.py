"""
Scheduled reflection job (memory hygiene + RAG hints).

Extend this to: restore Litestream DB from GCS, read recent turns,
call your private LLM (same OPENAI_* env as ZeroClaw), and write
summaries / pruning back to storage.
"""

from __future__ import annotations

import logging
import os

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from mcp.server.sse import SseServerTransport
from search_service import get_search_provider
from mcp_server import mcp_server
from knowledge_engine import KnowledgeEngine

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("reflection")

app = FastAPI(title="Terraclaw Reflection & MCP", version="0.1.0")

# Setup SSE Transport for MCP
sse_transport = SseServerTransport("/mcp/messages")
engine = KnowledgeEngine()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/mcp/sse")
async def mcp_sse_endpoint():
    """Endpoint for MCP clients to establish an SSE connection."""
    async with sse_transport.connect_sse() as (read_stream, write_stream):
        await mcp_server.run(
            read_stream,
            write_stream,
            mcp_server.create_initialization_options()
        )


@app.post("/mcp/messages")
async def mcp_messages_endpoint(request: Request):
    """Endpoint for MCP clients to send messages to the server."""
    await sse_transport.handle_post_request(request)
    return JSONResponse(content={"status": "ok"})


@app.post("/run")
async def run_reflection() -> dict[str, str]:
    """Execute the daily knowledge synthesis loop."""
    try:
        status = await engine.run_loop()
        return {
            "status": "ok",
            "detail": status
        }
    except Exception as e:
        log.error(f"Reflection loop failed: {e}")
        return {
            "status": "error",
            "detail": str(e)
        }
