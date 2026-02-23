"""
Knowledge Store - Facts about the user with semantic search.
Uses numpy cosine similarity over embeddings in SQLite.
Simple, portable, no extensions needed.

v0.3.0: deduplication, conflict resolution, temporal metadata.
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
import struct
from datetime import datetime, timezone

import aiosqlite
import numpy as np

from memory.db_manager import SharedDbConnection

logger = logging.getLogger(__name__)


def _serialize_embedding(
    embedding: list[float],
) -> bytes:
    """Convert a list of floats to bytes."""
    return struct.pack(f"{len(embedding)}f", *embedding)


def _deserialize_embedding(
    blob: bytes,
) -> np.ndarray:
    """Convert bytes back to a numpy array.

    Contract:
        - Empty blob: returns empty float32 array.
        - Blob length must be divisible by 4 (4 bytes per float32).
        - Truncated or corrupt blobs raise ValueError to avoid silent corruption.
    """
    if len(blob) == 0:
        return np.array([], dtype=np.float32)
    if len(blob) % 4 != 0:
        raise ValueError(
            f"Embedding blob length {len(blob)} is not divisible by 4; "
            "expected float32 values (4 bytes each)"
        )
    dim = len(blob) // 4
    return np.array(
        struct.unpack(f"{dim}f", blob),
        dtype=np.float32,
    )


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity between two vectors."""
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))


class KnowledgeStore:
    """Stores and retrieves user facts with
    semantic search via embeddings."""

    def __init__(self, db_path: str | SharedDbConnection):
        if isinstance(db_path, SharedDbConnection):
            self._shared = db_path
            self._own_connection = False
        else:
            self._shared = SharedDbConnection(db_path)
            self._own_connection = True
        self._embed_fn = None
        self._embed_warned = False

    def set_embed_function(self, fn):
        """Set the embedding function."""
        self._embed_fn = fn

    async def initialize(self):
        """Create tables if they don't exist."""
        if self._own_connection:
            await self._shared.initialize()

        async with self._shared.lock:
            db = self._shared.connection
            try:
                db._conn.isolation_level = None  # manual transactions for correct_fact
            except (sqlite3.ProgrammingError, OSError):
                # SQLite thread affinity: connection created in executor thread
                pass
            await db.execute("""
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
            await db.execute("""
                CREATE INDEX IF NOT EXISTS
                idx_facts_category ON facts(category)
            """)
            await db.execute("""
                CREATE INDEX IF NOT EXISTS
                idx_facts_key ON facts(key)
            """)

            # v0.3.0 schema migration: add temporal cols
            cursor = await db.execute("PRAGMA table_info(facts)")
            cols = {row[1] for row in await cursor.fetchall()}

            if "last_mentioned_at" not in cols:
                await db.execute(
                    "ALTER TABLE facts ADD COLUMN last_mentioned_at TEXT"
                )
            if "expires_at" not in cols:
                await db.execute(
                    "ALTER TABLE facts ADD COLUMN expires_at TEXT"
                )

            # Unique constraint on (category, key) to prevent duplicates
            await db.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS
                idx_facts_cat_key ON facts(category, key)
            """)
            await db.commit()

    def _ensure_db(self):
        if not self._shared.is_initialized:
            raise RuntimeError("Store not initialized. Call initialize() first.")

    def _extract_embedding_from_response(self, response) -> list[float] | None:
        """Extract embedding list from embed function response.

        Handles: (1) dict with 'embedding' key, (2) object with .embedding
        attribute, (3) raw list of floats, (4) LiteLLM-style data[0].embedding.
        Only returns a valid list of numbers; returns None if not extractable.
        """
        if response is None:
            return None

        # (3) Raw list or tuple of floats
        if isinstance(response, (list, tuple)) and len(response) > 0:
            if all(isinstance(x, (int, float)) for x in response):
                return list(response)
            return None

        # (1) Dict with top-level 'embedding' key
        if isinstance(response, dict):
            emb = response.get("embedding")
            if emb is not None and isinstance(emb, (list, tuple)):
                if len(emb) > 0 and all(isinstance(x, (int, float)) for x in emb):
                    return list(emb)
            # LiteLLM-style: response["data"][0]["embedding"] or [0].embedding
            data = response.get("data")
            if data and len(data) > 0:
                item = data[0]
                if isinstance(item, dict):
                    emb = item.get("embedding")
                else:
                    emb = getattr(item, "embedding", None)
                if emb is not None and isinstance(emb, (list, tuple)):
                    if len(emb) > 0 and all(isinstance(x, (int, float)) for x in emb):
                        return list(emb)
            return None

        # (2) Object with .embedding attribute
        emb = getattr(response, "embedding", None)
        if emb is not None and isinstance(emb, (list, tuple)):
            if len(emb) > 0 and all(isinstance(x, (int, float)) for x in emb):
                return list(emb)

        # Object with .data (LiteLLM-style)
        data = getattr(response, "data", None)
        if data and len(data) > 0:
            item = data[0]
            if isinstance(item, dict):
                emb = item.get("embedding")
            else:
                emb = getattr(item, "embedding", None)
            if emb is not None and isinstance(emb, (list, tuple)):
                if len(emb) > 0 and all(isinstance(x, (int, float)) for x in emb):
                    return list(emb)

        return None

    async def _embed_text(self, text: str) -> np.ndarray | None:
        """Get embedding vector for text."""
        if not self._embed_fn:
            if not self._embed_warned:
                logger.warning(
                    "No embedding function set — semantic "
                    "search and deduplication are disabled. "
                    "Call set_embed_function() to enable."
                )
                self._embed_warned = True
            return None
        try:
            response = await self._embed_fn(text)
            emb_list = self._extract_embedding_from_response(response)
            if emb_list is not None:
                # Bug 77 (P5-BUG-85): Only convert if we have a sequence of numbers.
                # If embed_fn returns a complex object (LiteLLM, dict, etc.), np.array()
                # would create invalid object array and break cosine similarity.
                if (
                    isinstance(emb_list, (list, tuple))
                    and len(emb_list) > 0
                    and all(isinstance(x, (int, float)) for x in emb_list)
                ):
                    return np.array(emb_list, dtype=np.float32)
                # Non-numeric structure — treat as non-extractable
                emb_list = None
            # Bug 77 (P5-BUG-85): When extraction failed, do not blindly pass response
            # to np.array(). Only use it if it's already a list/array of numbers.
            if emb_list is None and response is not None:
                if isinstance(response, (list, tuple)) and len(response) > 0:
                    if all(isinstance(x, (int, float)) for x in response):
                        return np.array(response, dtype=np.float32)
                elif isinstance(response, np.ndarray) and response.size > 0:
                    if np.issubdtype(response.dtype, np.floating) or np.issubdtype(
                        response.dtype, np.integer
                    ):
                        return np.asarray(response, dtype=np.float32)
                logger.warning(
                    "[KnowledgeStore] Embed function returned non-extractable structure "
                    "(type=%s); expected embedding list, dict with 'embedding', or object with .embedding",
                    type(response).__name__,
                )
        except Exception as e:
            logger.error("[KnowledgeStore] Embedding error: %s", e)
        return None

    async def _check_duplicate(
        self,
        db: aiosqlite.Connection,
        category: str,
        value: str,
        new_embedding: np.ndarray | None,
        threshold: float = 0.92,
    ) -> int | None:
        """Check for semantically duplicate fact.

        Returns existing fact ID if duplicate found.
        Caller must hold self._shared.lock.
        """
        if new_embedding is None:
            return None

        cursor = await db.execute(
            "SELECT id, embedding FROM facts "
            "WHERE category = ? "
            "AND embedding IS NOT NULL "
            "ORDER BY updated_at DESC LIMIT 500",
            (category,),
        )
        rows = await cursor.fetchall()

        for row in rows:
            existing = _deserialize_embedding(row[1])
            sim = _cosine_similarity(new_embedding, existing)
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
        _lock_held: bool = False,
    ) -> int:
        """Store a fact with dedup + conflict
        resolution.

        If same (category, key) exists: update if
        new confidence >= old. If semantically
        duplicate value exists: update the existing
        fact with the new key, value, confidence,
        embedding, last_mentioned_at, updated_at
        (Bug 76 / P8-BUG-137).
        When force=True, skip confidence comparison
        and always update (used for corrections).

        _lock_held: True when called from correct_fact (caller holds lock).
        """
        self._ensure_db()
        now = datetime.now(timezone.utc).isoformat()

        # Generate embedding (outside lock - may call embed API)
        embedding_blob = None
        embedding_vec = await self._embed_text(f"{key}: {value}")
        if embedding_vec is not None:
            embedding_blob = _serialize_embedding(embedding_vec.tolist())
        elif self._embed_fn is not None:
            # BUG-76: Embed failed; fact will be stored with NULL embedding
            # and excluded from semantic search
            logger.warning(
                "[KnowledgeStore] Embedding failed for fact '%s: %s'; "
                "stored without embedding (invisible to semantic search).",
                key,
                (value or "")[:50],
            )

        async def _do_store(db: aiosqlite.Connection) -> int:
            try:
                cursor = await db.execute(
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

                    if old_value == value:
                        await db.execute(
                            "UPDATE facts "
                            "SET last_mentioned_at = ?, "
                            "updated_at = ? "
                            "WHERE id = ?",
                            (now, now, fact_id),
                        )
                        await db.commit()
                        return fact_id

                    if force or confidence >= old_conf:
                        await db.execute(
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
                        await db.commit()
                        return fact_id
                    await db.commit()
                    return fact_id

                dup_id = await self._check_duplicate(
                    db, category, value, embedding_vec
                )
                if dup_id is not None:
                    await db.execute(
                        "UPDATE facts SET key = ?, value = ?, confidence = ?, "
                        "embedding = ?, last_mentioned_at = ?, updated_at = ?, "
                        "expires_at = ?, source = ? WHERE id = ?",
                        (
                            key,
                            value,
                            confidence,
                            embedding_blob,
                            now,
                            now,
                            expires_at,
                            source,
                            dup_id,
                        ),
                    )
                    await db.commit()
                    return dup_id

                cursor = await db.execute(
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
                await db.commit()
                return fact_id
            except Exception:
                try:
                    await db.rollback()
                except Exception as rb_err:
                    logger.error(
                        "[KnowledgeStore] ROLLBACK failed: %s",
                        rb_err,
                    )
                raise

        db = self._shared.connection
        if _lock_held:
            return await _do_store(db)
        async with self._shared.lock:
            return await _do_store(db)

    async def correct_fact(
        self,
        category: str,
        key: str,
        new_value: str,
        confidence: float = 1.0,
    ) -> str:
        """Force-update a fact regardless of existing
        confidence. Used for explicit user corrections.

        Wraps SELECT + UPDATE/INSERT in a transaction (BEGIN IMMEDIATE)
        so concurrent tasks cannot delete the fact between SELECT and
        UPDATE, or insert a duplicate between SELECT and store_fact.
        """
        self._ensure_db()
        now = datetime.now(timezone.utc).isoformat()

        async with self._shared.lock:
            db = self._shared.connection
            await db.execute("BEGIN IMMEDIATE")
            try:
                cursor = await db.execute(
                    "SELECT id FROM facts WHERE category = ? AND key = ?",
                    (category, key),
                )
                existing = await cursor.fetchone()

                if existing:
                    fact_id = existing[0]
                    embedding_blob = None
                    embedding_vec = await self._embed_text(
                        f"{key}: {new_value}"
                    )
                    if embedding_vec is not None:
                        embedding_blob = _serialize_embedding(
                            embedding_vec.tolist()
                        )

                    update_cursor = await db.execute(
                        "UPDATE facts SET value = ?, "
                        "confidence = ?, "
                        "embedding = ?, "
                        "updated_at = ?, "
                        "last_mentioned_at = ?, "
                        "source = ? "
                        "WHERE id = ?",
                        (
                            new_value,
                            confidence,
                            embedding_blob,
                            now,
                            now,
                            "user",
                            fact_id,
                        ),
                    )
                    await db.commit()

                    if update_cursor.rowcount > 0:
                        return f"Updated: {key} → {new_value}"
                else:
                    # Fact does not exist: release exclusive lock before store_fact.
                    # store_fact will run _check_duplicate (scans up to 200 facts);
                    # holding BEGIN IMMEDIATE during that scan blocks all writers.
                    await db.rollback()

                await self.store_fact(
                    category=category,
                    key=key,
                    value=new_value,
                    confidence=confidence,
                    source="user",
                    _lock_held=True,
                )
                return f"Updated: {key} → {new_value}"
            except Exception:
                try:
                    await db.rollback()
                except Exception as rb_err:
                    logger.error(
                        "[KnowledgeStore] ROLLBACK failed: %s",
                        rb_err,
                    )
                raise

    async def touch_fact(self, fact_id: int):
        """Update last_mentioned_at to now."""
        self._ensure_db()
        now = datetime.now(timezone.utc).isoformat()
        async with self._shared.lock:
            db = self._shared.connection
            await db.execute(
                "UPDATE facts SET last_mentioned_at = ? WHERE id = ?",
                (now, fact_id),
            )
            await db.commit()

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
        self._ensure_db()
        now = datetime.now(timezone.utc)
        thirty_days_secs = 30 * 24 * 3600
        decayed_count = 0

        async with self._shared.lock:
            db = self._shared.connection
            cursor = await db.execute(
                "SELECT id, confidence, "
                "last_mentioned_at FROM facts "
                "WHERE source != 'user' "
                "AND last_mentioned_at IS NOT NULL"
            )
            rows = await cursor.fetchall()

            for row in rows:
                fact_id = row[0]
                confidence = row[1]
                last_mentioned = datetime.fromisoformat(row[2])

                # Normalize to UTC for age calculation. Naive timestamps (no tz
                # in DB string) are assumed UTC; aware timestamps must use
                # astimezone() to convert — replace() would overwrite without
                # converting and produce wrong age for non-UTC zones.
                if last_mentioned.tzinfo is None:
                    logger.debug(
                        "Fact %s has naive timestamp, assuming UTC",
                        fact_id,
                    )
                    last_mentioned = last_mentioned.replace(
                        tzinfo=timezone.utc
                    )
                else:
                    last_mentioned = last_mentioned.astimezone(timezone.utc)

                age_secs = (now - last_mentioned).total_seconds()

                if age_secs < thirty_days_secs:
                    continue

                periods = int(age_secs // thirty_days_secs)
                new_conf = confidence * ((1 - decay_rate) ** periods)
                new_conf = max(new_conf, min_confidence)

                if new_conf < confidence:
                    await db.execute(
                        "UPDATE facts SET confidence = ? WHERE id = ?",
                        (new_conf, fact_id),
                    )
                    decayed_count += 1

            if decayed_count > 0:
                await db.commit()

        return decayed_count

    async def cleanup_expired(self) -> int:
        """Delete facts past expires_at."""
        self._ensure_db()
        now = datetime.now(timezone.utc).isoformat()
        async with self._shared.lock:
            db = self._shared.connection
            cursor = await db.execute(
                "DELETE FROM facts "
                "WHERE expires_at IS NOT NULL "
                "AND expires_at < ?",
                (now,),
            )
            await db.commit()
            return cursor.rowcount

    async def search_semantic(
        self, query: str, limit: int = 10, update_last_mentioned: bool = False
    ) -> list[dict]:
        """Search by semantic similarity.

        Args:
            query: Search query text.
            limit: Max number of results.
            update_last_mentioned: If True, update last_mentioned_at for
                returned facts (used by decay). Default False to avoid write
                pressure on read-heavy paths like context builds.
        """
        self._ensure_db()
        if not self._embed_fn:
            return await self.search_keyword(
                query, limit, update_last_mentioned
            )

        try:
            query_vec = await self._embed_text(query)
            if query_vec is None:
                return await self.search_keyword(
                    query, limit, update_last_mentioned
                )

            query_norm = np.linalg.norm(query_vec)
            if query_norm == 0:
                return await self.search_keyword(
                    query, limit, update_last_mentioned
                )

            _CANDIDATE_LIMIT = 500
            now = datetime.now(timezone.utc).isoformat()

            async with self._shared.lock:
                db = self._shared.connection
                cursor = await db.execute(
                    "SELECT id, category, key, value, "
                    "confidence, created_at, "
                    "updated_at, embedding "
                    "FROM facts "
                    "WHERE embedding IS NOT NULL "
                    "AND (expires_at IS NULL "
                    "OR expires_at >= ?) "
                    "LIMIT ?",
                    (now, _CANDIDATE_LIMIT),
                )
                rows = await cursor.fetchall()

            if not rows:
                return await self.search_keyword(
                    query, limit, update_last_mentioned
                )

            scored = []
            for i, row in enumerate(rows):
                if i > 0 and i % 50 == 0:
                    await asyncio.sleep(0)
                fact_emb = _deserialize_embedding(row[7])
                sim = _cosine_similarity(query_vec, fact_emb)
                scored.append((sim, row))

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

            # Batch-touch only facts above a minimum
            # similarity threshold to prevent irrelevant
            # facts from being kept alive indefinitely.
            # Skip when update_last_mentioned=False to avoid write
            # pressure on read-heavy paths (e.g. context builds).
            _MIN_TOUCH_SIMILARITY = 0.4
            if results and update_last_mentioned:
                to_touch = [
                    r["id"]
                    for r in results
                    if r.get("similarity", 0)
                    >= _MIN_TOUCH_SIMILARITY
                ]
                if to_touch:
                    placeholders = ",".join(
                        "?" * len(to_touch)
                    )
                    touch_now = (
                        datetime.now(timezone.utc).isoformat()
                    )
                    async with self._shared.lock:
                        db = self._shared.connection
                        await db.execute(
                            "UPDATE facts "
                            "SET last_mentioned_at = ? "
                            f"WHERE id IN ({placeholders})",
                            [touch_now] + to_touch,
                        )
                        await db.commit()

            return results

        except Exception as e:
            logger.warning(
                "[KnowledgeStore] Semantic search error (%s), falling back.",
                e,
            )
            return await self.search_keyword(
                query, limit, update_last_mentioned
            )

    async def search_keyword(
        self, query: str, limit: int = 10, update_last_mentioned: bool = False
    ) -> list[dict]:
        """Fallback keyword search using LIKE.

        Args:
            query: Search query text.
            limit: Max number of results.
            update_last_mentioned: If True, update last_mentioned_at for
                returned facts. Default False to avoid write pressure on
                read-heavy paths like context builds.
        """
        self._ensure_db()
        now = datetime.now(timezone.utc).isoformat()
        escaped = (
            query.replace("\\", "\\\\")
            .replace("%", "\\%")
            .replace("_", "\\_")
        )

        async with self._shared.lock:
            db = self._shared.connection
            cursor = await db.execute(
                "SELECT id, category, key, value, "
                "confidence, created_at, updated_at "
                "FROM facts "
                "WHERE (key LIKE ? ESCAPE '\\' "
                "OR value LIKE ? ESCAPE '\\') "
                "AND (expires_at IS NULL "
                "OR expires_at >= ?) "
                "ORDER BY updated_at DESC LIMIT ?",
                (
                    f"%{escaped}%",
                    f"%{escaped}%",
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

        # Batch-touch returned facts so they don't decay while still relevant.
        # Skip when update_last_mentioned=False to avoid write pressure on
        # read-heavy paths (e.g. context builds).
        if results and update_last_mentioned:
            ids = [r["id"] for r in results]
            placeholders = ",".join("?" * len(ids))
            touch_now = datetime.now(timezone.utc).isoformat()
            async with self._shared.lock:
                db = self._shared.connection
                await db.execute(
                    f"UPDATE facts SET last_mentioned_at = ? "
                    f"WHERE id IN ({placeholders})",
                    [touch_now] + ids,
                )
                await db.commit()

        return results

    async def get_due_reminders(self, limit: int = 20) -> list[dict]:
        """Get reminders that are due (expires_at <= now).

        Uses proper datetime parsing instead of string comparison
        so that different timezone offsets and ISO format variations
        are handled correctly.

        Returns facts with id, category, key, value, confidence,
        created_at, updated_at, expires_at.
        """
        self._ensure_db()
        now = datetime.now(timezone.utc)
        async with self._shared.lock:
            db = self._shared.connection
            cursor = await db.execute(
                "SELECT id, category, key, value, confidence, "
                "created_at, updated_at, expires_at "
                "FROM facts "
                "WHERE category = 'reminder' "
                "AND expires_at IS NOT NULL "
                "ORDER BY expires_at ASC",
            )
            rows = await cursor.fetchall()
        due: list[dict] = []
        for r in rows:
            try:
                expires = datetime.fromisoformat(r[7])
                # Treat naive timestamps as UTC
                if expires.tzinfo is None:
                    expires = expires.replace(tzinfo=timezone.utc)
                if expires <= now:
                    due.append(
                        {
                            "id": r[0],
                            "category": r[1],
                            "key": r[2],
                            "value": r[3],
                            "confidence": r[4],
                            "created_at": r[5],
                            "updated_at": r[6],
                            "expires_at": r[7],
                        }
                    )
                    if len(due) >= limit:
                        break
            except (ValueError, TypeError):
                logger.warning(
                    "Skipping reminder id=%s with invalid "
                    "expires_at: %s",
                    r[0],
                    r[7],
                )
        return due

    async def get_all_facts(
        self,
        category: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        """Get all facts, optionally by category."""
        self._ensure_db()
        now = datetime.now(timezone.utc).isoformat()
        async with self._shared.lock:
            db = self._shared.connection
            if category:
                cursor = await db.execute(
                    "SELECT id, category, key, value, "
                    "confidence, created_at, updated_at "
                    "FROM facts WHERE category = ? "
                    "AND (expires_at IS NULL "
                    "OR expires_at >= ?) "
                    "ORDER BY updated_at DESC LIMIT ?",
                    (category, now, limit),
                )
            else:
                cursor = await db.execute(
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

    async def delete_fact(
        self, key: str, category: str = ""
    ) -> bool:
        """Delete a fact by key (exact match only).

        If category is provided, only delete the fact
        matching both (category, key).
        """
        self._ensure_db()
        async with self._shared.lock:
            db = self._shared.connection
            if category:
                cursor = await db.execute(
                    "DELETE FROM facts WHERE key = ? AND category = ?",
                    (key, category),
                )
            else:
                cursor = await db.execute(
                    "DELETE FROM facts WHERE key = ?",
                    (key,),
                )
            await db.commit()
            return cursor.rowcount > 0

    async def get_low_confidence_facts(
        self, threshold: float = 0.4, limit: int = 50
    ) -> list[dict]:
        """Get facts with confidence below threshold (candidates for pruning)."""
        self._ensure_db()
        now = datetime.now(timezone.utc).isoformat()
        async with self._shared.lock:
            db = self._shared.connection
            cursor = await db.execute(
                "SELECT id, category, key, value, confidence, "
                "created_at, updated_at FROM facts "
                "WHERE confidence < ? "
                "AND (expires_at IS NULL OR expires_at >= ?) "
                "ORDER BY confidence ASC LIMIT ?",
                (threshold, now, limit),
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

    async def get_stale_facts(
        self, days: int = 90, limit: int = 50
    ) -> list[dict]:
        """Get facts not mentioned in N days."""
        self._ensure_db()
        async with self._shared.lock:
            db = self._shared.connection
            cursor = await db.execute(
                "SELECT id, category, key, value, confidence, "
                "created_at, updated_at, last_mentioned_at FROM facts "
                "WHERE last_mentioned_at IS NOT NULL "
                "AND julianday('now', 'utc') - julianday(last_mentioned_at) > ? "
                "ORDER BY last_mentioned_at ASC LIMIT ?",
                (days, limit),
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
                "last_mentioned_at": r[7],
            }
            for r in rows
        ]

    async def get_contradictory_facts(
        self,
        similarity_threshold: float = 0.85,
        limit: int = 200,
    ) -> list[tuple[dict, dict]]:
        """Find facts that are semantically similar but have conflicting values.

        With UNIQUE(category, key), same-key contradictions are impossible.
        This method detects semantic contradictions: facts with similar
        meaning (embedding cosine similarity >= threshold) but different
        values. Only considers facts that have embeddings.

        Returns list of (fact_a, fact_b) tuples where the facts are
        semantically similar but their values differ significantly.
        """
        self._ensure_db()
        now = datetime.now(timezone.utc).isoformat()
        async with self._shared.lock:
            db = self._shared.connection
            cursor = await db.execute(
                "SELECT id, category, key, value, confidence, "
                "created_at, updated_at, embedding "
                "FROM facts "
                "WHERE embedding IS NOT NULL "
                "AND (expires_at IS NULL OR expires_at >= ?) "
                "ORDER BY updated_at DESC LIMIT ?",
                (now, limit),
            )
            rows = await cursor.fetchall()
        if len(rows) < 2:
            return []

        def _norm_val(v: str) -> str:
            return (v or "").strip().lower()

        results: list[tuple[dict, dict]] = []
        facts = []
        for r in rows:
            facts.append(
                {
                    "id": r[0],
                    "category": r[1],
                    "key": r[2],
                    "value": r[3],
                    "confidence": r[4],
                    "created_at": r[5],
                    "updated_at": r[6],
                    "_emb": _deserialize_embedding(r[7]),
                }
            )

        for i in range(len(facts)):
            for j in range(i + 1, len(facts)):
                a, b = facts[i], facts[j]
                sim = _cosine_similarity(a["_emb"], b["_emb"])
                if sim < similarity_threshold:
                    continue
                if _norm_val(a["value"]) == _norm_val(b["value"]):
                    continue
                fa = {k: v for k, v in a.items() if k != "_emb"}
                fb = {k: v for k, v in b.items() if k != "_emb"}
                results.append((fa, fb))
        return results

    async def delete_fact_by_id(self, fact_id: int) -> bool:
        """Delete a fact by its ID."""
        self._ensure_db()
        async with self._shared.lock:
            db = self._shared.connection
            cursor = await db.execute(
                "DELETE FROM facts WHERE id = ?", (fact_id,)
            )
            await db.commit()
            return cursor.rowcount > 0

    async def close(self):
        if self._own_connection:
            await self._shared.close()
