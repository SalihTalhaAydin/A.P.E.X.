"""Tests for the Scheduler - background task runner."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from brain.scheduler import Scheduler, ScheduledTask


@pytest.fixture
def mock_conversation():
    conv = AsyncMock()
    conv.handle = AsyncMock(return_value="OK")
    return conv


@pytest.fixture
def mock_knowledge_store():
    ks = AsyncMock()
    ks.decay_confidence = AsyncMock(return_value=0)
    ks.cleanup_expired = AsyncMock(return_value=0)
    ks.get_all_facts = AsyncMock(return_value=[])
    return ks


@pytest.fixture
def mock_curator():
    c = AsyncMock()
    c.audit_facts = AsyncMock(return_value="healthy")
    c.audit_automations = AsyncMock()
    c.audit_entities = AsyncMock()
    c.consolidate_facts = AsyncMock(return_value="no contradictions")
    return c


@pytest.fixture
def scheduler(mock_conversation, mock_knowledge_store, mock_curator):
    return Scheduler(
        conversation=mock_conversation,
        knowledge_store=mock_knowledge_store,
        curator=mock_curator,
    )


# ------------------------------------------------------------------ #
# Registration tests
# ------------------------------------------------------------------ #
class TestRegistration:
    def test_register_task(self, scheduler):
        scheduler.register("test", AsyncMock(), interval_seconds=60)
        assert scheduler.task_count == 1
        assert "test" in scheduler.task_names

    def test_register_multiple(self, scheduler):
        scheduler.register("a", AsyncMock(), interval_seconds=60)
        scheduler.register("b", AsyncMock(), interval_seconds=120)
        assert scheduler.task_count == 2

    def test_initial_state(self, scheduler):
        assert not scheduler.running
        assert scheduler.task_count == 0


# ------------------------------------------------------------------ #
# Start / stop
# ------------------------------------------------------------------ #
class TestStartStop:
    @pytest.mark.asyncio
    async def test_start_registers_builtin_tasks(self, scheduler):
        await scheduler.start()
        # Should have registered builtin tasks
        assert scheduler.task_count > 0
        assert scheduler.running
        await scheduler.stop()

    @pytest.mark.asyncio
    async def test_stop_sets_running_false(self, scheduler):
        await scheduler.start()
        await scheduler.stop()
        assert not scheduler.running

    @pytest.mark.asyncio
    async def test_builtin_tasks_include_key_tasks(self, scheduler):
        await scheduler.start()
        names = scheduler.task_names
        # When curator is enabled, standalone fact_decay/cleanup
        # are NOT registered (curator.audit_facts handles both).
        assert "morning_briefing" in names
        assert "evening_briefing" in names
        assert "health_check" in names
        assert "reminder_check" in names
        await scheduler.stop()

    @pytest.mark.asyncio
    async def test_curator_tasks_registered_when_curator_present(self, scheduler):
        await scheduler.start()
        names = scheduler.task_names
        assert "fact_audit" in names
        assert "automation_audit" in names
        assert "entity_audit" in names
        assert "fact_consolidation" in names
        await scheduler.stop()

    @pytest.mark.asyncio
    async def test_no_curator_tasks_when_no_curator(self, mock_conversation, mock_knowledge_store):
        s = Scheduler(mock_conversation, mock_knowledge_store, curator=None)
        await s.start()
        names = s.task_names
        assert "fact_audit" not in names
        assert "automation_audit" not in names
        await s.stop()


# ------------------------------------------------------------------ #
# Safe run
# ------------------------------------------------------------------ #
class TestSafeRun:
    @pytest.mark.asyncio
    async def test_safe_run_executes_callback(self, scheduler):
        callback = AsyncMock()
        task = ScheduledTask(name="test", callback=callback, interval_seconds=60)
        await scheduler._safe_run(task)
        callback.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_safe_run_catches_exception(self, scheduler):
        callback = AsyncMock(side_effect=ValueError("boom"))
        task = ScheduledTask(name="test", callback=callback, interval_seconds=60)
        # Should not raise
        await scheduler._safe_run(task)

    @pytest.mark.asyncio
    async def test_safe_run_catches_timeout(self, scheduler):
        async def slow_task():
            await asyncio.sleep(999)

        task = ScheduledTask(name="slow", callback=slow_task, interval_seconds=60)
        # Patch the timeout to be very short
        with patch("brain.scheduler._TASK_TIMEOUT", 0.1):
            await scheduler._safe_run(task)  # Should not raise


# ------------------------------------------------------------------ #
# Fact tasks
# ------------------------------------------------------------------ #
class TestFactTasks:
    @pytest.mark.asyncio
    async def test_fact_decay_calls_store(self, scheduler, mock_knowledge_store):
        await scheduler._task_fact_decay()
        mock_knowledge_store.decay_confidence.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_fact_cleanup_calls_store(self, scheduler, mock_knowledge_store):
        await scheduler._task_fact_cleanup()
        mock_knowledge_store.cleanup_expired.assert_awaited_once()


# ------------------------------------------------------------------ #
# Timed briefing
# ------------------------------------------------------------------ #
class TestTimedBriefing:
    @pytest.mark.asyncio
    async def test_briefing_fires_at_target_hour(self, scheduler, mock_conversation):
        with patch("brain.scheduler.datetime") as mock_dt:
            mock_now = MagicMock()
            mock_now.hour = 7
            mock_now.strftime.return_value = "2025-02-20"
            mock_dt.now.return_value = mock_now
            mock_dt.side_effect = lambda *a, **kw: mock_dt

            await scheduler._timed_briefing(7, "morning_briefing", "test message")
            mock_conversation.handle.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_briefing_skips_wrong_hour(self, scheduler, mock_conversation):
        with patch("brain.scheduler.datetime") as mock_dt:
            mock_now = MagicMock()
            mock_now.hour = 14
            mock_now.strftime.return_value = "2025-02-20"
            mock_dt.now.return_value = mock_now

            await scheduler._timed_briefing(7, "morning_briefing", "test message")
            mock_conversation.handle.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_briefing_fires_only_once_per_day(
        self, scheduler, mock_conversation, mock_knowledge_store
    ):
        with patch("brain.scheduler.datetime") as mock_dt:
            mock_now = MagicMock()
            mock_now.hour = 7
            mock_now.strftime.return_value = "2025-02-20"
            mock_dt.now.return_value = mock_now

            # Register a task so we can track _last_fired_date
            scheduler.register("test_briefing", AsyncMock(), 60)

            await scheduler._timed_briefing(7, "test_briefing", "msg")
            await scheduler._timed_briefing(7, "test_briefing", "msg")
            # Only fires once
            assert mock_conversation.handle.await_count == 1

            # Advance to next day — should fire again
            mock_now.strftime.return_value = "2025-02-21"
            await scheduler._timed_briefing(7, "test_briefing", "msg")
            assert mock_conversation.handle.await_count == 2
