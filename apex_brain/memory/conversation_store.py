"""
Conversation Store - Saves every conversation turn permanently.
Never lose context. Every Apex interaction is searchable.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from memory.db_manager import SharedDbConnection


class ConversationStore:
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
                CREATE TABLE IF NOT EXISTS conversations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    session_id TEXT DEFAULT 'default'
                )
            """)
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_conv_timestamp
                ON conversations(timestamp DESC)
            """)
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_conv_session
                ON conversations(session_id, timestamp DESC)
            """)
            await db.commit()

    def _ensure_db(self) -> None:
        """Ensure DB is initialized and not closed. Call before any DB access."""
        if not self._shared.is_initialized:
            raise RuntimeError(
                "Store not initialized or already closed. Call initialize() first."
            )

    async def save_turn(
        self, role: str, content: str, session_id: str = "default"
    ):
        """Save a conversation turn (user or assistant)."""
        self._ensure_db()
        if not content or not content.strip():
            return
        content = (content.strip() or "")[:10000]
        now = datetime.now(timezone.utc).isoformat()

        async with self._shared.lock:
            db = self._shared.connection
            await db.execute(
                "INSERT INTO conversations (role, content, timestamp, session_id) VALUES (?, ?, ?, ?)",
                (role, content, now, session_id),
            )
            await db.commit()

    async def get_recent(
        self, n: int = 10, session_id: str | None = None
    ) -> list[dict]:
        """Get the last N conversation turns, newest last (chronological order)."""
        self._ensure_db()

        async with self._shared.lock:
            db = self._shared.connection
            if session_id:
                cursor = await db.execute(
                    "SELECT role, content, timestamp FROM conversations "
                    "WHERE session_id = ? ORDER BY id DESC LIMIT ?",
                    (session_id, n),
                )
            else:
                cursor = await db.execute(
                    "SELECT role, content, timestamp FROM conversations "
                    "ORDER BY id DESC LIMIT ?",
                    (n,),
                )
            rows = await cursor.fetchall()

        # Reverse so oldest is first (chronological)
        return [
            {"role": r[0], "content": r[1], "timestamp": r[2]}
            for r in reversed(rows)
        ]

    @staticmethod
    def _escape_like(s: str) -> str:
        return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

    async def search(self, query: str, limit: int = 20) -> list[dict]:
        """Search conversation history by keyword."""
        self._ensure_db()
        escaped = self._escape_like(query)

        async with self._shared.lock:
            db = self._shared.connection
            cursor = await db.execute(
                "SELECT role, content, timestamp FROM conversations "
                "WHERE content LIKE ? ESCAPE '\\' ORDER BY timestamp DESC LIMIT ?",
                (f"%{escaped}%", limit),
            )
            rows = await cursor.fetchall()

        return [
            {"role": r[0], "content": r[1], "timestamp": r[2]}
            for r in rows
        ]

    async def cleanup_old_turns(self, days: int = 90) -> int:
        """Delete conversation turns older than N days.

        Returns the count of deleted rows. Call on startup or periodically
        to prevent unbounded growth of the conversations table.
        """
        self._ensure_db()
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=days)
        ).isoformat()

        async with self._shared.lock:
            db = self._shared.connection
            cursor = await db.execute(
                "DELETE FROM conversations WHERE timestamp < ?",
                (cutoff,),
            )
            await db.commit()
            return cursor.rowcount

    async def get_turns_since(
        self, since_hours: int = 24, limit: int = 1000
    ) -> list[dict]:
        """Get conversation turns from the last N hours (up to limit)."""
        self._ensure_db()
        cutoff = (
            datetime.now(timezone.utc) - timedelta(hours=since_hours)
        ).isoformat()

        async with self._shared.lock:
            db = self._shared.connection
            cursor = await db.execute(
                "SELECT role, content, timestamp FROM conversations "
                "WHERE timestamp >= ? ORDER BY timestamp ASC LIMIT ?",
                (cutoff, limit),
            )
            rows = await cursor.fetchall()

        return [
            {"role": r[0], "content": r[1], "timestamp": r[2]}
            for r in rows
        ]

    async def close(self):
        if self._own_connection:
            await self._shared.close()
