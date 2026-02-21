"""
Audit Store - Logs every manage() and configure() call.
Provides a full audit trail for post-incident review.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

import aiosqlite

logger = logging.getLogger(__name__)


class AuditStore:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def initialize(self):
        """Create the system_audit_log table."""
        self._db = await aiosqlite.connect(self.db_path)
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA busy_timeout=5000")
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS system_audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                tool TEXT NOT NULL,
                action TEXT NOT NULL,
                target TEXT NOT NULL DEFAULT '',
                config_json TEXT NOT NULL DEFAULT '{}',
                result TEXT NOT NULL DEFAULT '',
                session_id TEXT NOT NULL DEFAULT 'default',
                user_approved INTEGER NOT NULL DEFAULT 0
            )
        """)
        await self._db.execute("""
            CREATE INDEX IF NOT EXISTS idx_audit_timestamp
            ON system_audit_log(timestamp DESC)
        """)
        await self._db.execute("""
            CREATE INDEX IF NOT EXISTS idx_audit_tool
            ON system_audit_log(tool, action)
        """)
        await self._db.commit()

    async def log(
        self,
        tool: str,
        action: str,
        target: str = "",
        config: dict | None = None,
        result: str = "",
        session_id: str = "default",
        user_approved: bool = False,
    ) -> int:
        """Log an audit event. Returns the row id."""
        now = datetime.now(timezone.utc).isoformat()
        config_json = json.dumps(config or {})
        cursor = await self._db.execute(
            "INSERT INTO system_audit_log "
            "(timestamp, tool, action, target, config_json, "
            "result, session_id, user_approved) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                now,
                tool,
                action,
                target,
                config_json,
                result,
                session_id,
                1 if user_approved else 0,
            ),
        )
        await self._db.commit()
        return cursor.lastrowid

    async def get_recent(
        self, limit: int = 50
    ) -> list[dict]:
        """Get the most recent audit entries."""
        cursor = await self._db.execute(
            "SELECT id, timestamp, tool, action, target, "
            "config_json, result, session_id, user_approved "
            "FROM system_audit_log "
            "ORDER BY timestamp DESC LIMIT ?",
            (limit,),
        )
        rows = await cursor.fetchall()
        return [
            {
                "id": r[0],
                "timestamp": r[1],
                "tool": r[2],
                "action": r[3],
                "target": r[4],
                "config": self._safe_json_loads(r[5]),
                "result": r[6],
                "session_id": r[7],
                "user_approved": bool(r[8]),
            }
            for r in rows
        ]

    async def get_by_tool(
        self, tool: str, limit: int = 50
    ) -> list[dict]:
        """Get audit entries filtered by tool name."""
        cursor = await self._db.execute(
            "SELECT id, timestamp, tool, action, target, "
            "config_json, result, session_id, user_approved "
            "FROM system_audit_log "
            "WHERE tool = ? "
            "ORDER BY timestamp DESC LIMIT ?",
            (tool, limit),
        )
        rows = await cursor.fetchall()
        return [
            {
                "id": r[0],
                "timestamp": r[1],
                "tool": r[2],
                "action": r[3],
                "target": r[4],
                "config": self._safe_json_loads(r[5]),
                "result": r[6],
                "session_id": r[7],
                "user_approved": bool(r[8]),
            }
            for r in rows
        ]

    @staticmethod
    def _safe_json_loads(raw: str) -> dict:
        """Parse JSON, returning empty dict on error."""
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return {}

    async def close(self):
        if self._db:
            await self._db.close()
