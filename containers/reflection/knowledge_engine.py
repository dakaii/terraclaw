"""
Knowledge Engine for Terraclaw.
Handles database extraction, LLM synthesis, and vector memory updates.
"""

from __future__ import annotations

import logging
import os
import sqlite3
from datetime import datetime, timedelta
from typing import Any

from google.cloud import storage
from openai import AsyncOpenAI

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("knowledge-engine")

class KnowledgeEngine:
    def __init__(self):
        self.bucket_name = os.environ.get("LITESTREAM_BUCKET")
        self.db_path = "/tmp/reflection_memory.db"
        self.openai_base_url = os.environ.get("OPENAI_BASE_URL")
        self.client = AsyncOpenAI(
            base_url=self.openai_base_url,
            api_key="dummy"
        )

    async def sync_database(self):
        """Download the latest SQLite DB from GCS."""
        if not self.bucket_name:
            logger.warning("LITESTREAM_BUCKET not set, skipping DB sync")
            return False

        logger.info(f"Downloading memory.db from gs://{self.bucket_name}/zeroclaw-memory")
        storage_client = storage.Client()
        bucket = storage_client.bucket(self.bucket_name)
        # Note: Litestream stores the main DB at the root of the path
        blob = bucket.blob("zeroclaw-memory/data") # This depends on Litestream's pathing
        
        # If the exact path is complex, we might need to list blobs or use litestream restore
        # For now, we assume a direct download is possible or we'd use 'litestream restore'
        try:
            blob.download_to_filename(self.db_path)
            return True
        except Exception as e:
            logger.error(f"Failed to download DB: {e}")
            return False

    async def extract_recent_interactions(self, hours: int = 24) -> list[dict[str, Any]]:
        """Query SQLite for recent messages and tool results."""
        if not os.path.exists(self.db_path):
            return []

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Assuming ZeroClaw schema (messages, tool_calls, observations)
        # We'll use a generic query that looks for recent entries
        since = (datetime.now() - timedelta(hours=hours)).isoformat()
        
        interactions = []
        try:
            # This is a heuristic query - exact schema may vary
            cursor.execute("SELECT * FROM messages WHERE created_at > ?", (since,))
            interactions = [dict(row) for row in cursor.fetchall()]
        except sqlite3.OperationalError:
            logger.warning("Could not find 'messages' table, trying alternative schema...")
            # Fallback to general investigation of tables if schema is unknown
        finally:
            conn.close()

        return interactions

    async def synthesize(self, interactions: list[dict[str, Any]]) -> list[str]:
        """Use DeepSeek to turn raw logs into permanent facts."""
        if not interactions:
            return []

        # Convert interactions to a readable string for the LLM
        log_text = "\n".join([f"{i.get('role')}: {i.get('content')}" for i in interactions[:50]])

        prompt = f"""
        You are the Reflection Brain for Terraclaw, a private AI agent.
        Below are the raw interaction logs from the last 24 hours.
        Your task is to extract 'Knowledge Fragments' (permanent facts) that the agent should remember forever.
        
        Focus on:
        1. New information learned from web searches.
        2. User preferences or specific instructions.
        3. Factual corrections.
        
        Raw Logs:
        {log_text}
        
        Output only a bulleted list of facts. If nothing new was learned, output 'None'.
        """

        response = await self.client.chat.completions.create(
            model="deepseek",
            messages=[{"role": "system", "content": prompt}]
        )

        facts = response.choices[0].message.content.split("\n")
        return [f.strip("- ").strip() for f in facts if f.strip() and f.lower() != "none"]

    async def run_loop(self):
        """Execute the full synthesis loop."""
        await self.sync_database()
        interactions = await self.extract_recent_interactions()
        if not interactions:
            return "No recent interactions found."

        facts = await self.synthesize(interactions)
        
        # TODO: Push to Vertex AI Vector Search
        # For now, we log them
        for fact in facts:
            logger.info(f"Synthesized Fact: {fact}")

        return f"Successfully synthesized {len(facts)} new facts."
