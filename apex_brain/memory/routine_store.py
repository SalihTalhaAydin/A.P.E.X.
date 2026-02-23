"""
Routine Store - Dedicated storage for named multi-step routines.

Stores routines with lifecycle metadata (use_count, last_used_at)
in a dedicated SQLite table, separate from the knowledge store.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from datetime import datetime, timezone

from memory.db_manager import SharedDbConnection

logger = logging.getLogger(__name__)


class RoutineStore:
    """Dedicated storage for routines with metadata tracking."""

    def __init__(self, db_path: str | SharedDbConnection):
        if isinstance(db_path, SharedDbConnection):
            self._shared = db_path
            self._own_connection = False
        else:
            self._shared = SharedDbConnection(db_path)
            self._own_connection = True

    async def initialize(self):
        """Create tables if they don't exist."""
        if self._own_connection:
            await self._shared.initialize()

        async with self._shared.lock:
            db = self._shared.connection
            await db.execute("""
                CREATE TABLE IF NOT EXISTS routines (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    steps TEXT NOT NULL,
                    trigger_hint TEXT DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_used_at TEXT,
                    use_count INTEGER DEFAULT 0,
                    source TEXT DEFAULT 'user',
                    enabled INTEGER DEFAULT 1
                )
            """)
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_routines_name
                ON routines(name COLLATE NOCASE)
            """)
            await db.commit()

    def _ensure_db(self):
        if not self._shared.is_initialized:
            raise RuntimeError("Store not initialized. Call initialize() first.")

    async def save_routine(
        self,
        name: str,
        steps: list[str],
        trigger: str = "",
        source: str = "user",
    ) -> int:
        """Save or update a routine. Returns the row ID."""
        self._ensure_db()
        now = datetime.now(timezone.utc).isoformat()
        steps_json = json.dumps(steps)
        name_norm = name.lower().strip()

        async with self._shared.lock:
            db = self._shared.connection
            await db.execute("BEGIN IMMEDIATE")
            try:
                cursor = await db.execute(
                    "SELECT id FROM routines WHERE name = ?",
                    (name_norm,),
                )
                existing = await cursor.fetchone()

                if existing:
                    await db.execute(
                        "UPDATE routines SET steps = ?, trigger_hint = ?, "
                        "updated_at = ?, source = ? WHERE id = ?",
                        (steps_json, trigger, now, source, existing[0]),
                    )
                    await db.commit()
                    return existing[0]

                try:
                    cursor = await db.execute(
                        "INSERT INTO routines "
                        "(name, steps, trigger_hint, created_at, updated_at, source) "
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        (name_norm, steps_json, trigger, now, now, source),
                    )
                    await db.commit()
                    return cursor.lastrowid
                except sqlite3.IntegrityError:
                    # Race: another task inserted first. Rollback, get id, update.
                    try:
                        await db.rollback()
                    except Exception as rb_err:
                        logger.error("save_routine ROLLBACK failed: %s", rb_err)
                        raise
                    await db.execute("BEGIN IMMEDIATE")
                    cursor = await db.execute(
                        "SELECT id FROM routines WHERE name = ?",
                        (name_norm,),
                    )
                    existing = await cursor.fetchone()
                    if existing:
                        await db.execute(
                            "UPDATE routines SET steps = ?, trigger_hint = ?, "
                            "updated_at = ?, source = ? WHERE id = ?",
                            (steps_json, trigger, now, source, existing[0]),
                        )
                        await db.commit()
                        return existing[0]
                    raise
            except Exception:
                try:
                    await db.rollback()
                except Exception as rb_err:
                    logger.error("save_routine ROLLBACK failed: %s", rb_err)
                raise

    async def get_routine(self, name: str) -> dict | None:
        """Get a routine by name (case-insensitive)."""
        self._ensure_db()

        async with self._shared.lock:
            db = self._shared.connection
            cursor = await db.execute(
                "SELECT id, name, steps, trigger_hint, created_at, "
                "updated_at, last_used_at, use_count, source, enabled "
                "FROM routines WHERE name = ?",
                (name.lower().strip(),),
            )
            row = await cursor.fetchone()

        if not row:
            return None
        return self._row_to_dict(row)

    async def list_routines(
        self, include_disabled: bool = False
    ) -> list[dict]:
        """List all routines with metadata."""
        self._ensure_db()
        query = (
            "SELECT id, name, steps, trigger_hint, created_at, "
            "updated_at, last_used_at, use_count, source, enabled "
            "FROM routines"
        )
        if not include_disabled:
            query += " WHERE enabled = 1"
        query += " ORDER BY use_count DESC, updated_at DESC"

        async with self._shared.lock:
            db = self._shared.connection
            cursor = await db.execute(query)
            rows = await cursor.fetchall()

        return [self._row_to_dict(row) for row in rows]

    async def record_usage(self, name: str) -> None:
        """Increment use_count and set last_used_at."""
        self._ensure_db()
        now = datetime.now(timezone.utc).isoformat()

        async with self._shared.lock:
            db = self._shared.connection
            await db.execute(
                "UPDATE routines SET use_count = use_count + 1, "
                "last_used_at = ? WHERE name = ?",
                (now, name.lower().strip()),
            )
            await db.commit()

    async def get_stale_routines(self, days: int = 90) -> list[dict]:
        """Get routines not used in N days."""
        self._ensure_db()

        async with self._shared.lock:
            db = self._shared.connection
            cursor = await db.execute(
                "SELECT id, name, steps, trigger_hint, created_at, "
                "updated_at, last_used_at, use_count, source, enabled "
                "FROM routines WHERE enabled = 1 AND ("
                "  last_used_at IS NULL AND "
                "  julianday('now', 'utc') - julianday(created_at) > ? "
                "  OR "
                "  last_used_at IS NOT NULL AND "
                "  julianday('now', 'utc') - julianday(last_used_at) > ?"
                ")",
                (days, days),
            )
            rows = await cursor.fetchall()

        return [self._row_to_dict(row) for row in rows]

    async def delete_routine(self, name: str) -> bool:
        """Delete a routine by name."""
        self._ensure_db()

        async with self._shared.lock:
            db = self._shared.connection
            cursor = await db.execute(
                "DELETE FROM routines WHERE name = ?",
                (name.lower().strip(),),
            )
            await db.commit()
            return cursor.rowcount > 0

    async def migrate_from_knowledge_store(self, knowledge_store) -> int:
        """One-time migration of routines from knowledge_store facts table."""
        self._ensure_db()
        migrated = 0
        try:
            facts = await knowledge_store.get_all_facts(
                category="routine", limit=100
            )
            for fact in facts:
                existing = await self.get_routine(fact["key"])
                if not existing:
                    # Parse steps from the stored value
                    value = fact["value"]
                    # Remove trigger hint prefix if present
                    if value.startswith("[trigger:"):
                        idx = value.find("]")
                        if idx != -1:
                            value = value[idx + 1 :].strip()
                    # Split on newlines or sentence-ending
                    # periods followed by a space (legacy format)
                    parts = re.split(r"\n|(?<=\.)\s+", value)
                    steps = [
                        s.strip().rstrip(".") for s in parts if s.strip()
                    ]
                    await self.save_routine(
                        fact["key"], steps, source="migrated"
                    )
                    migrated += 1
            if migrated:
                logger.info(
                    "Migrated %d routines from knowledge store", migrated
                )
        except Exception as e:
            logger.warning("Routine migration error: %s", e)
        return migrated

    async def close(self):
        """Close the database connection."""
        if self._own_connection:
            await self._shared.close()

    @staticmethod
    def _row_to_dict(row) -> dict:
        """Convert a database row to a dict."""
        steps = row[2]
        try:
            steps = json.loads(steps)
        except (json.JSONDecodeError, TypeError):
            steps = [steps] if steps else []
        return {
            "id": row[0],
            "name": row[1],
            "steps": steps,
            "trigger_hint": row[3],
            "created_at": row[4],
            "updated_at": row[5],
            "last_used_at": row[6],
            "use_count": row[7],
            "source": row[8],
            "enabled": bool(row[9]),
        }
