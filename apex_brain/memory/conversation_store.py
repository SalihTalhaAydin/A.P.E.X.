"""
Conversation Store - Saves every conversation turn permanently.
Never lose context. Every Apex interaction is searchable.
"""
from __future__ import annotations

from datetime import datetime, timezone

import aiosqlite


class ConversationStore:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def initialize(self):
        """Create tables if they don't exist."""
        self._db = await aiosqlite.connect(self.db_path)
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA busy_timeout=5000")
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                session_id TEXT DEFAULT 'default'
            )
        """)
        await self._db.execute("""
            CREATE INDEX IF NOT EXISTS idx_conv_timestamp
            ON conversations(timestamp DESC)
        """)
        await self._db.execute("""
            CREATE INDEX IF NOT EXISTS idx_conv_session
            ON conversations(session_id, timestamp DESC)
        """)
        await self._db.commit()

    async def save_turn(
        self, role: str, content: str, session_id: str = "default"
    ):
        """Save a conversation turn (user or assistant)."""
        if not content or not content.strip():
            return
        now = datetime.now(timezone.utc).isoformat()
        await self._db.execute(
            "INSERT INTO conversations (role, content, timestamp, session_id) VALUES (?, ?, ?, ?)",
            (role, content.strip(), now, session_id),
        )
        await self._db.commit()

    async def get_recent(
        self, n: int = 10, session_id: str | None = None
    ) -> list[dict]:
        """Get the last N conversation turns, newest last (chronological order)."""
        if session_id:
            cursor = await self._db.execute(
                "SELECT role, content, timestamp FROM conversations "
                "WHERE session_id = ? ORDER BY id DESC LIMIT ?",
                (session_id, n),
            )
        else:
            cursor = await self._db.execute(
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
        escaped = self._escape_like(query)
        cursor = await self._db.execute(
            "SELECT role, content, timestamp FROM conversations "
            "WHERE content LIKE ? ESCAPE '\\' ORDER BY timestamp DESC LIMIT ?",
            (f"%{escaped}%", limit),
        )
        rows = await cursor.fetchall()
        return [
            {"role": r[0], "content": r[1], "timestamp": r[2]}
            for r in rows
        ]

    async def get_turns_since(self, since_hours: int = 24) -> list[dict]:
        """Get all conversation turns from the last N hours."""
        from datetime import timedelta
        cutoff = (
            datetime.now(timezone.utc) - timedelta(hours=since_hours)
        ).isoformat()
        cursor = await self._db.execute(
            "SELECT role, content, timestamp FROM conversations "
            "WHERE timestamp >= ? ORDER BY timestamp ASC",
            (cutoff,),
        )
        rows = await cursor.fetchall()
        return [
            {"role": r[0], "content": r[1], "timestamp": r[2]}
            for r in rows
        ]

    async def close(self):
        if self._db:
            await self._db.close()
