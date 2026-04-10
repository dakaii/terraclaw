"""
Scheduled reflection job (memory hygiene + RAG hints).

Extend this to: restore Litestream DB from GCS, read recent turns,
call your private LLM (same OPENAI_* env as ZeroClaw), and write
summaries / pruning back to storage.
"""

from __future__ import annotations

import logging
import os

from fastapi import FastAPI
from search_service import get_search_provider

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("reflection")

app = FastAPI(title="Terraclaw Reflection", version="0.1.0")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


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
