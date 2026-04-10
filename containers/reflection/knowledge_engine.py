"""
Knowledge Engine for Terraclaw.
Handles database extraction, LLM synthesis, and vector memory updates.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import json
from datetime import datetime, timedelta
from typing import Any

from google.cloud import storage, aiplatform
from google.cloud.aiplatform.models import TextEmbeddingModel
from openai import AsyncOpenAI

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("knowledge-engine")


class VectorStore:
    def __init__(self, project: str, location: str, index_name: str):
        self.project = project
        self.location = location
        self.index_name = index_name
        if project and location:
            aiplatform.init(project=project, location=location)
            try:
                self.model = TextEmbeddingModel.from_pretrained("text-embedding-004")
            except Exception as e:
                logger.warning(f"Could not load embedding model: {e}")
                self.model = None
        else:
            self.model = None

    async def push_facts(self, facts: list[str]):
        """Embed facts and push them to GCS for Vertex AI Vector Search sync."""
        if not facts or not self.model:
            logger.warning("No facts to push or embedding model not loaded.")
            return

        logger.info(f"Pushing {len(facts)} facts to Vertex Index: {self.index_name}")
        
        # Batch embedding (handle small batches for stability)
        embeddings = self.model.get_embeddings(facts)
        
        bucket_name = os.environ.get("LITESTREAM_BUCKET")
        if not bucket_name:
            logger.error("LITESTREAM_BUCKET not set, cannot push to Vector Search.")
            return

        storage_client = storage.Client()
        bucket = storage_client.bucket(bucket_name)
        
        data = []
        for i, (fact, emb) in enumerate(zip(facts, embeddings)):
            data.append({
                "id": f"fact-{datetime.now().strftime('%Y%m%d')}-{i}",
                "embedding": emb.values,
                "metadata": {"text": fact}
            })
            
        blob = bucket.blob(f"vector-index/update-{datetime.now().timestamp()}.jsonl")
        blob.upload_from_string("\n".join([json.dumps(d) for d in data]))
        logger.info(f"Uploaded {len(data)} embeddings to GCS for Vertex AI sync.")


class KnowledgeEngine:
    def __init__(self):
        self.bucket_name = os.environ.get("LITESTREAM_BUCKET")
        self.db_path = "/tmp/reflection_memory.db"
        self.openai_base_url = os.environ.get("OPENAI_BASE_URL")
        self.project = os.environ.get("GCP_PROJECT")
        self.location = os.environ.get("GCP_REGION", "us-central1")
        self.index_name = os.environ.get("VECTOR_SEARCH_INDEX")
        
        self.client = AsyncOpenAI(
            base_url=self.openai_base_url,
            api_key="dummy"
        )
        self.vector_store = VectorStore(self.project, self.location, self.index_name)

    async def sync_database(self):
        """Use litestream restore to get the latest SQLite DB."""
        if not self.bucket_name:
            logger.warning("LITESTREAM_BUCKET not set, skipping DB sync")
            return False

        replica_url = f"gs://{self.bucket_name}/zeroclaw-memory"
        logger.info(f"Restoring database from {replica_url}")
        
        import subprocess
        try:
            # -if-not-exists ensures we don't overwrite if not needed, 
            # but for reflection we usually want the freshest data.
            subprocess.run([
                "litestream", "restore", 
                "-o", self.db_path, 
                replica_url
            ], check=True)
            return True
        except subprocess.CalledProcessError as e:
            logger.error(f"Litestream restore failed: {e}")
            return False

    async def extract_recent_interactions(self, hours: int = 24) -> list[dict[str, Any]]:
        """Query SQLite for recent messages and tool results."""
        if not os.path.exists(self.db_path):
            return []

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        since = (datetime.now() - timedelta(hours=hours)).isoformat()
        
        interactions = []
        try:
            cursor.execute("SELECT * FROM messages WHERE created_at > ?", (since,))
            interactions = [dict(row) for row in cursor.fetchall()]
        except sqlite3.OperationalError:
            logger.warning("Could not find 'messages' table, trying alternative schema...")
        finally:
            conn.close()

        return interactions

    async def synthesize(self, interactions: list[dict[str, Any]]) -> list[str]:
        """Use DeepSeek to turn raw logs into permanent facts."""
        if not interactions:
            return []

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
        
        if facts:
            await self.vector_store.push_facts(facts)
            return f"Successfully synthesized and indexed {len(facts)} new facts."
        
        return "No new facts identified for synthesis."
