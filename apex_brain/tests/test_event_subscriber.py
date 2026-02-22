"""Tests for the Event Subscriber - persistent WebSocket to HA."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from brain.decision_engine import DecisionEngine, EventDecision
from brain.event_subscriber import EventSubscriber


@pytest.fixture
def mock_conversation():
    conv = AsyncMock()
    conv.handle = AsyncMock(return_value="OK")
    return conv


@pytest.fixture
def mock_decision_engine():
    de = AsyncMock(spec=DecisionEngine)
    de.evaluate = AsyncMock(
        return_value=EventDecision(True, 0.8, "test", "high")
    )
    return de


@pytest.fixture
def subscriber(mock_conversation, mock_decision_engine):
    return EventSubscriber(mock_conversation, mock_decision_engine)


# ------------------------------------------------------------------ #
# Initialization
# ------------------------------------------------------------------ #
class TestInit:
    def test_initial_state(self, subscriber):
        assert not subscriber.connected

    @pytest.mark.asyncio
    async def test_start_creates_session(self, subscriber):
        mock_sess = AsyncMock()
        with patch("brain.event_subscriber.aiohttp.ClientSession", return_value=mock_sess):
            await subscriber.start()
            # Stop immediately to clean up
            await subscriber.stop()

    @pytest.mark.asyncio
    async def test_stop_sets_not_connected(self, subscriber):
        subscriber._connected = True
        subscriber._running = True
        subscriber._session = AsyncMock()
        await subscriber.stop()
        assert not subscriber.connected


# ------------------------------------------------------------------ #
# Event handling
# ------------------------------------------------------------------ #
class TestHandleEvent:
    @pytest.mark.asyncio
    async def test_significant_event_processed(
        self, subscriber, mock_conversation, mock_decision_engine
    ):
        mock_decision_engine.evaluate = AsyncMock(
            return_value=EventDecision(True, 0.8, "passed", "high")
        )
        event = {
            "data": {
                "entity_id": "binary_sensor.front_door",
                "old_state": {"state": "off", "attributes": {}},
                "new_state": {"state": "on", "attributes": {"friendly_name": "Front Door"}},
            }
        }
        await subscriber._handle_event(event)
        mock_conversation.handle.assert_awaited_once()
        call_msg = mock_conversation.handle.call_args[0][0]
        assert "Front Door" in call_msg
        assert "HIGH" in call_msg

    @pytest.mark.asyncio
    async def test_insignificant_event_skipped(
        self, subscriber, mock_conversation, mock_decision_engine
    ):
        mock_decision_engine.evaluate = AsyncMock(
            return_value=EventDecision(False, 0.1, "below threshold", "low")
        )
        event = {
            "data": {
                "entity_id": "sensor.temperature",
                "old_state": {"state": "72.0", "attributes": {}},
                "new_state": {"state": "72.1", "attributes": {}},
            }
        }
        await subscriber._handle_event(event)
        mock_conversation.handle.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_handle_event_with_none_states(
        self, subscriber, mock_decision_engine, mock_conversation
    ):
        mock_decision_engine.evaluate = AsyncMock(
            return_value=EventDecision(True, 0.5, "passed", "medium")
        )
        event = {
            "data": {
                "entity_id": "light.new",
                "old_state": None,
                "new_state": {"state": "on", "attributes": {}},
            }
        }
        await subscriber._handle_event(event)
        # Should handle None old_state gracefully
        mock_conversation.handle.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_handle_event_conversation_error(
        self, subscriber, mock_decision_engine, mock_conversation
    ):
        mock_decision_engine.evaluate = AsyncMock(
            return_value=EventDecision(True, 0.9, "passed", "critical")
        )
        mock_conversation.handle = AsyncMock(side_effect=Exception("LLM error"))
        event = {
            "data": {
                "entity_id": "lock.front",
                "old_state": {"state": "locked", "attributes": {}},
                "new_state": {"state": "unlocked", "attributes": {}},
            }
        }
        # Should not raise
        await subscriber._handle_event(event)


# ------------------------------------------------------------------ #
# Message building
# ------------------------------------------------------------------ #
class TestBuildMessage:
    def test_message_includes_entity_info(self, subscriber):
        from brain.event_handler import WebhookEvent

        event = WebhookEvent(
            event_type="state_changed",
            entity_id="binary_sensor.front_door",
            old_state="off",
            new_state="on",
            attributes={"friendly_name": "Front Door"},
        )
        decision = EventDecision(True, 0.8, "passed", "high")
        msg = subscriber._build_event_message(event, decision)
        assert "Front Door" in msg
        assert "binary_sensor.front_door" in msg
        assert "off" in msg
        assert "on" in msg
        assert "HIGH" in msg
        assert "0.80" in msg

    def test_message_uses_entity_id_as_fallback_name(self, subscriber):
        from brain.event_handler import WebhookEvent

        event = WebhookEvent(
            event_type="state_changed",
            entity_id="binary_sensor.garage_door",
            old_state="off",
            new_state="on",
        )
        decision = EventDecision(True, 0.7, "passed", "medium")
        msg = subscriber._build_event_message(event, decision)
        assert "Garage Door" in msg


    @pytest.mark.asyncio
    async def test_handle_event_with_string_states(
        self, subscriber, mock_decision_engine, mock_conversation
    ):
        """Non-dict states are handled gracefully (empty strings)."""
        mock_decision_engine.evaluate = AsyncMock(
            return_value=EventDecision(True, 0.5, "passed", "medium")
        )
        event = {
            "data": {
                "entity_id": "light.test",
                "old_state": "some_string",
                "new_state": "another_string",
            }
        }
        await subscriber._handle_event(event)
        mock_conversation.handle.assert_awaited_once()


# ------------------------------------------------------------------ #
# Connection loop (mocked WebSocket)
# ------------------------------------------------------------------ #
class TestConnectionLoop:
    @pytest.mark.asyncio
    async def test_no_token_waits_and_returns(self, subscriber):
        with patch("brain.event_subscriber._get_token", return_value=None):
            # Should wait 60s — we mock sleep to avoid real delay
            with patch("asyncio.sleep", new_callable=AsyncMock):
                await subscriber._connect_and_listen()
        assert not subscriber.connected

    @pytest.mark.asyncio
    async def test_msg_id_resets_on_connect(self, subscriber):
        """_msg_id resets to 0 on each new connection attempt."""
        subscriber._msg_id = 42
        with patch("brain.event_subscriber._get_token", return_value=None):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                await subscriber._connect_and_listen()
        assert subscriber._msg_id == 0
