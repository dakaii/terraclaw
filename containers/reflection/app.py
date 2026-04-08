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

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("reflection")

app = FastAPI(title="Terraclaw Reflection", version="0.1.0")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/run")
def run_reflection() -> dict[str, str]:
    bucket = os.environ.get("LITESTREAM_BUCKET", "")
    llm = os.environ.get("OPENAI_BASE_URL", "")
    log.info("reflection run bucket=%s openai_base=%s", bucket, llm)
    # TODO: litestream restore, sqlite read, LLM summarization, gcs writeback
    return {
        "status": "ok",
        "detail": "stub — implement pruning + RAG updates against your private model",
    }
