"""
Knowledge Store - Extracted facts about the user with semantic search.
Uses numpy cosine similarity over embeddings stored as BLOBs in SQLite.
Simple, portable, no extensions needed. Fast enough for tens of thousands of facts.
"""

import struct
from datetime import UTC, datetime

import aiosqlite
import numpy as np


def _serialize_embedding(embedding: list[float]) -> bytes:
    """Convert a list of floats to bytes for SQLite storage."""
    return struct.pack(f"{len(embedding)}f", *embedding)


def _deserialize_embedding(blob: bytes) -> np.ndarray:
    """Convert bytes back to a numpy array."""
    dim = len(blob) // 4  # 4 bytes per float32
    return np.array(struct.unpack(f"{dim}f", blob), dtype=np.float32)


class KnowledgeStore:
    """Stores and retrieves user facts with optional semantic search via embeddings."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._db: aiosqlite.Connection | None = None
        self._embed_fn = (
            None  # Set externally: async fn(text) -> list[float]
        )

    def set_embed_function(self, fn):
        """Set the embedding function: async fn(text) -> list[float]."""
        self._embed_fn = fn

    async def initialize(self):
        """Create tables if they don't exist."""
        self._db = await aiosqlite.connect(self.db_path)

        # Facts table (structured data + embedding as BLOB)
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS facts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT NOT NULL,
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                confidence REAL DEFAULT 1.0,
                source TEXT DEFAULT 'auto',
                embedding BLOB,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        await self._db.execute("""
            CREATE INDEX IF NOT EXISTS idx_facts_category ON facts(category)
        """)
        await self._db.execute("""
            CREATE INDEX IF NOT EXISTS idx_facts_key ON facts(key)
        """)
        await self._db.commit()

    async def store_fact(
        self,
        category: str,
        key: str,
        value: str,
        confidence: float = 1.0,
        source: str = "auto",
    ) -> int:
        """Store a fact. If a similar key exists in the same category, update it."""
        now = datetime.now(UTC).isoformat()

        # Generate embedding
        embedding_blob = None
        if self._embed_fn:
            try:
                text_to_embed = f"{key}: {value}"
                embedding = await self._embed_fn(text_to_embed)
                if embedding:
                    embedding_blob = _serialize_embedding(embedding)
            except Exception as e:
                print(f"[KnowledgeStore] Embedding error: {e}")

        # Check for existing fact with same key in same category
        cursor = await self._db.execute(
            "SELECT id FROM facts WHERE category = ? AND key = ?",
            (category, key),
        )
        existing = await cursor.fetchone()

        if existing:
            fact_id = existing[0]
            await self._db.execute(
                "UPDATE facts SET value = ?, confidence = ?, embedding = ?, updated_at = ? WHERE id = ?",
                (value, confidence, embedding_blob, now, fact_id),
            )
        else:
            cursor = await self._db.execute(
                "INSERT INTO facts (category, key, value, confidence, source, embedding, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    category,
                    key,
                    value,
                    confidence,
                    source,
                    embedding_blob,
                    now,
                    now,
                ),
            )
            fact_id = cursor.lastrowid

        await self._db.commit()
        return fact_id

    async def search_semantic(
        self, query: str, limit: int = 10
    ) -> list[dict]:
        """Search facts by semantic similarity using cosine distance."""
        if not self._embed_fn:
            return await self.search_keyword(query, limit)

        try:
            # Embed the query
            query_embedding = await self._embed_fn(query)
            if not query_embedding:
                return await self.search_keyword(query, limit)

            query_vec = np.array(query_embedding, dtype=np.float32)
            query_norm = np.linalg.norm(query_vec)
            if query_norm == 0:
                return await self.search_keyword(query, limit)

            # Fetch all facts with embeddings
            cursor = await self._db.execute(
                "SELECT id, category, key, value, confidence, created_at, updated_at, embedding "
                "FROM facts WHERE embedding IS NOT NULL"
            )
            rows = await cursor.fetchall()

            if not rows:
                return await self.search_keyword(query, limit)

            # Compute cosine similarity for each fact
            scored = []
            for row in rows:
                fact_embedding = _deserialize_embedding(row[7])
                fact_norm = np.linalg.norm(fact_embedding)
                if fact_norm == 0:
                    continue
                similarity = float(
                    np.dot(query_vec, fact_embedding)
                    / (query_norm * fact_norm)
                )
                scored.append((similarity, row))

            # Sort by similarity (highest first) and take top K
            scored.sort(key=lambda x: x[0], reverse=True)

            results = []
            for similarity, row in scored[:limit]:
                results.append(
                    {
                        "id": row[0],
                        "category": row[1],
                        "key": row[2],
                        "value": row[3],
                        "confidence": row[4],
                        "created_at": row[5],
                        "updated_at": row[6],
                        "similarity": round(similarity, 4),
                    }
                )
            return results

        except Exception as e:
            print(
                f"[KnowledgeStore] Semantic search error ({e}), falling back to keyword."
            )
            return await self.search_keyword(query, limit)

    async def search_keyword(
        self, query: str, limit: int = 10
    ) -> list[dict]:
        """Fallback keyword search using LIKE."""
        cursor = await self._db.execute(
            "SELECT id, category, key, value, confidence, created_at, updated_at "
            "FROM facts WHERE key LIKE ? OR value LIKE ? "
            "ORDER BY updated_at DESC LIMIT ?",
            (f"%{query}%", f"%{query}%", limit),
        )
        rows = await cursor.fetchall()
        return [
            {
                "id": r[0],
                "category": r[1],
                "key": r[2],
                "value": r[3],
                "confidence": r[4],
                "created_at": r[5],
                "updated_at": r[6],
            }
            for r in rows
        ]

    async def get_all_facts(
        self, category: str | None = None, limit: int = 100
    ) -> list[dict]:
        """Get all facts, optionally filtered by category."""
        if category:
            cursor = await self._db.execute(
                "SELECT id, category, key, value, confidence, created_at, updated_at "
                "FROM facts WHERE category = ? ORDER BY updated_at DESC LIMIT ?",
                (category, limit),
            )
        else:
            cursor = await self._db.execute(
                "SELECT id, category, key, value, confidence, created_at, updated_at "
                "FROM facts ORDER BY updated_at DESC LIMIT ?",
                (limit,),
            )
        rows = await cursor.fetchall()
        return [
            {
                "id": r[0],
                "category": r[1],
                "key": r[2],
                "value": r[3],
                "confidence": r[4],
                "created_at": r[5],
                "updated_at": r[6],
            }
            for r in rows
        ]

    async def delete_fact(self, key: str) -> bool:
        """Delete a fact by key."""
        cursor = await self._db.execute(
            "SELECT id FROM facts WHERE key LIKE ?", (f"%{key}%",)
        )
        row = await cursor.fetchone()
        if not row:
            return False

        await self._db.execute("DELETE FROM facts WHERE id = ?", (row[0],))
        await self._db.commit()
        return True

    async def close(self):
        if self._db:
            await self._db.close()
