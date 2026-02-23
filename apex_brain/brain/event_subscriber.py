"""
Event Subscriber - Persistent WebSocket connection to Home Assistant.

Subscribes to state_changed events, filters through the Decision Engine,
and routes significant events to the conversation orchestrator.
"""

from __future__ import annotations

import asyncio
import logging
import uuid

import aiohttp

from brain.config import settings
from brain.decision_engine import DecisionEngine
from brain.event_handler import WebhookEvent

logger = logging.getLogger(__name__)


def _get_ws_url() -> str:
    """Derive WebSocket URL from the configured HA URL."""
    ha_url = settings.ha_url
    ws_url = ha_url.replace("https://", "wss://").replace(
        "http://", "ws://"
    )
    return f"{ws_url}/websocket"


def _get_token() -> str | None:
    """Get the auth token for WebSocket connections."""
    import os

    token = os.environ.get("SUPERVISOR_TOKEN", "") or settings.ha_token
    return token if token else None


class EventSubscriber:
    """Persistent WebSocket connection to HA for real-time state change events."""

    def __init__(
        self,
        conversation,
        decision_engine: DecisionEngine,
    ):
        self._conversation = conversation
        self._decision_engine = decision_engine
        self._session: aiohttp.ClientSession | None = None
        self._running = False
        self._connected = False
        self._msg_id = 0
        self._loop_task: asyncio.Task | None = None
        self._event_tasks: set = set()  # fire-and-forget tasks, discarded on done

    @property
    def connected(self) -> bool:
        return self._connected

    async def start(self) -> None:
        """Start the event subscription loop with reconnection."""
        # If start() is called twice (retry, duplicate creation, race), close the
        # existing session first to avoid TCP connection leaks.
        if self._session is not None:
            await self._session.close()
            self._session = None
        if self._loop_task is not None:
            self._loop_task.cancel()
            try:
                await self._loop_task
            except asyncio.CancelledError:
                pass
            self._loop_task = None

        self._running = True
        self._session = aiohttp.ClientSession()
        self._loop_task = asyncio.create_task(self._connection_loop())
        logger.info("EventSubscriber starting")

    async def stop(self) -> None:
        """Graceful shutdown."""
        self._running = False
        self._connected = False
        if self._loop_task:
            self._loop_task.cancel()
            try:
                await self._loop_task
            except asyncio.CancelledError:
                pass
        if self._session:
            await self._session.close()
            self._session = None
        logger.info("EventSubscriber stopped")

    async def _connection_loop(self) -> None:
        """Reconnection loop with exponential backoff."""
        delay = settings.event_reconnect_delay
        # Initial delay to let the server fully start
        await asyncio.sleep(10)
        while self._running:
            try:
                await self._connect_and_listen()
                delay = (
                    settings.event_reconnect_delay
                )  # reset on clean disconnect
            except asyncio.CancelledError:
                break
            except Exception as e:
                self._connected = False
                logger.error("EventSubscriber connection error: %s", e)
                if self._running:
                    logger.info("Reconnecting in %ds...", delay)
                    await asyncio.sleep(delay)
                    delay = min(
                        delay * 2, settings.event_max_reconnect_delay
                    )

    async def _connect_and_listen(self) -> None:
        """Connect, authenticate, subscribe, and process events."""
        if self._session is None or not self._running:
            return
        # P3-BUG-114: During shutdown race, _session can be closed before
        # ws_connect (e.g. start() called again, or stop() ordering). Skip
        # connect if session is already closed to avoid confusing error logs.
        if getattr(self._session, "closed", False):
            return
        self._msg_id = 0  # Reset on each new connection
        ws_url = _get_ws_url()
        token = _get_token()
        if not token:
            logger.warning("EventSubscriber: no auth token, skipping")
            # Wait and retry later instead of spinning
            await asyncio.sleep(60)
            return

        try:
            async with self._session.ws_connect(ws_url) as ws:
                # 1. Auth handshake (with timeouts)
                auth_required = await asyncio.wait_for(
                    ws.receive_json(), timeout=30
                )
                if auth_required.get("type") != "auth_required":
                    raise ConnectionError(
                        f"Expected auth_required, got "
                        f"{auth_required.get('type')}"
                    )
                await ws.send_json({"type": "auth", "access_token": token})
                auth_result = await asyncio.wait_for(
                    ws.receive_json(), timeout=30
                )
                if auth_result.get("type") != "auth_ok":
                    raise PermissionError(
                        f"Auth failed: {auth_result.get('message', 'unknown')}"
                    )

                # 2. Subscribe to state_changed events
                self._msg_id += 1
                await ws.send_json(
                    {
                        "id": self._msg_id,
                        "type": "subscribe_events",
                        "event_type": "state_changed",
                    }
                )
                sub_result = await asyncio.wait_for(
                    ws.receive_json(), timeout=30
                )
                if not sub_result.get("success"):
                    raise RuntimeError(f"Subscribe failed: {sub_result}")

                self._connected = True
                logger.info(
                    "EventSubscriber: connected and listening for state_changed events"
                )

                # 3. Listen for events
                async for msg in ws:
                    if not self._running:
                        break
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        try:
                            data = msg.json()
                        except Exception:
                            logger.warning(
                                "Malformed WebSocket message, skipping"
                            )
                            continue
                        if data.get("type") == "event":
                            task = asyncio.create_task(
                                self._handle_event(data.get("event", {}))
                            )
                            self._event_tasks.add(task)
                            task.add_done_callback(self._event_tasks.discard)
                    elif msg.type in (
                        aiohttp.WSMsgType.CLOSED,
                        aiohttp.WSMsgType.ERROR,
                    ):
                        logger.warning("WebSocket closed/error: %s", msg)
                        break
        except (RuntimeError, aiohttp.ClientError) as e:
            # P3-BUG-114: Session closed during shutdown race; avoid noisy logs
            if "closed" not in str(e).lower():
                raise
            logger.debug(
                "EventSubscriber: session closed before/during ws_connect (shutdown race): %s",
                e,
            )
            return

        self._connected = False

    async def _handle_event(self, event: dict) -> None:
        """Process a state_changed event through the decision engine."""
        event_data = event.get("data", {})
        entity_id = event_data.get("entity_id", "")
        if not entity_id:
            return  # Skip events with missing entity_id
        old_state = event_data.get("old_state")
        if not isinstance(old_state, dict):
            old_state = {}
        new_state = event_data.get("new_state")
        if not isinstance(new_state, dict):
            new_state = {}

        # Build a WebhookEvent-compatible structure
        webhook_event = WebhookEvent(
            event_type="state_changed",
            entity_id=entity_id,
            old_state=old_state.get("state", ""),
            new_state=new_state.get("state", ""),
            attributes=new_state.get("attributes", {}),
        )

        # Run through decision engine
        decision = await self._decision_engine.evaluate(webhook_event)

        if decision.should_process:
            msg = self._build_event_message(webhook_event, decision)
            # BUG-64: Always use fresh uuid per event so conversation histories
            # do not bleed together (do not trust HA context.id reuse).
            session_id = f"apex_events:{entity_id}:{uuid.uuid4().hex[:12]}"
            task = asyncio.create_task(
                self._conversation.handle(msg, session_id=session_id)
            )

            def _on_done(t: asyncio.Task) -> None:
                try:
                    t.result()
                except Exception as e:
                    logger.error(
                        "Failed to process event for %s: %s",
                        entity_id,
                        e,
                    )

            task.add_done_callback(_on_done)

    def _build_event_message(self, event: WebhookEvent, decision) -> str:
        """Convert an event to a natural language message for the AI."""
        name = (
            event.attributes.get("friendly_name")
            or event.entity_id.split(".")[-1].replace("_", " ").title()
        )
        msg = (
            f"[EVENT: {decision.priority.upper()}] "
            f"{name} ({event.entity_id}) changed from "
            f"'{event.old_state}' to '{event.new_state}'. "
            f"Significance: {decision.significance_score:.2f}. "
            f"Assess and take action if appropriate."
        )
        return msg
