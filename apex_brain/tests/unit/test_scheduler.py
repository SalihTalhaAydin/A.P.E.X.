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
    ks.get_due_reminders = AsyncMock(return_value=[])
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
# Register from callback (reentrancy)
# ------------------------------------------------------------------ #
class TestRegisterFromCallback:
    """Verify scheduler.register() can be called from inside a task callback."""

    @pytest.mark.asyncio
    async def test_callback_registering_new_task_safe_no_crash(
        self, mock_conversation, mock_knowledge_store
    ):
        """A running task's callback calls scheduler.register(); scheduler must handle
        it safely (e.g., iterate over copy of _tasks so modification doesn't crash).
        Assert: no crash, newly registered task appears in task_count/task_names."""
        s = Scheduler(
            conversation=mock_conversation,
            knowledge_store=mock_knowledge_store,
            curator=None,
        )
        second_callback = AsyncMock()

        async def first_callback():
            s.register(
                "newly_added_task",
                second_callback,
                interval_seconds=60,
            )

        real_sleep = asyncio.sleep

        async def fast_sleep(delay):
            d = 0.02 if delay > 1 else delay
            await real_sleep(d)

        with (
            patch("brain.scheduler._TICK_INTERVAL", 0.05),
            patch("brain.scheduler.asyncio.sleep", fast_sleep),
            patch.object(s, "_register_builtin_tasks", return_value=None),
        ):
            s.register(
                "trigger_task",
                first_callback,
                interval_seconds=60,
                run_on_startup=True,
            )
            await s.start()
            await asyncio.sleep(0.2)
            await s.stop()

        assert "newly_added_task" in s.task_names
        assert s.task_count >= 2
        assert "trigger_task" in s.task_names

    @pytest.mark.asyncio
    async def test_register_from_task_callback(self, scheduler):
        """A running task's callback calls scheduler.register() to add a new task."""
        real_sleep = asyncio.sleep

        async def fast_sleep(delay):
            d = 0.02 if delay > 1 else delay
            await real_sleep(d)

        with (
            patch("brain.scheduler._TICK_INTERVAL", 0.05),
            patch("brain.scheduler.asyncio.sleep", fast_sleep),
            patch.object(scheduler, "_register_builtin_tasks", return_value=None),
        ):
            await scheduler.start()

            async def first_callback():
                scheduler.register(
                    "second_task",
                    AsyncMock(),
                    interval_seconds=60,
                )

            scheduler.register(
                "first_task",
                first_callback,
                interval_seconds=60,
                run_on_startup=True,
            )
            await asyncio.sleep(0.2)

            assert "second_task" in scheduler.task_names
            assert scheduler.task_count >= 2

            await scheduler.stop()

    @pytest.mark.asyncio
    async def test_register_from_callback_both_tasks_run_bug130(
        self, mock_conversation, mock_knowledge_store
    ):
        """Bug 130: When a task callback calls scheduler.register(), the Scheduler must
        handle it (e.g., not mutate _tasks while iterating). Both the original task
        and the newly registered task must run."""
        s = Scheduler(
            conversation=mock_conversation,
            knowledge_store=mock_knowledge_store,
            curator=None,
        )
        first_ran = []
        second_ran = []

        second_callback = AsyncMock(side_effect=lambda: second_ran.append(1))

        async def first_callback():
            first_ran.append(1)
            s.register(
                "second_task",
                second_callback,
                interval_seconds=60,
                run_on_startup=True,
            )

        real_sleep = asyncio.sleep

        async def fast_sleep(delay):
            d = 0.02 if delay > 1 else delay
            await real_sleep(d)

        with (
            patch("brain.scheduler._TICK_INTERVAL", 0.05),
            patch("brain.scheduler.asyncio.sleep", fast_sleep),
            patch.object(s, "_register_builtin_tasks", return_value=None),
        ):
            s.register(
                "first_task",
                first_callback,
                interval_seconds=60,
                run_on_startup=True,
            )
            await s.start()
            await asyncio.sleep(0.25)
            await s.stop()

        assert "first_task" in s.task_names
        assert "second_task" in s.task_names
        assert s.task_count >= 2
        assert len(first_ran) >= 1, "first_task callback should have run"
        assert second_callback.await_count >= 1, "second_task callback should have run"

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


# ------------------------------------------------------------------ #
# Reminder check (Bug 4 + Bug 3 regression)
# ------------------------------------------------------------------ #
class TestReminderCheck:
    """Regression: reminder_check must use get_due_reminders (which returns
    expires_at) and must query for expired facts, not non-expired ones.
    Bug 3: get_due_reminders must use datetime comparison, not string
    comparison (see test_knowledge_store.py for datetime parsing tests).
    Bug 15: _task_reminder_check must be fully covered by unit tests."""

    @pytest.mark.asyncio
    async def test_reminder_check_uses_get_due_reminders_not_get_all_facts(
        self, scheduler, mock_knowledge_store
    ):
        """Scheduler must use get_due_reminders (which filters by expires_at),
        never get_all_facts. Using get_all_facts would return non-expired facts."""
        mock_knowledge_store.get_due_reminders.return_value = []
        await scheduler._task_reminder_check()
        mock_knowledge_store.get_due_reminders.assert_awaited_once_with(limit=20)
        mock_knowledge_store.get_all_facts.assert_not_called()

    @pytest.mark.asyncio
    async def test_reminder_check_filters_by_expires_at_via_get_due_reminders(
        self, scheduler, mock_conversation, mock_knowledge_store
    ):
        """get_due_reminders returns only reminders with expires_at <= now.
        Scheduler processes all returned reminders; filtering happens in store."""
        # Store returns pre-filtered reminders (expires_at already past)
        mock_knowledge_store.get_due_reminders.return_value = [
            {
                "id": 10,
                "category": "reminder",
                "key": "expired_task",
                "value": "was due earlier",
                "expires_at": "2025-02-20T08:00:00+00:00",
            }
        ]
        await scheduler._task_reminder_check()
        mock_conversation.handle.assert_awaited_once()
        mock_knowledge_store.delete_fact_by_id.assert_awaited_once_with(10)

    @pytest.mark.asyncio
    async def test_reminder_check_calls_get_due_reminders(
        self, scheduler, mock_knowledge_store
    ):
        """Reminder check must use get_due_reminders, not get_all_facts."""
        await scheduler._task_reminder_check()
        mock_knowledge_store.get_due_reminders.assert_awaited_once_with(
            limit=20
        )

    @pytest.mark.asyncio
    async def test_reminder_check_fires_for_due_reminders(
        self, scheduler, mock_conversation, mock_knowledge_store
    ):
        """When get_due_reminders returns facts, reminder_check delivers them."""
        mock_knowledge_store.get_due_reminders.return_value = [
            {
                "id": 1,
                "category": "reminder",
                "key": "pick_up_milk",
                "value": "get milk from store",
                "confidence": 1.0,
                "created_at": "2025-02-20T10:00:00+00:00",
                "updated_at": "2025-02-20T10:00:00+00:00",
                "expires_at": "2025-02-20T12:00:00+00:00",
            }
        ]
        await scheduler._task_reminder_check()
        mock_conversation.handle.assert_awaited_once()
        mock_knowledge_store.delete_fact_by_id.assert_awaited_once_with(1)

    @pytest.mark.asyncio
    async def test_reminder_check_empty_due_list_returns_early(
        self, scheduler, mock_conversation, mock_knowledge_store
    ):
        """Empty due list is a no-op: no handle or delete calls."""
        mock_knowledge_store.get_due_reminders.return_value = []
        await scheduler._task_reminder_check()
        mock_conversation.handle.assert_not_awaited()
        mock_knowledge_store.delete_fact_by_id.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_reminder_check_handle_exception_no_delete(
        self, scheduler, mock_conversation, mock_knowledge_store
    ):
        """When handle raises, fact is not deleted; retries next cycle."""
        mock_knowledge_store.get_due_reminders.return_value = [
            {
                "id": 42,
                "category": "reminder",
                "key": "call_dentist",
                "value": "schedule appointment",
                "confidence": 1.0,
                "created_at": "2025-02-20T10:00:00+00:00",
                "updated_at": "2025-02-20T10:00:00+00:00",
                "expires_at": "2025-02-20T14:00:00+00:00",
            }
        ]
        mock_conversation.handle.side_effect = RuntimeError("handle failed")
        await scheduler._task_reminder_check()
        mock_conversation.handle.assert_awaited_once()
        mock_knowledge_store.delete_fact_by_id.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_reminder_check_delete_exception_graceful(
        self, scheduler, mock_conversation, mock_knowledge_store
    ):
        """Exception during delete_fact_by_id is swallowed; task completes."""
        mock_knowledge_store.get_due_reminders.return_value = [
            {
                "id": 99,
                "category": "reminder",
                "key": "pay_bill",
                "value": "electric bill",
                "confidence": 1.0,
                "created_at": "2025-02-20T10:00:00+00:00",
                "updated_at": "2025-02-20T10:00:00+00:00",
                "expires_at": "2025-02-20T16:00:00+00:00",
            }
        ]
        mock_knowledge_store.delete_fact_by_id.side_effect = OSError("db locked")
        await scheduler._task_reminder_check()
        mock_conversation.handle.assert_awaited_once()
        mock_knowledge_store.delete_fact_by_id.assert_awaited_once_with(99)

    @pytest.mark.asyncio
    async def test_reminder_check_multiple_reminders_batch(
        self, scheduler, mock_conversation, mock_knowledge_store
    ):
        """Multiple due reminders in one batch: each gets handle call."""
        mock_knowledge_store.get_due_reminders.return_value = [
            {
                "id": 1,
                "category": "reminder",
                "key": "task_a",
                "value": "first task",
                "confidence": 1.0,
                "created_at": "2025-02-20T10:00:00+00:00",
                "updated_at": "2025-02-20T10:00:00+00:00",
                "expires_at": "2025-02-20T12:00:00+00:00",
            },
            {
                "id": 2,
                "category": "reminder",
                "key": "task_b",
                "value": "second task",
                "confidence": 1.0,
                "created_at": "2025-02-20T10:00:00+00:00",
                "updated_at": "2025-02-20T10:00:00+00:00",
                "expires_at": "2025-02-20T12:00:00+00:00",
            },
            {
                "id": 3,
                "category": "reminder",
                "key": "task_c",
                "value": "third task",
                "confidence": 1.0,
                "created_at": "2025-02-20T10:00:00+00:00",
                "updated_at": "2025-02-20T10:00:00+00:00",
                "expires_at": "2025-02-20T12:00:00+00:00",
            },
        ]
        await scheduler._task_reminder_check()
        assert mock_conversation.handle.await_count == 3
        assert mock_knowledge_store.delete_fact_by_id.await_count == 3
        mock_knowledge_store.delete_fact_by_id.assert_any_call(1)
        mock_knowledge_store.delete_fact_by_id.assert_any_call(2)
        mock_knowledge_store.delete_fact_by_id.assert_any_call(3)

    @pytest.mark.asyncio
    async def test_reminder_check_get_due_reminders_raises_graceful(
        self, scheduler, mock_conversation, mock_knowledge_store
    ):
        """When get_due_reminders raises, outer exception is caught; no crash."""
        mock_knowledge_store.get_due_reminders.side_effect = RuntimeError(
            "db locked"
        )
        await scheduler._task_reminder_check()  # Should not raise
        mock_conversation.handle.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_reminder_check_reminder_without_id_skips_delete(
        self, scheduler, mock_conversation, mock_knowledge_store
    ):
        """Reminder dict without id: handle is called but delete_fact_by_id is not."""
        mock_knowledge_store.get_due_reminders.return_value = [
            {
                "category": "reminder",
                "key": "no_id_reminder",
                "value": "content",
                "expires_at": "2025-02-20T12:00:00+00:00",
            }
        ]
        await scheduler._task_reminder_check()
        mock_conversation.handle.assert_awaited_once()
        mock_knowledge_store.delete_fact_by_id.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_reminder_check_uses_defaults_for_missing_key_value(
        self, scheduler, mock_conversation, mock_knowledge_store
    ):
        """Reminder with missing key/value uses defaults ('reminder', '')."""
        mock_knowledge_store.get_due_reminders.return_value = [
            {"id": 1, "category": "reminder", "expires_at": "2025-02-20T12:00:00+00:00"}
        ]
        await scheduler._task_reminder_check()
        mock_conversation.handle.assert_awaited_once_with(
            "[REMINDER] The user asked to be reminded: reminder — . "
            "Let them know naturally.",
            session_id="apex_reminders",
        )

    @pytest.mark.asyncio
    async def test_reminder_check_message_contains_key_value_and_session(
        self, scheduler, mock_conversation, mock_knowledge_store
    ):
        """Verify handle called with correct message format and apex_reminders session."""
        mock_knowledge_store.get_due_reminders.return_value = [
            {
                "id": 7,
                "key": "pay_rent",
                "value": "due tomorrow",
                "expires_at": "2025-02-20T18:00:00+00:00",
            }
        ]
        await scheduler._task_reminder_check()
        mock_conversation.handle.assert_awaited_once_with(
            "[REMINDER] The user asked to be reminded: pay_rent — due tomorrow. "
            "Let them know naturally.",
            session_id="apex_reminders",
        )

    @pytest.mark.asyncio
    async def test_reminder_check_partial_batch_first_fails_second_succeeds(
        self, scheduler, mock_conversation, mock_knowledge_store
    ):
        """When first reminder's handle raises, second still gets delivered and deleted."""
        call_count = 0

        def handle_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("first failed")
            return "OK"

        mock_conversation.handle.side_effect = handle_side_effect
        mock_knowledge_store.get_due_reminders.return_value = [
            {
                "id": 1,
                "key": "first",
                "value": "fails",
                "expires_at": "2025-02-20T12:00:00+00:00",
            },
            {
                "id": 2,
                "key": "second",
                "value": "succeeds",
                "expires_at": "2025-02-20T12:00:00+00:00",
            },
        ]
        await scheduler._task_reminder_check()
        assert mock_conversation.handle.await_count == 2
        # First fails → no delete; second succeeds → deleted
        mock_knowledge_store.delete_fact_by_id.assert_awaited_once_with(2)

    @pytest.mark.asyncio
    async def test_reminder_check_fact_with_expires_at_delivered_and_deleted(
        self, scheduler, mock_conversation, mock_knowledge_store
    ):
        """Reminder with expires_at (past due) is delivered and deleted on success."""
        mock_knowledge_store.get_due_reminders.return_value = [
            {
                "id": 99,
                "category": "reminder",
                "key": "water_plants",
                "value": "water the succulents",
                "confidence": 1.0,
                "created_at": "2025-02-20T09:00:00+00:00",
                "updated_at": "2025-02-20T09:00:00+00:00",
                "expires_at": "2025-02-20T11:00:00+00:00",
            }
        ]
        await scheduler._task_reminder_check()
        mock_conversation.handle.assert_awaited_once_with(
            "[REMINDER] The user asked to be reminded: water_plants — water the succulents. "
            "Let them know naturally.",
            session_id="apex_reminders",
        )
        mock_knowledge_store.delete_fact_by_id.assert_awaited_once_with(99)
