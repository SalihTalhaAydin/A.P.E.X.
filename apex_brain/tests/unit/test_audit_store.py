"""
Tests for the AuditStore — system_audit_log table.
"""

from __future__ import annotations

import pytest
from memory.audit_store import AuditStore


@pytest.fixture
async def store(tmp_path):
    """Create an in-memory audit store for testing."""
    db_path = str(tmp_path / "test_audit.db")
    s = AuditStore(db_path)
    await s.initialize()
    yield s
    await s.close()


@pytest.mark.asyncio
async def test_initialize_creates_table(store):
    """Table exists after initialize."""
    async with store._shared.lock:
        cursor = await store._shared.connection.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name='system_audit_log'"
        )
        row = await cursor.fetchone()
    assert row is not None


@pytest.mark.asyncio
async def test_log_returns_row_id(store):
    row_id = await store.log(
        tool="manage",
        action="backup",
        target="list",
        result="executed",
    )
    assert row_id == 1


@pytest.mark.asyncio
async def test_log_stores_all_fields(store):
    await store.log(
        tool="manage",
        action="restart",
        target="core",
        config={"confirmed": True},
        result="executed",
        session_id="voice",
        user_approved=True,
    )
    entries = await store.get_recent(limit=1)
    assert len(entries) == 1
    entry = entries[0]
    assert entry["tool"] == "manage"
    assert entry["action"] == "restart"
    assert entry["target"] == "core"
    assert entry["config"] == {"confirmed": True}
    assert entry["result"] == "executed"
    assert entry["session_id"] == "voice"
    assert entry["user_approved"] is True


@pytest.mark.asyncio
async def test_log_defaults(store):
    """Default values are applied correctly."""
    await store.log(tool="configure", action="rename")
    entries = await store.get_recent(limit=1)
    entry = entries[0]
    assert entry["target"] == ""
    assert entry["config"] == {}
    assert entry["result"] == ""
    assert entry["session_id"] == "default"
    assert entry["user_approved"] is False


@pytest.mark.asyncio
async def test_get_recent_ordering(store):
    """Most recent entries come first."""
    await store.log(tool="manage", action="first")
    await store.log(tool="manage", action="second")
    await store.log(tool="manage", action="third")
    entries = await store.get_recent(limit=10)
    assert len(entries) == 3
    assert entries[0]["action"] == "third"
    assert entries[2]["action"] == "first"


@pytest.mark.asyncio
async def test_get_recent_limit(store):
    """Limit parameter restricts results."""
    for i in range(10):
        await store.log(tool="manage", action=f"action_{i}")
    entries = await store.get_recent(limit=3)
    assert len(entries) == 3


@pytest.mark.asyncio
async def test_get_by_tool(store):
    """Filter by tool name."""
    await store.log(tool="manage", action="backup")
    await store.log(tool="configure", action="rename")
    await store.log(tool="manage", action="health")

    manage_entries = await store.get_by_tool("manage")
    assert len(manage_entries) == 2
    assert all(e["tool"] == "manage" for e in manage_entries)

    config_entries = await store.get_by_tool("configure")
    assert len(config_entries) == 1


@pytest.mark.asyncio
async def test_config_json_serialization(store):
    """Config dict is properly serialized/deserialized."""
    config = {
        "backup_id": "abc123",
        "nested": {"key": "value"},
        "list": [1, 2, 3],
    }
    await store.log(
        tool="manage",
        action="restore",
        config=config,
    )
    entries = await store.get_recent(limit=1)
    assert entries[0]["config"] == config


@pytest.mark.asyncio
async def test_multiple_stores_same_db(tmp_path):
    """Two stores pointing to same DB work with WAL."""
    db_path = str(tmp_path / "shared.db")
    store1 = AuditStore(db_path)
    store2 = AuditStore(db_path)
    await store1.initialize()
    await store2.initialize()

    await store1.log(tool="manage", action="test1")
    await store2.log(tool="configure", action="test2")

    entries = await store1.get_recent()
    assert len(entries) == 2

    await store1.close()
    await store2.close()


# ── Bug 17 regression: uninitialized store raises RuntimeError ──


@pytest.mark.asyncio
async def test_audit_store_uninitialized_raises_runtime_error(tmp_path):
    """Regression for Bug 17: methods raise RuntimeError when initialize() not called."""
    db_path = str(tmp_path / "test.db")
    store = AuditStore(db_path)

    with pytest.raises(RuntimeError, match="Store not initialized"):
        await store.log(tool="manage", action="backup")

    with pytest.raises(RuntimeError, match="Store not initialized"):
        await store.get_recent(limit=5)

    with pytest.raises(RuntimeError, match="Store not initialized"):
        await store.get_by_tool("manage")


@pytest.mark.asyncio
async def test_audit_store_after_close_raises_runtime_error(store):
    """Regression for Bug 17: after close(), methods raise RuntimeError not AttributeError."""
    await store.close()

    with pytest.raises(RuntimeError, match="Store not initialized"):
        await store.log(tool="manage", action="backup")

    with pytest.raises(RuntimeError, match="Store not initialized"):
        await store.get_recent(limit=5)
