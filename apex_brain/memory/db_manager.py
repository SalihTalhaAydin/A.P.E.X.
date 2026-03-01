"""
Shared Database Connection - Prevents "database is locked" under concurrent load.

SQLite WAL mode allows only ONE writer at a time across all connections.
Four independent stores (conversation, knowledge, routine, audit) each opened
their own connection, causing "database is locked" errors under load.

This module provides SharedDbConnection: a single aiosqlite connection with an
asyncio.Lock that serializes all database access. All stores share this connection
and lock, eliminating writer contention.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import aiosqlite

if TYPE_CHECKING:
    pass


class SharedDbConnection:
    """
    Single shared SQLite connection for all stores.

    Serializes access via an asyncio.Lock so only one writer runs at a time,
    preventing "database is locked" under concurrent load.
    """

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._conn: aiosqlite.Connection | None = None
        self._lock = asyncio.Lock()

    @property
    def lock(self) -> asyncio.Lock:
        """Lock to hold for the duration of any DB operation."""
        return self._lock

    @property
    def connection(self) -> aiosqlite.Connection:
        """The underlying aiosqlite connection. Do not use without holding lock."""
        if self._conn is None:
            raise RuntimeError(
                "SharedDbConnection not initialized. Call initialize() first."
            )
        return self._conn

    @property
    def is_initialized(self) -> bool:
        """Whether the connection has been opened."""
        return self._conn is not None

    async def initialize(self) -> None:
        """Open the connection and set PRAGMAs for WAL + busy timeout."""
        if self._conn is not None:
            return
        self._conn = await aiosqlite.connect(
            self.db_path, isolation_level=None
        )
        await self._conn.execute("PRAGMA journal_mode=WAL")
        # 10s busy timeout: retry on lock before raising "database is locked"
        await self._conn.execute("PRAGMA busy_timeout=10000")

    async def close(self) -> None:
        """Close the connection. Idempotent. Acquires lock to avoid races with in-progress operations."""
        async with self._lock:
            if self._conn is not None:
                await self._conn.close()
                self._conn = None
