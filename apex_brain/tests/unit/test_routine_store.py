"""Tests for the Routine Store - dedicated routine storage with lifecycle."""
from __future__ import annotations

import pytest

from memory.routine_store import RoutineStore


@pytest.fixture
async def store(tmp_path):
    """Create a fresh RoutineStore for each test."""
    db_path = str(tmp_path / "test_routines.db")
    s = RoutineStore(db_path)
    await s.initialize()
    yield s
    await s.close()


# ------------------------------------------------------------------ #
# Basic CRUD
# ------------------------------------------------------------------ #
class TestSaveAndGet:
    @pytest.mark.asyncio
    async def test_save_new_routine(self, store):
        rid = await store.save_routine("morning", ["Turn on lights", "Set thermostat"])
        assert rid > 0

    @pytest.mark.asyncio
    async def test_get_routine(self, store):
        await store.save_routine("morning", ["Turn on lights", "Set thermostat"], trigger="morning")
        routine = await store.get_routine("morning")
        assert routine is not None
        assert routine["name"] == "morning"
        assert routine["steps"] == ["Turn on lights", "Set thermostat"]
        assert routine["trigger_hint"] == "morning"
        assert routine["use_count"] == 0
        assert routine["enabled"] is True

    @pytest.mark.asyncio
    async def test_get_nonexistent_returns_none(self, store):
        assert await store.get_routine("nonexistent") is None

    @pytest.mark.asyncio
    async def test_case_insensitive_name(self, store):
        await store.save_routine("Movie Night", ["Dim lights", "Turn on TV"])
        routine = await store.get_routine("movie night")
        assert routine is not None
        assert routine["name"] == "movie night"

    @pytest.mark.asyncio
    async def test_update_existing_routine(self, store):
        await store.save_routine("morning", ["Turn on lights"])
        await store.save_routine("morning", ["Turn on lights", "Play music"])
        routine = await store.get_routine("morning")
        assert routine["steps"] == ["Turn on lights", "Play music"]


# ------------------------------------------------------------------ #
# List routines
# ------------------------------------------------------------------ #
class TestListRoutines:
    @pytest.mark.asyncio
    async def test_list_empty(self, store):
        result = await store.list_routines()
        assert result == []

    @pytest.mark.asyncio
    async def test_list_multiple(self, store):
        await store.save_routine("morning", ["Lights on"])
        await store.save_routine("bedtime", ["Lights off"])
        result = await store.list_routines()
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_list_excludes_disabled(self, store):
        await store.save_routine("morning", ["Lights on"])
        # Manually disable
        async with store._shared.lock:
            db = store._shared.connection
            await db.execute(
                "UPDATE routines SET enabled = 0 WHERE name = 'morning'"
            )
            await db.commit()
        result = await store.list_routines(include_disabled=False)
        assert len(result) == 0

    @pytest.mark.asyncio
    async def test_list_includes_disabled(self, store):
        await store.save_routine("morning", ["Lights on"])
        async with store._shared.lock:
            db = store._shared.connection
            await db.execute(
                "UPDATE routines SET enabled = 0 WHERE name = 'morning'"
            )
            await db.commit()
        result = await store.list_routines(include_disabled=True)
        assert len(result) == 1


# ------------------------------------------------------------------ #
# Usage tracking
# ------------------------------------------------------------------ #
class TestUsageTracking:
    @pytest.mark.asyncio
    async def test_record_usage_increments(self, store):
        await store.save_routine("morning", ["Lights on"])
        await store.record_usage("morning")
        await store.record_usage("morning")
        routine = await store.get_routine("morning")
        assert routine["use_count"] == 2
        assert routine["last_used_at"] is not None

    @pytest.mark.asyncio
    async def test_record_usage_sets_last_used(self, store):
        await store.save_routine("morning", ["Lights on"])
        routine = await store.get_routine("morning")
        assert routine["last_used_at"] is None
        await store.record_usage("morning")
        routine = await store.get_routine("morning")
        assert routine["last_used_at"] is not None


# ------------------------------------------------------------------ #
# Delete
# ------------------------------------------------------------------ #
class TestDelete:
    @pytest.mark.asyncio
    async def test_delete_existing(self, store):
        await store.save_routine("morning", ["Lights on"])
        assert await store.delete_routine("morning") is True
        assert await store.get_routine("morning") is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent(self, store):
        assert await store.delete_routine("nope") is False


# ------------------------------------------------------------------ #
# Stale detection
# ------------------------------------------------------------------ #
class TestStaleDetection:
    @pytest.mark.asyncio
    async def test_new_routine_not_stale(self, store):
        await store.save_routine("morning", ["Lights on"])
        stale = await store.get_stale_routines(days=90)
        assert len(stale) == 0

    @pytest.mark.asyncio
    async def test_old_unused_routine_is_stale(self, store):
        await store.save_routine("morning", ["Lights on"])
        # Manually set created_at to 100 days ago
        async with store._shared.lock:
            db = store._shared.connection
            await db.execute(
                "UPDATE routines SET created_at = datetime('now', '-100 days') "
                "WHERE name = 'morning'"
            )
            await db.commit()
        stale = await store.get_stale_routines(days=90)
        assert len(stale) == 1
        assert stale[0]["name"] == "morning"

    @pytest.mark.asyncio
    async def test_recently_used_not_stale(self, store):
        await store.save_routine("morning", ["Lights on"])
        async with store._shared.lock:
            db = store._shared.connection
            await db.execute(
                "UPDATE routines SET created_at = datetime('now', '-100 days') "
                "WHERE name = 'morning'"
            )
            await db.commit()
        await store.record_usage("morning")  # just used it
        stale = await store.get_stale_routines(days=90)
        assert len(stale) == 0


# ------------------------------------------------------------------ #
# Migration
# ------------------------------------------------------------------ #
class TestMigration:
    @pytest.mark.asyncio
    async def test_migration_from_knowledge_store(self, store):
        mock_ks = type("MockKS", (), {
            "get_all_facts": lambda self, **kw: _async_return([
                {"key": "good morning", "value": "Turn on lights. Set thermostat to 72."},
                {"key": "bedtime", "value": "[trigger: bedtime] Turn off all lights. Lock doors."},
            ])
        })()
        count = await store.migrate_from_knowledge_store(mock_ks)
        assert count == 2
        morning = await store.get_routine("good morning")
        assert morning is not None
        assert "Turn on lights" in morning["steps"]

    @pytest.mark.asyncio
    async def test_migration_skips_existing(self, store):
        await store.save_routine("good morning", ["Existing steps"])
        mock_ks = type("MockKS", (), {
            "get_all_facts": lambda self, **kw: _async_return([
                {"key": "good morning", "value": "New steps."},
            ])
        })()
        count = await store.migrate_from_knowledge_store(mock_ks)
        assert count == 0
        routine = await store.get_routine("good morning")
        assert routine["steps"] == ["Existing steps"]

    @pytest.mark.asyncio
    async def test_migration_strips_trigger_prefix(self, store):
        mock_ks = type("MockKS", (), {
            "get_all_facts": lambda self, **kw: _async_return([
                {"key": "bedtime", "value": "[trigger: bedtime] Turn off lights. Lock doors."},
            ])
        })()
        await store.migrate_from_knowledge_store(mock_ks)
        routine = await store.get_routine("bedtime")
        assert routine is not None
        assert "Turn off lights" in routine["steps"]
        assert not any("[trigger:" in s for s in routine["steps"])


async def _async_return(val):
    return val


# ── Bug 17 regression: uninitialized store raises RuntimeError ──


@pytest.mark.asyncio
async def test_routine_store_uninitialized_raises_runtime_error(tmp_path):
    """Regression for Bug 17: methods raise RuntimeError when initialize() not called."""
    db_path = str(tmp_path / "test.db")
    store = RoutineStore(db_path)

    with pytest.raises(RuntimeError, match="Store not initialized"):
        await store.save_routine("morning", ["Lights on"])

    with pytest.raises(RuntimeError, match="Store not initialized"):
        await store.get_routine("morning")

    with pytest.raises(RuntimeError, match="Store not initialized"):
        await store.list_routines()


@pytest.mark.asyncio
async def test_routine_store_after_close_raises_runtime_error(store):
    """Regression for Bug 17: after close(), methods raise RuntimeError not AttributeError."""
    await store.close()

    with pytest.raises(RuntimeError, match="Store not initialized"):
        await store.save_routine("morning", ["Lights on"])

    with pytest.raises(RuntimeError, match="Store not initialized"):
        await store.get_routine("morning")
