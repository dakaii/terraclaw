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

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("reflection")

app = FastAPI(title="Terraclaw Reflection & MCP", version="0.1.0")

# Setup SSE Transport for MCP
sse_transport = SseServerTransport("/mcp/messages")


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
    bucket = os.environ.get("LITESTREAM_BUCKET", "")
    llm = os.environ.get("OPENAI_BASE_URL", "")

    search = get_search_provider()
    results = await search.search("What is the current state of Terraclaw AI?")

    log.info("reflection run bucket=%s openai_base=%s search_results=%d",
             bucket, llm, len(results))

    # TODO:
    # 1. litestream restore (restore the latest SQLite DB from GCS)
    # 2. sqlite query (extract today's interactions/web-crawls)
    # 3. LLM call (summarize knowledge into new facts)
    # 4. vertex index update (push new facts to RAG)
    # 5. gcs writeback (backup summarized/pruned DB)

    return {
        "status": "ok",
        "detail": f"Knowledge synthesized from {len(results)} search results.",
        "search_used": type(search).__name__
    }
