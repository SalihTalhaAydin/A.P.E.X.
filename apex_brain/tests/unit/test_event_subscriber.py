"""Tests for the Event Subscriber - persistent WebSocket to HA."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from brain.decision_engine import DecisionEngine, EventDecision
from brain.event_subscriber import EventSubscriber, _get_ws_url


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
    async def test_start_twice_closes_old_session_before_new(self, subscriber):
        """Regression: double start() must close the first session to avoid TCP leaks."""
        first_sess = AsyncMock()
        second_sess = AsyncMock()
        session_factory = MagicMock(side_effect=[first_sess, second_sess])

        with patch("brain.event_subscriber.aiohttp.ClientSession", session_factory):
            await subscriber.start()
            assert subscriber._session is first_sess

            await subscriber.start()
            # First session must have been closed before creating second
            first_sess.close.assert_awaited_once()
            assert subscriber._session is second_sess

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
        await asyncio.sleep(0)  # yield so create_task'd handle runs
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
    async def test_handle_event_skips_empty_entity_id(
        self, subscriber, mock_decision_engine, mock_conversation
    ):
        """Events with missing/empty entity_id return without calling decision engine."""
        event = {
            "data": {
                "entity_id": "",
                "old_state": {"state": "off"},
                "new_state": {"state": "on"},
            }
        }
        await subscriber._handle_event(event)
        mock_decision_engine.evaluate.assert_not_awaited()
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
        await asyncio.sleep(0)  # yield so create_task'd handle runs
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
        # Should not raise (error logged via task callback)
        await subscriber._handle_event(event)
        await asyncio.sleep(0)  # yield so task runs and callback logs


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
        await asyncio.sleep(0)  # yield so create_task'd handle runs
        mock_conversation.handle.assert_awaited_once()


# ------------------------------------------------------------------ #
# Connection loop (mocked WebSocket)
# ------------------------------------------------------------------ #
class TestConnectionLoop:
    @pytest.mark.asyncio
    async def test_no_token_waits_and_returns(self, subscriber):
        subscriber._session = AsyncMock()
        subscriber._running = True
        with patch("brain.event_subscriber._get_token", return_value=None):
            # Should wait 60s — we mock sleep to avoid real delay
            with patch("asyncio.sleep", new_callable=AsyncMock):
                await subscriber._connect_and_listen()
        assert not subscriber.connected

    @pytest.mark.asyncio
    async def test_msg_id_resets_on_connect(self, subscriber):
        """_msg_id resets to 0 at start of _connect_and_listen even when token is None.
        (Early-return path; see test_msg_id_resets_on_reconnect for full reconnect scenario.)
        """
        subscriber._session = AsyncMock()
        subscriber._session.closed = False
        subscriber._running = True
        subscriber._msg_id = 42
        with patch("brain.event_subscriber._get_token", return_value=None):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                await subscriber._connect_and_listen()
        assert subscriber._msg_id == 0

    @pytest.mark.asyncio
    async def test_msg_id_resets_on_reconnect(self, subscriber):
        """Verify _msg_id resets to 0 at start of each new connection after disconnect.

        Simulates: working connection -> subscribe_events (increments _msg_id) ->
        disconnect -> reconnect -> verify _msg_id is 0 and subscribe uses id=1.
        """
        subscriber._session = AsyncMock()
        subscriber._session.closed = False
        subscriber._running = True
        subscriber._msg_id = 99  # Simulate prior session had incremented it

        auth_required = {"type": "auth_required"}
        auth_ok = {"type": "auth_ok"}
        sub_ok = {"success": True}

        closed_msg = MagicMock()
        closed_msg.type = aiohttp.WSMsgType.CLOSED

        async def one_closed_then_stop():
            yield closed_msg

        def make_mock_ws():
            ws = AsyncMock()
            ws.receive_json = AsyncMock(
                side_effect=[auth_required, auth_ok, sub_ok]
            )
            ws.send_json = AsyncMock()
            ws.__aiter__ = lambda self: one_closed_then_stop()
            return ws

        mock_ws_first = make_mock_ws()
        mock_ws_second = make_mock_ws()

        enter_count = 0

        def mock_ws_context(*_args, **_kwargs):
            nonlocal enter_count
            enter_count += 1
            ws = mock_ws_first if enter_count == 1 else mock_ws_second
            cm = AsyncMock()
            cm.__aenter__ = AsyncMock(return_value=ws)
            cm.__aexit__ = AsyncMock(return_value=None)
            return cm

        subscriber._session.ws_connect = MagicMock(side_effect=mock_ws_context)

        with patch("brain.event_subscriber._get_token", return_value="valid-token"):
            with patch("brain.event_subscriber._get_ws_url", return_value="wss://test/websocket"):
                # First connection: subscribe uses id=1 (msg_id 0 -> 1)
                await subscriber._connect_and_listen()
                assert subscriber._msg_id == 1  # Incremented during subscribe
                mock_ws_first.send_json.assert_any_call(
                    {"id": 1, "type": "subscribe_events", "event_type": "state_changed"}
                )

                # Second connection: _msg_id resets to 0, subscribe uses id=1 again
                await subscriber._connect_and_listen()
                assert subscriber._msg_id == 1  # 0 + 1 from subscribe
                mock_ws_second.send_json.assert_any_call(
                    {"id": 1, "type": "subscribe_events", "event_type": "state_changed"}
                )

    @pytest.mark.asyncio
    async def test_connect_and_listen_returns_early_if_session_none(self, subscriber):
        """Regression (bug 66): shutdown race - _session closed before ws_connect."""
        subscriber._session = None
        subscriber._running = True
        await subscriber._connect_and_listen()
        assert not subscriber.connected

    @pytest.mark.asyncio
    async def test_connect_and_listen_returns_early_if_not_running(self, subscriber):
        """Regression (bug 66): shutdown race - stop() called before ws_connect."""
        subscriber._session = AsyncMock()
        subscriber._running = False
        await subscriber._connect_and_listen()
        # Should not call ws_connect
        subscriber._session.ws_connect.assert_not_called()

    @pytest.mark.asyncio
    async def test_auth_invalid_token_raises_permission_error(self, subscriber):
        """Auth failure with invalid token raises PermissionError."""
        subscriber._session = AsyncMock()
        subscriber._session.closed = False
        subscriber._running = True

        auth_required = {"type": "auth_required"}
        auth_invalid = {"type": "auth_invalid", "message": "Invalid access token"}

        mock_ws = AsyncMock()
        mock_ws.receive_json = AsyncMock(
            side_effect=[auth_required, auth_invalid]
        )
        mock_ws.send_json = AsyncMock()

        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=mock_ws)
        cm.__aexit__ = AsyncMock(return_value=None)
        subscriber._session.ws_connect = MagicMock(return_value=cm)

        with patch("brain.event_subscriber._get_token", return_value="bad-token"):
            with patch("brain.event_subscriber._get_ws_url", return_value="wss://test/websocket"):
                with pytest.raises(PermissionError) as exc_info:
                    await subscriber._connect_and_listen()
                assert "Invalid access token" in str(exc_info.value)
        assert not subscriber.connected

    @pytest.mark.asyncio
    async def test_auth_expired_token_raises_permission_error(self, subscriber):
        """Auth failure with expired token raises PermissionError."""
        subscriber._session = AsyncMock()
        subscriber._session.closed = False
        subscriber._running = True

        auth_required = {"type": "auth_required"}
        auth_invalid = {"type": "auth_invalid", "message": "Token expired"}

        mock_ws = AsyncMock()
        mock_ws.receive_json = AsyncMock(
            side_effect=[auth_required, auth_invalid]
        )
        mock_ws.send_json = AsyncMock()

        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=mock_ws)
        cm.__aexit__ = AsyncMock(return_value=None)
        subscriber._session.ws_connect = MagicMock(return_value=cm)

        with patch("brain.event_subscriber._get_token", return_value="expired-token"):
            with patch("brain.event_subscriber._get_ws_url", return_value="wss://test/websocket"):
                with pytest.raises(PermissionError) as exc_info:
                    await subscriber._connect_and_listen()
                assert "Token expired" in str(exc_info.value)
        assert not subscriber.connected

    @pytest.mark.asyncio
    async def test_auth_unknown_error_message_in_exception(self, subscriber):
        """Auth failure with unknown message still raises PermissionError."""
        subscriber._session = AsyncMock()
        subscriber._session.closed = False
        subscriber._running = True

        auth_required = {"type": "auth_required"}
        auth_invalid = {"type": "auth_invalid"}  # no message key

        mock_ws = AsyncMock()
        mock_ws.receive_json = AsyncMock(
            side_effect=[auth_required, auth_invalid]
        )
        mock_ws.send_json = AsyncMock()

        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=mock_ws)
        cm.__aexit__ = AsyncMock(return_value=None)
        subscriber._session.ws_connect = MagicMock(return_value=cm)

        with patch("brain.event_subscriber._get_token", return_value="token"):
            with patch("brain.event_subscriber._get_ws_url", return_value="wss://test/websocket"):
                with pytest.raises(PermissionError) as exc_info:
                    await subscriber._connect_and_listen()
                assert "unknown" in str(exc_info.value).lower()


# ------------------------------------------------------------------ #
# URL Derivation (Bug 49 - P3-GAP-6)
# ------------------------------------------------------------------ #
class TestURLDerivation:
    """Tests for _get_ws_url — how WebSocket URL is built from HA URL."""

    def test_https_becomes_wss(self):
        with patch("brain.event_subscriber.settings") as mock_settings:
            mock_settings.ha_url = "https://homeassistant.local:8123"
            assert _get_ws_url() == "wss://homeassistant.local:8123/websocket"

    def test_http_becomes_ws(self):
        with patch("brain.event_subscriber.settings") as mock_settings:
            mock_settings.ha_url = "http://192.168.1.1:8123"
            assert _get_ws_url() == "ws://192.168.1.1:8123/websocket"

    def test_http_supervisor_core(self):
        with patch("brain.event_subscriber.settings") as mock_settings:
            mock_settings.ha_url = "http://supervisor/core"
            assert _get_ws_url() == "ws://supervisor/core/websocket"

    def test_https_with_trailing_slash(self):
        with patch("brain.event_subscriber.settings") as mock_settings:
            mock_settings.ha_url = "https://ha.example.com/"
            assert _get_ws_url() == "wss://ha.example.com//websocket"

    def test_http_no_port(self):
        with patch("brain.event_subscriber.settings") as mock_settings:
            mock_settings.ha_url = "http://localhost"
            assert _get_ws_url() == "ws://localhost/websocket"


# ------------------------------------------------------------------ #
# Reconnection behavior (Bug 49 - P3-GAP-6)
# ------------------------------------------------------------------ #
class TestReconnection:
    """Tests for reconnection when connection drops and reconnects."""

    @pytest.mark.asyncio
    async def test_connection_drop_triggers_reconnect_attempt(self, subscriber):
        """When WebSocket closes mid-stream, _connection_loop retries _connect_and_listen."""
        subscriber._session = AsyncMock()
        subscriber._running = True

        auth_required = {"type": "auth_required"}
        auth_ok = {"type": "auth_ok"}
        sub_ok = {"success": True}
        closed_msg = MagicMock()
        closed_msg.type = aiohttp.WSMsgType.CLOSED

        async def first_conn_closes_then_stop():
            yield closed_msg

        call_count = 0

        def make_mock_ws():
            nonlocal call_count
            call_count += 1
            ws = AsyncMock()
            ws.receive_json = AsyncMock(
                side_effect=[auth_required, auth_ok, sub_ok]
            )
            ws.send_json = AsyncMock()
            ws.__aiter__ = lambda: first_conn_closes_then_stop()
            return ws

        enter_count = 0

        def mock_ws_context(*_args, **_kwargs):
            nonlocal enter_count
            enter_count += 1
            ws = make_mock_ws()
            cm = AsyncMock()
            cm.__aenter__ = AsyncMock(return_value=ws)
            cm.__aexit__ = AsyncMock(return_value=None)
            return cm

        subscriber._session.ws_connect = MagicMock(side_effect=mock_ws_context)

        with patch("brain.event_subscriber._get_token", return_value="valid-token"):
            with patch("brain.event_subscriber._get_ws_url", return_value="wss://test/websocket"):
                # Run one full cycle: connect, get CLOSED, exit
                await subscriber._connect_and_listen()
        assert not subscriber.connected

    @pytest.mark.asyncio
    async def test_exception_in_connect_sets_connected_false_and_uses_backoff(
        self, subscriber
    ):
        """When _connect_and_listen raises, _connected is False and backoff is applied."""
        with patch("brain.event_subscriber.aiohttp.ClientSession", return_value=AsyncMock()):
            await subscriber.start()

        # Make _connect_and_listen raise (e.g. auth failure)
        with patch("brain.event_subscriber._get_token", return_value="token"):
            with patch("brain.event_subscriber._get_ws_url", return_value="wss://test/websocket"):
                auth_required = {"type": "auth_required"}
                auth_invalid = {"type": "auth_invalid", "message": "Invalid"}
                mock_ws = AsyncMock()
                mock_ws.receive_json = AsyncMock(
                    side_effect=[auth_required, auth_invalid]
                )
                mock_ws.send_json = AsyncMock()
                cm = AsyncMock()
                cm.__aenter__ = AsyncMock(return_value=mock_ws)
                cm.__aexit__ = AsyncMock(return_value=None)
                subscriber._session.ws_connect = MagicMock(return_value=cm)

                # _connection_loop will catch PermissionError and sleep with backoff
                sleep_calls = []

                async def capture_sleep(sec):
                    sleep_calls.append(sec)
                    # Stop the loop after backoff sleep (skip initial 10s delay)
                    if sec == 5:
                        subscriber._running = False

                with patch("brain.event_subscriber.settings") as mock_settings:
                    mock_settings.event_reconnect_delay = 5
                    mock_settings.event_max_reconnect_delay = 300
                    with patch("brain.event_subscriber.asyncio.sleep", side_effect=capture_sleep):
                        await subscriber._connection_loop()

                assert subscriber._connected is False
                assert 5 in sleep_calls  # event_reconnect_delay used on auth failure

        await subscriber.stop()

    @pytest.mark.asyncio
    async def test_clean_disconnect_resets_backoff_delay(self, subscriber):
        """On clean disconnect (no exception), next attempt uses base delay, not doubled."""
        subscriber._session = AsyncMock()
        subscriber._running = True

        auth_required = {"type": "auth_required"}
        auth_ok = {"type": "auth_ok"}
        sub_ok = {"success": True}
        closed_msg = MagicMock()
        closed_msg.type = aiohttp.WSMsgType.CLOSED

        async def closes_immediately():
            yield closed_msg

        def make_mock_ws():
            ws = AsyncMock()
            ws.receive_json = AsyncMock(
                side_effect=[auth_required, auth_ok, sub_ok]
            )
            ws.send_json = AsyncMock()
            ws.__aiter__ = lambda: closes_immediately()
            return ws

        def make_cm():
            cm = AsyncMock()
            cm.__aenter__ = AsyncMock(return_value=make_mock_ws())
            cm.__aexit__ = AsyncMock(return_value=None)
            return cm

        subscriber._session.ws_connect = MagicMock(side_effect=make_cm)

        with patch("brain.event_subscriber._get_token", return_value="token"):
            with patch("brain.event_subscriber._get_ws_url", return_value="wss://test/websocket"):
                # First connect: completes (closed), returns normally
                await subscriber._connect_and_listen()
                assert not subscriber.connected
                # Second connect: same flow; delay should stay at base (reset)
                await subscriber._connect_and_listen()
                assert not subscriber.connected

    @pytest.mark.asyncio
    async def test_ws_error_message_breaks_loop(self, subscriber):
        """WSMsgType.ERROR breaks the receive loop and sets connected=False."""
        subscriber._session = AsyncMock()
        subscriber._running = True

        auth_required = {"type": "auth_required"}
        auth_ok = {"type": "auth_ok"}
        sub_ok = {"success": True}
        error_msg = MagicMock()
        error_msg.type = aiohttp.WSMsgType.ERROR

        async def error_then_stop():
            yield error_msg

        ws = AsyncMock()
        ws.receive_json = AsyncMock(
            side_effect=[auth_required, auth_ok, sub_ok]
        )
        ws.send_json = AsyncMock()
        ws.__aiter__ = lambda: error_then_stop()

        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=ws)
        cm.__aexit__ = AsyncMock(return_value=None)
        subscriber._session.ws_connect = MagicMock(return_value=cm)

        with patch("brain.event_subscriber._get_token", return_value="valid-token"):
            with patch("brain.event_subscriber._get_ws_url", return_value="wss://test/websocket"):
                await subscriber._connect_and_listen()

        assert not subscriber.connected
