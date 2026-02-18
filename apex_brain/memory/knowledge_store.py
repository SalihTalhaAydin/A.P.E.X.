"""
Knowledge Store - Facts about the user with semantic search.
Uses numpy cosine similarity over embeddings in SQLite.
Simple, portable, no extensions needed.

v0.3.0: deduplication, conflict resolution, temporal metadata.
"""
from __future__ import annotations

import struct
from datetime import datetime, timezone

import aiosqlite
import numpy as np


def _serialize_embedding(
    embedding: list[float],
) -> bytes:
    """Convert a list of floats to bytes."""
    return struct.pack(
        f"{len(embedding)}f", *embedding
    )


def _deserialize_embedding(
    blob: bytes,
) -> np.ndarray:
    """Convert bytes back to a numpy array."""
    dim = len(blob) // 4  # 4 bytes per float32
    return np.array(
        struct.unpack(f"{dim}f", blob),
        dtype=np.float32,
    )


def _cosine_similarity(
    a: np.ndarray, b: np.ndarray
) -> float:
    """Cosine similarity between two vectors."""
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))


class KnowledgeStore:
    """Stores and retrieves user facts with
    semantic search via embeddings."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._db: aiosqlite.Connection | None = None
        self._embed_fn = None

    def set_embed_function(self, fn):
        """Set the embedding function."""
        self._embed_fn = fn

    async def initialize(self):
        """Create tables if they don't exist."""
        self._db = await aiosqlite.connect(
            self.db_path
        )

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
            CREATE INDEX IF NOT EXISTS
            idx_facts_category ON facts(category)
        """)
        await self._db.execute("""
            CREATE INDEX IF NOT EXISTS
            idx_facts_key ON facts(key)
        """)

        # v0.3.0 schema migration: add temporal cols
        await self._migrate_add_columns()

        await self._db.commit()

    async def _migrate_add_columns(self):
        """Add new columns if missing."""
        cursor = await self._db.execute(
            "PRAGMA table_info(facts)"
        )
        cols = {
            row[1] for row in await cursor.fetchall()
        }

        if "last_mentioned_at" not in cols:
            await self._db.execute(
                "ALTER TABLE facts "
                "ADD COLUMN last_mentioned_at TEXT"
            )
        if "expires_at" not in cols:
            await self._db.execute(
                "ALTER TABLE facts "
                "ADD COLUMN expires_at TEXT"
            )

    async def _embed_text(
        self, text: str
    ) -> np.ndarray | None:
        """Get embedding vector for text."""
        if not self._embed_fn:
            return None
        try:
            emb = await self._embed_fn(text)
            if emb:
                return np.array(
                    emb, dtype=np.float32
                )
        except Exception as e:
            print(
                "[KnowledgeStore] "
                f"Embedding error: {e}"
            )
        return None

    async def _check_duplicate(
        self,
        category: str,
        value: str,
        new_embedding: np.ndarray | None,
        threshold: float = 0.92,
    ) -> int | None:
        """Check for semantically duplicate fact.

        Returns existing fact ID if duplicate found.
        """
        if new_embedding is None:
            return None

        cursor = await self._db.execute(
            "SELECT id, embedding FROM facts "
            "WHERE category = ? "
            "AND embedding IS NOT NULL",
            (category,),
        )
        rows = await cursor.fetchall()

        for row in rows:
            existing = _deserialize_embedding(
                row[1]
            )
            sim = _cosine_similarity(
                new_embedding, existing
            )
            if sim >= threshold:
                return row[0]
        return None

    async def store_fact(
        self,
        category: str,
        key: str,
        value: str,
        confidence: float = 1.0,
        source: str = "auto",
        expires_at: str | None = None,
        force: bool = False,
    ) -> int:
        """Store a fact with dedup + conflict
        resolution.

        If same (category, key) exists: update if
        new confidence >= old. If semantically
        duplicate value exists: skip (just touch).
        When force=True, skip confidence comparison
        and always update (used for corrections).
        """
        now = datetime.now(timezone.utc).isoformat()

        # Generate embedding
        embedding_blob = None
        embedding_vec = await self._embed_text(
            f"{key}: {value}"
        )
        if embedding_vec is not None:
            embedding_blob = _serialize_embedding(
                embedding_vec.tolist()
            )

        # 1. Check exact key match (conflict)
        cursor = await self._db.execute(
            "SELECT id, value, confidence "
            "FROM facts "
            "WHERE category = ? AND key = ?",
            (category, key),
        )
        existing = await cursor.fetchone()

        if existing:
            fact_id = existing[0]
            old_value = existing[1]
            old_conf = existing[2]

            # Same value → just touch timestamp
            if old_value == value:
                await self._db.execute(
                    "UPDATE facts "
                    "SET last_mentioned_at = ?, "
                    "updated_at = ? "
                    "WHERE id = ?",
                    (now, now, fact_id),
                )
                await self._db.commit()
                return fact_id

            # Different value → higher conf wins
            # (force=True skips comparison)
            if force or confidence >= old_conf:
                await self._db.execute(
                    "UPDATE facts SET value = ?, "
                    "confidence = ?, "
                    "embedding = ?, "
                    "updated_at = ?, "
                    "last_mentioned_at = ?, "
                    "expires_at = ? "
                    "WHERE id = ?",
                    (
                        value,
                        confidence,
                        embedding_blob,
                        now,
                        now,
                        expires_at,
                        fact_id,
                    ),
                )
                await self._db.commit()
                return fact_id
            else:
                # Lower confidence → skip
                return fact_id

        # 2. Semantic dedup: similar value stored?
        dup_id = await self._check_duplicate(
            category, value, embedding_vec
        )
        if dup_id is not None:
            await self._db.execute(
                "UPDATE facts "
                "SET last_mentioned_at = ?, "
                "updated_at = ? WHERE id = ?",
                (now, now, dup_id),
            )
            await self._db.commit()
            return dup_id

        # 3. New fact → insert
        cursor = await self._db.execute(
            "INSERT INTO facts "
            "(category, key, value, confidence, "
            "source, embedding, created_at, "
            "updated_at, last_mentioned_at, "
            "expires_at) "
            "VALUES "
            "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                category,
                key,
                value,
                confidence,
                source,
                embedding_blob,
                now,
                now,
                now,
                expires_at,
            ),
        )
        fact_id = cursor.lastrowid
        await self._db.commit()
        return fact_id

    async def correct_fact(
        self,
        category: str,
        key: str,
        new_value: str,
        confidence: float = 1.0,
    ) -> str:
        """Force-update a fact regardless of existing
        confidence. Used for explicit user corrections.
        """
        now = datetime.now(timezone.utc).isoformat()

        # Find existing fact by (category, key)
        cursor = await self._db.execute(
            "SELECT id FROM facts "
            "WHERE category = ? AND key = ?",
            (category, key),
        )
        existing = await cursor.fetchone()

        if existing:
            fact_id = existing[0]

            # Re-embed the new value
            embedding_blob = None
            embedding_vec = await self._embed_text(
                f"{key}: {new_value}"
            )
            if embedding_vec is not None:
                embedding_blob = (
                    _serialize_embedding(
                        embedding_vec.tolist()
                    )
                )

            await self._db.execute(
                "UPDATE facts SET value = ?, "
                "confidence = ?, "
                "embedding = ?, "
                "updated_at = ?, "
                "last_mentioned_at = ? "
                "WHERE id = ?",
                (
                    new_value,
                    confidence,
                    embedding_blob,
                    now,
                    now,
                    fact_id,
                ),
            )
            await self._db.commit()
            return (
                f"Updated: {key} → {new_value}"
            )

        # No existing fact found → store as new
        await self.store_fact(
            category=category,
            key=key,
            value=new_value,
            confidence=confidence,
            source="user",
        )
        return f"Updated: {key} → {new_value}"

    async def touch_fact(self, fact_id: int):
        """Update last_mentioned_at to now."""
        now = datetime.now(timezone.utc).isoformat()
        await self._db.execute(
            "UPDATE facts "
            "SET last_mentioned_at = ? "
            "WHERE id = ?",
            (now, fact_id),
        )
        await self._db.commit()

    async def decay_confidence(
        self,
        decay_rate: float = 0.01,
        min_confidence: float = 0.3,
    ) -> int:
        """Reduce confidence of facts not mentioned
        recently. Returns count of decayed facts.

        For each fact where last_mentioned_at is
        older than 30 days: multiply confidence by
        (1 - decay_rate) for each 30-day period
        since last mention. Don't go below
        min_confidence. Skip facts with
        source='user' (explicitly stated facts
        don't decay).
        """
        now = datetime.now(timezone.utc)
        thirty_days_secs = 30 * 24 * 3600
        decayed_count = 0

        cursor = await self._db.execute(
            "SELECT id, confidence, "
            "last_mentioned_at FROM facts "
            "WHERE source != 'user' "
            "AND last_mentioned_at IS NOT NULL"
        )
        rows = await cursor.fetchall()

        for row in rows:
            fact_id = row[0]
            confidence = row[1]
            last_mentioned = datetime.fromisoformat(
                row[2]
            )

            # Ensure timezone-aware comparison
            if last_mentioned.tzinfo is None:
                last_mentioned = (
                    last_mentioned.replace(tzinfo=timezone.utc)
                )

            age_secs = (
                now - last_mentioned
            ).total_seconds()

            if age_secs < thirty_days_secs:
                continue  # Not old enough to decay

            # Number of 30-day periods elapsed
            periods = int(
                age_secs // thirty_days_secs
            )

            new_conf = confidence * (
                (1 - decay_rate) ** periods
            )
            new_conf = max(new_conf, min_confidence)

            if new_conf < confidence:
                await self._db.execute(
                    "UPDATE facts "
                    "SET confidence = ? "
                    "WHERE id = ?",
                    (new_conf, fact_id),
                )
                decayed_count += 1

        if decayed_count > 0:
            await self._db.commit()

        return decayed_count

    async def cleanup_expired(self) -> int:
        """Delete facts past expires_at."""
        now = datetime.now(timezone.utc).isoformat()
        cursor = await self._db.execute(
            "DELETE FROM facts "
            "WHERE expires_at IS NOT NULL "
            "AND expires_at < ?",
            (now,),
        )
        await self._db.commit()
        return cursor.rowcount

    async def search_semantic(
        self, query: str, limit: int = 10
    ) -> list[dict]:
        """Search by semantic similarity."""
        if not self._embed_fn:
            return await self.search_keyword(
                query, limit
            )

        try:
            query_vec = await self._embed_text(
                query
            )
            if query_vec is None:
                return await self.search_keyword(
                    query, limit
                )

            query_norm = np.linalg.norm(query_vec)
            if query_norm == 0:
                return await self.search_keyword(
                    query, limit
                )

            # Exclude expired facts
            now = datetime.now(timezone.utc).isoformat()
            cursor = await self._db.execute(
                "SELECT id, category, key, value, "
                "confidence, created_at, "
                "updated_at, embedding "
                "FROM facts "
                "WHERE embedding IS NOT NULL "
                "AND (expires_at IS NULL "
                "OR expires_at >= ?)",
                (now,),
            )
            rows = await cursor.fetchall()

            if not rows:
                return await self.search_keyword(
                    query, limit
                )

            scored = []
            for row in rows:
                fact_emb = _deserialize_embedding(
                    row[7]
                )
                sim = _cosine_similarity(
                    query_vec, fact_emb
                )
                scored.append((sim, row))

            scored.sort(
                key=lambda x: x[0], reverse=True
            )

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
                        "similarity": round(
                            similarity, 4
                        ),
                    }
                )

            # Touch returned facts so they
            # don't decay while still relevant
            for r in results:
                await self.touch_fact(r["id"])

            return results

        except Exception as e:
            print(
                "[KnowledgeStore] Semantic search "
                f"error ({e}), falling back."
            )
            return await self.search_keyword(
                query, limit
            )

    async def search_keyword(
        self, query: str, limit: int = 10
    ) -> list[dict]:
        """Fallback keyword search using LIKE."""
        now = datetime.now(timezone.utc).isoformat()
        cursor = await self._db.execute(
            "SELECT id, category, key, value, "
            "confidence, created_at, updated_at "
            "FROM facts "
            "WHERE (key LIKE ? OR value LIKE ?) "
            "AND (expires_at IS NULL "
            "OR expires_at >= ?) "
            "ORDER BY updated_at DESC LIMIT ?",
            (
                f"%{query}%",
                f"%{query}%",
                now,
                limit,
            ),
        )
        rows = await cursor.fetchall()
        results = [
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

        # Touch returned facts so they
        # don't decay while still relevant
        for r in results:
            await self.touch_fact(r["id"])

        return results

    async def get_all_facts(
        self,
        category: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        """Get all facts, optionally by category."""
        now = datetime.now(timezone.utc).isoformat()
        if category:
            cursor = await self._db.execute(
                "SELECT id, category, key, value, "
                "confidence, created_at, updated_at "
                "FROM facts WHERE category = ? "
                "AND (expires_at IS NULL "
                "OR expires_at >= ?) "
                "ORDER BY updated_at DESC LIMIT ?",
                (category, now, limit),
            )
        else:
            cursor = await self._db.execute(
                "SELECT id, category, key, value, "
                "confidence, created_at, updated_at "
                "FROM facts "
                "WHERE expires_at IS NULL "
                "OR expires_at >= ? "
                "ORDER BY updated_at DESC LIMIT ?",
                (now, limit),
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
            "SELECT id FROM facts "
            "WHERE key LIKE ?",
            (f"%{key}%",),
        )
        row = await cursor.fetchone()
        if not row:
            return False

        await self._db.execute(
            "DELETE FROM facts WHERE id = ?",
            (row[0],),
        )
        await self._db.commit()
        return True

    async def close(self):
        if self._db:
            await self._db.close()
