"""
Tests for ws_helpers.ws_command() exception handling.
Verifies that socket/aiohttp errors are caught and re-raised as ConnectionError
so configure() can handle them (BUG-44).
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp

from tools.ws_helpers import ws_command


def _make_auth_ok_mock_ws(send_json_raises=None):
    """Build mock WS that completes auth, optionally raises on send_json."""
    mock_ws = AsyncMock()
    mock_ws.receive_json.side_effect = [
        {"type": "auth_required"},
        {"type": "auth_ok"},
        {"success": True, "result": {}},
    ]

    async def send_json_impl(obj):
        if send_json_raises:
            raise send_json_raises

    mock_ws.send_json = send_json_impl
    return mock_ws


def _make_ws_connect_raise(exc):
    """Build mock ws_connect that raises on __aenter__."""

    class RaisingCM:
        def __init__(self, e):
            self._exc = e

        async def __aenter__(self):
            raise self._exc

        async def __aexit__(self, *args):
            pass

    return RaisingCM(exc)


def _make_session_mock(ws=None, ws_connect_raises=None):
    """Build mock ClientSession; if ws_connect_raises, ws_connect raises."""
    mock_session = MagicMock()

    if ws_connect_raises:
        mock_cm = _make_ws_connect_raise(ws_connect_raises)
        mock_session.ws_connect.return_value = mock_cm
    else:
        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=ws)
        mock_cm.__aexit__ = AsyncMock(return_value=None)
        mock_session.ws_connect.return_value = mock_cm

    session_instance = MagicMock()
    session_instance.ws_connect = mock_session.ws_connect
    session_instance.__aenter__ = AsyncMock(return_value=session_instance)
    session_instance.__aexit__ = AsyncMock(return_value=None)

    return session_instance


class TestWsCommandExceptionConversion:
    """Verify ws_command catches and converts exceptions to ConnectionError."""

    @pytest.mark.asyncio
    async def test_client_os_error_converted_to_connection_error(self):
        """ClientOSError (broken pipe, connection reset) → ConnectionError."""
        mock_ws = _make_auth_ok_mock_ws(
            send_json_raises=aiohttp.ClientOSError(32, "Broken pipe")
        )
        mock_session = _make_session_mock(ws=mock_ws)

        with patch(
            "tools.ws_helpers.aiohttp.ClientSession",
            return_value=mock_session,
        ), patch("tools.ws_helpers._get_token", return_value="fake_token"):
            with pytest.raises(ConnectionError) as exc_info:
                await ws_command({"type": "config/entity_registry/list"})
            msg = str(exc_info.value)
            assert "broken pipe" in msg.lower() or "Broken pipe" in msg

    @pytest.mark.asyncio
    async def test_client_error_converted_to_connection_error(self):
        """aiohttp.ClientError (generic) → ConnectionError."""
        mock_session = _make_session_mock(
            ws_connect_raises=aiohttp.ClientError("Connection refused"),
        )

        with patch(
            "tools.ws_helpers.aiohttp.ClientSession",
            return_value=mock_session,
        ), patch("tools.ws_helpers._get_token", return_value="fake_token"):
            with pytest.raises(ConnectionError) as exc_info:
                await ws_command({"type": "config/entity_registry/list"})
            msg = str(exc_info.value).lower()
            assert "client error" in msg or "refused" in msg

    @pytest.mark.asyncio
    async def test_connection_reset_error_converted_to_connection_error(self):
        """ConnectionResetError (socket-level) → ConnectionError."""
        mock_session = _make_session_mock(
            ws_connect_raises=ConnectionResetError(
                104, "Connection reset by peer"
            ),
        )

        with patch(
            "tools.ws_helpers.aiohttp.ClientSession",
            return_value=mock_session,
        ), patch("tools.ws_helpers._get_token", return_value="fake_token"):
            with pytest.raises(ConnectionError) as exc_info:
                await ws_command({"type": "config/entity_registry/list"})
            assert "reset" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_os_error_converted_to_connection_error(self):
        """OSError (socket-level, e.g. BrokenPipeError) → ConnectionError."""
        mock_session = _make_session_mock(
            ws_connect_raises=OSError(32, "Broken pipe")
        )

        with patch(
            "tools.ws_helpers.aiohttp.ClientSession",
            return_value=mock_session,
        ), patch("tools.ws_helpers._get_token", return_value="fake_token"):
            with pytest.raises(ConnectionError) as exc_info:
                await ws_command({"type": "config/entity_registry/list"})
            msg = str(exc_info.value)
            assert "socket" in msg.lower() or "Broken" in msg


class TestWsCommandConfigureIntegration:
    """Verify converted ConnectionErrors are handled by configure()."""

    @pytest.mark.asyncio
    async def test_configure_handles_connection_error_from_ws_command(self):
        """configure() catches ConnectionError and returns user-facing message."""
        from tools.configure import configure

        with patch(
            "tools.configure.ws_command",
            new_callable=AsyncMock,
            side_effect=ConnectionError(
                "WebSocket connection lost (broken pipe/reset)"
            ),
        ):
            result = await configure(
                action="rename",
                target="light.test",
                data={"name": "Test"},
            )
            assert "Connection error" in result
