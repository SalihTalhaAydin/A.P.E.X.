"""Tests for FactCleanupTimer — background fact maintenance loop."""

from __future__ import annotations

import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from brain.fact_cleanup import FactCleanupTimer

# ---------------------------------------------------
# Fixtures
# ---------------------------------------------------


@pytest.fixture
def mock_knowledge_store():
    """Create a mock KnowledgeStore with async maintenance methods."""
    ks = MagicMock()
    ks.decay_confidence = AsyncMock(return_value=3)
    ks.cleanup_expired = AsyncMock(return_value=2)
    return ks


@pytest.fixture
def timer(mock_knowledge_store):
    """Create a FactCleanupTimer with a tiny interval for fast tests."""
    return FactCleanupTimer(mock_knowledge_store, interval_hours=1)


# ---------------------------------------------------
# start() tests
# ---------------------------------------------------


class TestStart:
    """Tests for start() — creates a background asyncio task."""

    @pytest.mark.asyncio
    async def test_start_returns_task(self, timer):
        """start() returns an asyncio.Task."""
        task = await timer.start()
        try:
            assert isinstance(task, asyncio.Task)
            assert not task.done()
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    @pytest.mark.asyncio
    async def test_start_creates_running_task(self, timer):
        """The task returned by start() is actively running
        (not immediately cancelled or finished)."""
        task = await timer.start()
        try:
            assert not task.cancelled()
            assert not task.done()
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


# ---------------------------------------------------
# stop() tests
# ---------------------------------------------------


class TestStop:
    """Tests for stop() — cancels the running task."""

    @pytest.mark.asyncio
    async def test_stop_cancels_task(self, timer):
        """Cancelling the task returned by start() stops the loop."""
        task = await timer.start()
        assert not task.done()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert task.cancelled()

    @pytest.mark.asyncio
    async def test_stop_when_not_started_is_safe(self):
        """Cancelling a not-yet-started scenario does not raise.

        Since FactCleanupTimer does not store the task internally,
        calling cancel on None should be handled by the caller.
        Verify the timer can be constructed and never started
        without error."""
        ks = MagicMock()
        t = FactCleanupTimer(ks, interval_hours=1)
        # No task reference exists; nothing to cancel.
        # The timer simply does nothing — no crash.
        assert t._knowledge_store is ks


# ---------------------------------------------------
# Timer loop tests
# ---------------------------------------------------


class TestLoop:
    """Tests for the _loop/_cleanup cycle."""

    @pytest.mark.asyncio
    async def test_loop_calls_decay_and_cleanup(
        self, mock_knowledge_store
    ):
        """After the sleep interval, _loop calls decay_confidence
        and cleanup_expired on the knowledge store."""
        timer = FactCleanupTimer(mock_knowledge_store, interval_hours=1)

        # Patch asyncio.sleep to return immediately once,
        # then raise CancelledError to stop the loop.
        with patch(
            "brain.fact_cleanup.asyncio.sleep",
            side_effect=[None, asyncio.CancelledError],
        ):
            task = await timer.start()
            try:
                await task
            except asyncio.CancelledError:
                pass

        mock_knowledge_store.decay_confidence.assert_awaited_once()
        mock_knowledge_store.cleanup_expired.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_loop_runs_multiple_iterations(
        self, mock_knowledge_store
    ):
        """The loop runs cleanup on each iteration until cancelled."""
        timer = FactCleanupTimer(mock_knowledge_store, interval_hours=1)

        # Let the loop run 3 iterations then cancel.
        with patch(
            "brain.fact_cleanup.asyncio.sleep",
            side_effect=[
                None,
                None,
                None,
                asyncio.CancelledError,
            ],
        ):
            task = await timer.start()
            try:
                await task
            except asyncio.CancelledError:
                pass

        assert mock_knowledge_store.decay_confidence.await_count == 3
        assert mock_knowledge_store.cleanup_expired.await_count == 3

    @pytest.mark.asyncio
    async def test_loop_handles_exception_gracefully(
        self, mock_knowledge_store, caplog
    ):
        """When _cleanup raises, the loop logs a warning but
        continues running (does not crash)."""
        mock_knowledge_store.decay_confidence.side_effect = [
            RuntimeError("db locked"),
            5,
        ]
        mock_knowledge_store.cleanup_expired.return_value = 1

        timer = FactCleanupTimer(mock_knowledge_store, interval_hours=1)

        with (
            patch(
                "brain.fact_cleanup.asyncio.sleep",
                side_effect=[None, None, asyncio.CancelledError],
            ),
            caplog.at_level(logging.WARNING),
        ):
            task = await timer.start()
            try:
                await task
            except asyncio.CancelledError:
                pass

        # First iteration: decay_confidence raises, logged as warning.
        assert any(
            "Fact cleanup error" in r.message for r in caplog.records
        )
        # Second iteration: should have succeeded normally.
        assert mock_knowledge_store.decay_confidence.await_count == 2

    @pytest.mark.asyncio
    async def test_loop_logs_cleanup_counts(
        self, mock_knowledge_store, caplog
    ):
        """After a successful cleanup, the loop logs decayed and
        expired counts at INFO level."""
        mock_knowledge_store.decay_confidence.return_value = 7
        mock_knowledge_store.cleanup_expired.return_value = 4

        timer = FactCleanupTimer(mock_knowledge_store, interval_hours=1)

        with (
            patch(
                "brain.fact_cleanup.asyncio.sleep",
                side_effect=[None, asyncio.CancelledError],
            ),
            caplog.at_level(logging.INFO),
        ):
            task = await timer.start()
            try:
                await task
            except asyncio.CancelledError:
                pass

        assert any(
            "7 decayed" in r.message and "4 expired" in r.message
            for r in caplog.records
        )

    @pytest.mark.asyncio
    async def test_loop_handles_none_return_values(
        self, mock_knowledge_store, caplog
    ):
        """When decay_confidence or cleanup_expired return None,
        the log shows 0 instead of crashing."""
        mock_knowledge_store.decay_confidence.return_value = None
        mock_knowledge_store.cleanup_expired.return_value = None

        timer = FactCleanupTimer(mock_knowledge_store, interval_hours=1)

        with (
            patch(
                "brain.fact_cleanup.asyncio.sleep",
                side_effect=[None, asyncio.CancelledError],
            ),
            caplog.at_level(logging.INFO),
        ):
            task = await timer.start()
            try:
                await task
            except asyncio.CancelledError:
                pass

        # Should log "0 decayed, 0 expired" when returns are None.
        assert any(
            "0 decayed" in r.message and "0 expired" in r.message
            for r in caplog.records
        )

    @pytest.mark.asyncio
    async def test_interval_conversion(self, mock_knowledge_store):
        """interval_hours is correctly converted to seconds."""
        t = FactCleanupTimer(mock_knowledge_store, interval_hours=6)
        assert t._interval == 6 * 3600

    @pytest.mark.asyncio
    async def test_default_interval(self, mock_knowledge_store):
        """Default interval is 24 hours (86400 seconds)."""
        t = FactCleanupTimer(mock_knowledge_store)
        assert t._interval == 24 * 3600
