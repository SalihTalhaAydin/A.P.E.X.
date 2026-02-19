"""
WebSocket helpers for Home Assistant registry operations.
Transient connection pattern: open, authenticate, send command,
receive result, close. Used by configure() for entity/device/area
registry operations not available via REST.
"""
from __future__ import annotations

import asyncio
import logging
import os

import aiohttp
from brain.config import settings

logger = logging.getLogger(__name__)

# WebSocket URL for HA Core API
# Inside add-on: ws://supervisor/core/websocket
# Local dev: ws://<HA_IP>:8123/api/websocket
_WS_TIMEOUT = 10  # seconds


def _get_ws_url() -> str:
    """Derive WebSocket URL from the configured HA URL."""
    ha_url = settings.ha_url
    # Replace http(s) with ws(s)
    ws_url = ha_url.replace("https://", "wss://").replace(
        "http://", "ws://"
    )
    return f"{ws_url}/websocket"


def _get_token() -> str | None:
    """Get the auth token for WebSocket connections."""
    token = os.environ.get(
        "SUPERVISOR_TOKEN", ""
    ) or settings.ha_token
    return token if token else None


async def ws_command(command: dict) -> dict:
    """Open a transient WebSocket connection, send one
    command, return the result.

    Args:
        command: The WebSocket command dict (must include
                 'type' key, e.g. 'config/entity_registry/list').

    Returns:
        The result dict from HA.

    Raises:
        ConnectionError: If the WebSocket connection fails.
        PermissionError: If authentication fails.
        TimeoutError: If the operation times out.
        RuntimeError: If no SUPERVISOR_TOKEN is available.
    """
    token = _get_token()
    if not token:
        raise RuntimeError(
            "No SUPERVISOR_TOKEN or HA_TOKEN available. "
            "WebSocket operations require authentication. "
            "In local dev mode, set HA_TOKEN in .env."
        )

    ws_url = _get_ws_url()
    logger.debug("WS connecting to %s", ws_url)

    timeout = aiohttp.ClientTimeout(total=_WS_TIMEOUT)
    try:
        async with aiohttp.ClientSession(
            timeout=timeout
        ) as session:
            async with session.ws_connect(ws_url) as ws:
                # 1. Receive auth_required
                msg = await asyncio.wait_for(
                    ws.receive_json(),
                    timeout=_WS_TIMEOUT,
                )
                if msg.get("type") != "auth_required":
                    raise ConnectionError(
                        f"Expected auth_required, got: "
                        f"{msg.get('type')}"
                    )

                # 2. Send auth
                await ws.send_json(
                    {"type": "auth", "access_token": token}
                )
                auth_result = await asyncio.wait_for(
                    ws.receive_json(),
                    timeout=_WS_TIMEOUT,
                )
                if auth_result.get("type") != "auth_ok":
                    raise PermissionError(
                        "WebSocket authentication failed: "
                        f"{auth_result.get('message', 'unknown error')}"
                    )

                # 3. Send command with id=1
                cmd = {"id": 1, **command}
                await ws.send_json(cmd)

                # 4. Receive result
                result = await asyncio.wait_for(
                    ws.receive_json(),
                    timeout=_WS_TIMEOUT,
                )
                if not result.get("success", False):
                    error = result.get("error", {})
                    raise RuntimeError(
                        f"WS command failed: "
                        f"{error.get('code', 'unknown')} - "
                        f"{error.get('message', 'no details')}"
                    )
                return result.get("result", {})

    except aiohttp.WSServerHandshakeError as e:
        raise ConnectionError(
            f"WebSocket handshake failed: {e}"
        ) from e
    except aiohttp.ClientConnectorError as e:
        raise ConnectionError(
            f"Cannot connect to HA WebSocket at {ws_url}: {e}"
        ) from e
    except asyncio.TimeoutError as e:
        raise TimeoutError(
            "WebSocket operation timed out "
            f"after {_WS_TIMEOUT}s"
        ) from e
