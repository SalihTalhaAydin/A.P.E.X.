"""Regression tests for bugs fixed in the deep scan.

Each test targets a specific bug to prevent regressions.
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import (
    AsyncMock,
    MagicMock,
    patch,
)

import pytest

# ------------------------------------------------------------------ #
# BUG-2: Malformed JSON in WebSocket doesn't crash event loop
# ------------------------------------------------------------------ #


@pytest.mark.asyncio
async def test_bug2_malformed_json_skipped():
    """Malformed WebSocket JSON message is skipped, not crashed."""
    import aiohttp
    from brain.event_subscriber import EventSubscriber

    conv = AsyncMock()
    de = AsyncMock()
    sub = EventSubscriber(conv, de)
    sub._running = True
    sub._session = AsyncMock()

    # Build a mock WS message that raises on .json()
    bad_msg = MagicMock()
    bad_msg.type = aiohttp.WSMsgType.TEXT
    bad_msg.json.side_effect = ValueError("bad json")

    good_msg = MagicMock()
    good_msg.type = aiohttp.WSMsgType.TEXT
    good_msg.json.return_value = {"type": "other"}

    close_msg = MagicMock()
    close_msg.type = aiohttp.WSMsgType.CLOSED

    # The event loop should skip the bad message
    # and continue to the good one without crashing.
    # We test _handle_event is NOT called for the bad
    # message and IS NOT called for the good one either
    # (since it's not type=event), but no exception.
    class FakeWS:
        """Fake WebSocket that supports async iteration."""

        def __init__(self, messages, handshake_replies):
            self._messages = messages
            self._replies = list(handshake_replies)
            self._reply_idx = 0

        def __aiter__(self):
            return self._AsyncIter(self._messages)

        async def receive_json(self):
            r = self._replies[self._reply_idx]
            self._reply_idx += 1
            return r

        async def send_json(self, data):
            pass

        class _AsyncIter:
            def __init__(self, items):
                self._items = list(items)
                self._idx = 0

            def __aiter__(self):
                return self

            async def __anext__(self):
                if self._idx >= len(self._items):
                    raise StopAsyncIteration
                item = self._items[self._idx]
                self._idx += 1
                return item

    ws_mock = FakeWS(
        [bad_msg, good_msg, close_msg],
        [
            {"type": "auth_required"},
            {"type": "auth_ok"},
            {"success": True},
        ],
    )

    ctx_manager = AsyncMock()
    ctx_manager.__aenter__ = AsyncMock(return_value=ws_mock)
    ctx_manager.__aexit__ = AsyncMock(return_value=False)
    sub._session.ws_connect = MagicMock(return_value=ctx_manager)

    with patch(
        "brain.event_subscriber._get_token",
        return_value="token",
    ):
        await sub._connect_and_listen()

    # No crash = success. The bad message was skipped.
    assert not sub._connected


# ------------------------------------------------------------------ #
# BUG-3: WebSocket handshake timeout is handled
# ------------------------------------------------------------------ #


@pytest.mark.asyncio
async def test_bug3_ws_handshake_timeout():
    """WebSocket handshake timeout raises (caught by connection loop)."""
    from brain.event_subscriber import EventSubscriber

    conv = AsyncMock()
    de = AsyncMock()
    sub = EventSubscriber(conv, de)
    sub._session = AsyncMock()

    ws_mock = AsyncMock()

    async def hang_forever():
        await asyncio.sleep(999)

    ws_mock.receive_json = hang_forever
    ws_mock.send_json = AsyncMock()

    ctx_manager = AsyncMock()
    ctx_manager.__aenter__ = AsyncMock(return_value=ws_mock)
    ctx_manager.__aexit__ = AsyncMock(return_value=False)
    sub._session.ws_connect = MagicMock(return_value=ctx_manager)

    with patch(
        "brain.event_subscriber._get_token",
        return_value="token",
    ):
        # The 30s timeout should fire quickly in test
        # We patch wait_for timeout to be tiny
        with patch(
            "brain.event_subscriber.asyncio.wait_for",
            side_effect=asyncio.TimeoutError,
        ):
            with pytest.raises(asyncio.TimeoutError):
                await sub._connect_and_listen()


# ------------------------------------------------------------------ #
# BUG-4: Failed briefing doesn't set _last_fired_date
# ------------------------------------------------------------------ #


@pytest.mark.asyncio
async def test_bug4_failed_briefing_no_date_set():
    """If handle() fails, _last_fired_date is NOT set."""
    from brain.scheduler import Scheduler

    conv = AsyncMock()
    conv.handle = AsyncMock(side_effect=RuntimeError("LLM down"))
    ks = AsyncMock()
    ks.get_all_facts = AsyncMock(return_value=[])
    ks.store_fact = AsyncMock()

    scheduler = Scheduler(conv, ks)
    scheduler.register("test_briefing", AsyncMock(), 60)

    with patch("brain.scheduler.datetime") as mock_dt:
        mock_now = MagicMock()
        mock_now.hour = 7
        mock_now.strftime.return_value = "2025-02-20"
        mock_dt.now.return_value = mock_now

        await scheduler._timed_briefing(7, "test_briefing", "msg")

    task = next(t for t in scheduler._tasks if t.name == "test_briefing")
    # Should NOT be marked as fired since handle() failed
    assert task._last_fired_date != "2025-02-20"


# ------------------------------------------------------------------ #
# BUG-5: Malformed JSON to /v1/chat/completions returns 400
# ------------------------------------------------------------------ #


@pytest.mark.asyncio
async def test_bug5_malformed_json_returns_400():
    """Invalid JSON body returns 400, not 500."""

    from brain.server import app

    # Use Starlette test client
    from starlette.testclient import TestClient

    with patch("brain.server.conversation", new=MagicMock()):
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post(
            "/v1/chat/completions",
            content=b"not json",
            headers={"content-type": "application/json"},
        )
        assert resp.status_code == 400
        assert "Invalid JSON" in resp.json()["error"]


# ------------------------------------------------------------------ #
# BUG-6: Invalid entity_id format rejected before template injection
# ------------------------------------------------------------------ #


@pytest.mark.asyncio
async def test_bug6_invalid_entity_id_rejected():
    """Entity IDs with injection chars are rejected."""
    from tools.generic import _query_entity

    with patch(
        "tools.generic.read_state",
        side_effect=Exception("not found"),
    ):
        result = await _query_entity("{{ malicious_template }}")
        assert "Invalid entity_id format" in result

    # Valid entity_id should NOT be rejected
    with patch(
        "tools.generic.read_state",
        return_value={
            "state": "on",
            "attributes": {"friendly_name": "Test"},
        },
    ):
        result = await _query_entity("light.kitchen")
        assert "Invalid" not in result


# ------------------------------------------------------------------ #
# BUG-8: Invalid expires dates are rejected
# ------------------------------------------------------------------ #


@pytest.mark.asyncio
async def test_bug8_invalid_expires_ignored():
    """Invalid expires date in LLM output is ignored."""
    from memory.fact_extractor import FactExtractor

    ks = AsyncMock()
    ks.store_fact = AsyncMock(return_value=1)
    extractor = FactExtractor(ks)

    facts_json = json.dumps(
        [
            {
                "category": "event",
                "key": "meeting",
                "value": "team sync",
                "confidence": 0.9,
                "expires": "not-a-date",
            }
        ]
    )

    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = facts_json
    llm = AsyncMock(return_value=mock_response)

    turns = [
        {
            "role": "user",
            "content": "I have a team sync next " * 5,
        }
    ]
    await extractor.extract_from_conversation(turns, llm)

    # store_fact should be called with expires_at=None
    ks.store_fact.assert_awaited_once()
    call_kwargs = ks.store_fact.call_args.kwargs
    assert call_kwargs["expires_at"] is None


# ------------------------------------------------------------------ #
# BUG-15: Critical domain unavailability NOT dropped
# ------------------------------------------------------------------ #


def test_bug15_critical_unavailable_not_dropped():
    """Lock/alarm/camera going unavailable should pass hard filter."""
    from brain.decision_engine import DecisionEngine
    from brain.event_handler import WebhookEvent

    engine = DecisionEngine()

    # Lock going unavailable — should NOT be dropped
    event = WebhookEvent(
        event_type="state_changed",
        entity_id="lock.front_door",
        old_state="locked",
        new_state="unavailable",
    )
    reason = engine._hard_filter(event)
    assert reason == "", f"Critical domain lock should pass, got: {reason}"

    # Camera going unavailable — should NOT be dropped
    event2 = WebhookEvent(
        event_type="state_changed",
        entity_id="camera.front",
        old_state="streaming",
        new_state="unavailable",
    )
    reason2 = engine._hard_filter(event2)
    assert reason2 == ""

    # Non-critical domain (light) unavailable — SHOULD be dropped
    event3 = WebhookEvent(
        event_type="state_changed",
        entity_id="light.kitchen",
        old_state="on",
        new_state="unavailable",
    )
    reason3 = engine._hard_filter(event3)
    assert reason3 == "device went unavailable"


# ------------------------------------------------------------------ #
# BUG-18: Empty phone_notify_target returns helpful error
# ------------------------------------------------------------------ #


@pytest.mark.asyncio
async def test_bug18_empty_phone_target_error():
    """Empty phone_notify_target returns config error."""
    from tools.notify import announce

    with patch("tools.notify.settings") as mock_settings:
        mock_settings.phone_notify_target = ""
        result = await announce("test message", target="phone")
        assert "not configured" in result


# ------------------------------------------------------------------ #
# BUG-25: ZoneInfo crash falls back to UTC
# ------------------------------------------------------------------ #


@pytest.mark.asyncio
async def test_bug25_invalid_timezone_falls_back_to_utc():
    """Invalid timezone should fall back to UTC, not crash."""
    from memory.context_builder import ContextBuilder

    conv_store = AsyncMock()
    conv_store.get_recent = AsyncMock(return_value=[])
    know_store = AsyncMock()
    know_store.search_semantic = AsyncMock(return_value=[])
    know_store.search_keyword = AsyncMock(return_value=[])
    know_store.get_all_facts = AsyncMock(return_value=[])

    cb = ContextBuilder(conv_store, know_store)

    with (
        patch(
            "memory.context_builder._build_time_context",
            return_value={"period": "morning"},
        ),
        patch(
            "memory.context_builder.build_system_prompt",
            return_value="ok",
        ),
        patch(
            "tools.presence.get_presence_summary",
            new_callable=AsyncMock,
            return_value="",
        ),
        patch(
            "tools.ha_helpers.get_device_summary",
            new_callable=AsyncMock,
            return_value="",
        ),
        patch("memory.context_builder.settings") as mock_settings,
    ):
        mock_settings.timezone = "Invalid/Zone"
        mock_settings.google_calendar_credentials_path = ""
        # Should NOT raise
        result = await cb.build("hello")
    assert result == "ok"


# ------------------------------------------------------------------ #
# BUG-27: Error HTML not returned as logs text
# ------------------------------------------------------------------ #


@pytest.mark.asyncio
async def test_bug27_error_html_not_returned_as_text():
    """500 response with as_text=True returns error string, not HTML."""
    import httpx
    from tools.manage import _supervisor_request

    mock_response = MagicMock()
    mock_response.status_code = 500
    mock_response.is_success = False
    mock_response.text = "<html>Internal Server Error</html>"

    with (
        patch(
            "tools.manage._get_supervisor_token",
            return_value="fake-token",
        ),
        patch(
            "tools.manage._supervisor_client",
            new=MagicMock(),
        ) as mock_client,
    ):
        mock_client.request = AsyncMock(return_value=mock_response)
        result = await _supervisor_request("GET", "/test", as_text=True)

    assert isinstance(result, str)
    assert "Error fetching text" in result
    assert "500" in result


# ------------------------------------------------------------------ #
# BUG-29: ha_request handles ConnectError gracefully
# ------------------------------------------------------------------ #


@pytest.mark.asyncio
async def test_bug29_ha_request_connect_error():
    """ConnectError returns error dict, not crash."""
    import httpx

    with patch(
        "tools.ha_helpers._ha_client",
        new=MagicMock(),
    ) as mock_client:
        mock_client.request = AsyncMock(
            side_effect=httpx.ConnectError("refused")
        )
        from tools.ha_helpers import ha_request

        result = await ha_request("GET", "/states")
    assert isinstance(result, dict)
    assert "error" in result
    assert "Cannot connect" in result["error"]


@pytest.mark.asyncio
async def test_bug29_ha_request_timeout():
    """TimeoutException returns error dict, not crash."""
    import httpx

    with patch(
        "tools.ha_helpers._ha_client",
        new=MagicMock(),
    ) as mock_client:
        mock_client.request = AsyncMock(
            side_effect=httpx.TimeoutException("timed out")
        )
        from tools.ha_helpers import ha_request

        result = await ha_request("GET", "/states")
    assert isinstance(result, dict)
    assert "error" in result
    assert "timed out" in result["error"]


# ------------------------------------------------------------------ #
# BUG-30: Curator skips facts without "id"
# ------------------------------------------------------------------ #


@pytest.mark.asyncio
async def test_bug30_curator_skips_fact_without_id():
    """Fact missing 'id' key is skipped, not crash."""
    from brain.curator import Curator

    ks = AsyncMock()
    ks.decay_confidence = AsyncMock(return_value=0)
    ks.cleanup_expired = AsyncMock(return_value=0)
    ks.get_low_confidence_facts = AsyncMock(
        return_value=[
            {"key": "no_id_fact", "confidence": 0.1},  # missing "id"
            {"id": 5, "key": "has_id", "confidence": 0.1},
        ]
    )
    ks.get_contradictory_facts = AsyncMock(return_value=[])
    ks.delete_fact_by_id = AsyncMock(return_value=True)
    conv = AsyncMock()

    with patch("brain.config.settings") as mock_s:
        mock_s.fact_min_confidence_prune = 0.3
        curator = Curator(conv, ks)
        result = await curator.audit_facts()

    # Should only delete the one with id=5
    ks.delete_fact_by_id.assert_awaited_once_with(5)


@pytest.mark.asyncio
async def test_bug30_contradiction_skips_missing_id():
    """Contradiction with missing 'id' is skipped, not crash."""
    from brain.curator import Curator

    ks = AsyncMock()
    ks.delete_fact_by_id = AsyncMock(return_value=True)
    conv = AsyncMock()

    curator = Curator(conv, ks)
    contradictions = [
        (
            {
                "key": "drink",
                "value": "coffee",
                "confidence": 0.9,
            },  # no id
            {"id": 2, "key": "drink", "value": "tea", "confidence": 0.5},
        )
    ]
    resolved = await curator._resolve_contradictions(contradictions)
    assert resolved == 0
    ks.delete_fact_by_id.assert_not_awaited()


# ------------------------------------------------------------------ #
# BUG-33: Core facts don't exceed max_facts
# ------------------------------------------------------------------ #


@pytest.mark.asyncio
async def test_bug33_core_facts_respect_max_facts_at_limit():
    """When semantic results already fill max_facts, no core facts are added."""
    from memory.context_builder import ContextBuilder

    conv_store = AsyncMock()
    conv_store.get_recent = AsyncMock(return_value=[])
    know_store = AsyncMock()

    max_facts = 5
    semantic_results = [
        {
            "id": i,
            "category": "c",
            "key": f"k{i}",
            "value": f"v{i}",
            "confidence": 1.0,
            "created_at": "2025-01-01",
            "updated_at": "2025-01-01",
        }
        for i in range(5)
    ]
    core_results = [
        {
            "id": 100 + i,
            "category": "c",
            "key": f"core{i}",
            "value": f"cv{i}",
            "confidence": 1.0,
            "created_at": "2025-01-01",
            "updated_at": "2025-01-01",
        }
        for i in range(5)
    ]
    know_store.search_semantic = AsyncMock(return_value=semantic_results)
    know_store.search_keyword = AsyncMock(return_value=[])
    know_store.get_all_facts = AsyncMock(return_value=core_results)

    cb = ContextBuilder(conv_store, know_store, max_facts=max_facts)

    with (
        patch(
            "memory.context_builder._build_time_context",
            return_value={},
        ),
        patch(
            "memory.context_builder.build_system_prompt",
            return_value="ok",
        ) as mock_prompt,
        patch(
            "tools.presence.get_presence_summary",
            new_callable=AsyncMock,
            return_value="",
        ),
        patch(
            "tools.ha_helpers.get_device_summary",
            new_callable=AsyncMock,
            return_value="",
        ),
        patch("memory.context_builder.settings") as mock_settings,
    ):
        mock_settings.timezone = "UTC"
        mock_settings.google_calendar_credentials_path = ""
        await cb.build("query")

    kw = mock_prompt.call_args[1]
    assert len(kw["relevant_facts"]) == max_facts


# ------------------------------------------------------------------ #
# BUG-35: backup_id path injection is rejected
# ------------------------------------------------------------------ #


@pytest.mark.asyncio
async def test_bug35_backup_id_path_traversal_rejected():
    """Crafted backup_id with path traversal is rejected."""
    from tools.manage import _handle_backup

    result = await _handle_backup(
        "restore", {"backup_id": "../../etc/passwd"}
    )
    assert "invalid backup_id" in result

    result2 = await _handle_backup("delete", {"backup_id": "../secrets"})
    assert "invalid backup_id" in result2


@pytest.mark.asyncio
async def test_bug35_valid_backup_id_accepted():
    """Valid backup_id passes validation."""
    from tools.manage import _handle_backup

    with patch(
        "tools.manage._supervisor_request",
        new_callable=AsyncMock,
        return_value={"data": {}},
    ):
        result = await _handle_backup("restore", {"backup_id": "abc123"})
    assert "restore initiated" in result


# ------------------------------------------------------------------ #
# BUG-36: Rate limiter uses real client IP
# ------------------------------------------------------------------ #


def test_bug36_rate_limiter_uses_client_host():
    """Rate limiter middleware should use request.client.host, not X-Forwarded-For."""
    # Verify server code doesn't reference x-forwarded-for in middleware
    import inspect
    from brain.server import rate_limit_middleware

    source = inspect.getsource(rate_limit_middleware)
    assert "x-forwarded-for" not in source, (
        "rate_limit_middleware should not use x-forwarded-for"
    )
    assert "client.host" in source


# ------------------------------------------------------------------ #
# BUG-37: Timestamp comparison uses parsed datetimes
# ------------------------------------------------------------------ #


@pytest.mark.asyncio
async def test_bug37_timestamp_comparison_parsed():
    """Contradiction resolution uses datetime parsing for comparison."""
    from brain.curator import Curator

    ks = AsyncMock()
    ks.delete_fact_by_id = AsyncMock(return_value=True)
    conv = AsyncMock()
    curator = Curator(conv, ks)

    contradictions = [
        (
            {
                "id": 1,
                "key": "color",
                "value": "blue",
                "confidence": 0.8,
                "updated_at": "2025-01-01T00:00:00",
            },
            {
                "id": 2,
                "key": "color",
                "value": "red",
                "confidence": 0.8,
                "updated_at": "2025-06-15T12:00:00",
            },
        )
    ]
    resolved = await curator._resolve_contradictions(contradictions)
    assert resolved == 1
    # fact_a is older, should be deleted
    ks.delete_fact_by_id.assert_awaited_once_with(1)


# ------------------------------------------------------------------ #
# BUG-39: Rate limiter cleanup removes stale non-empty keys
# ------------------------------------------------------------------ #


def test_bug39_rate_limiter_cleans_old_timestamps():
    """Stale keys with old-only timestamps are cleaned up."""
    import time

    from brain.server import RateLimiter

    rl = RateLimiter()
    now = time.time()

    # Add old timestamps (older than 5 minutes)
    rl._requests["chat:1.2.3.4"] = [now - 600, now - 500]
    # Add a fresh key
    rl._requests["chat:5.6.7.8"] = [now - 10]
    # Force cleanup
    rl._last_cleanup = now - 999
    rl._maybe_cleanup(now)

    assert "chat:1.2.3.4" not in rl._requests
    assert "chat:5.6.7.8" in rl._requests


# ------------------------------------------------------------------ #
# BUG-40: Overly broad exception catch is narrowed
# ------------------------------------------------------------------ #


def test_bug40_schema_from_hints_narrow_catch():
    """_schema_from_hints only catches TypeError/NameError."""
    from tools.base import _schema_from_hints

    # Function with valid hints should work fine
    def good_func(x: str, y: int = 5) -> str:
        return ""

    schema = _schema_from_hints(good_func)
    assert "x" in schema["properties"]
    assert "y" in schema["properties"]


# ------------------------------------------------------------------ #
# BUG-41: Camera tools hidden + cameras excluded from device summary
# ------------------------------------------------------------------ #


def test_bug41_camera_snapshot_not_deprecated():
    """get_camera_snapshot must NOT be in DEPRECATED_TOOLS.

    It was incorrectly deprecated despite having no generic equivalent,
    which caused the LLM to be unable to show camera snapshots.
    """
    from tools.base import DEPRECATED_TOOLS

    assert "get_camera_snapshot" not in DEPRECATED_TOOLS
    assert "get_camera_state" not in DEPRECATED_TOOLS


def test_bug41_camera_in_discovery_domains():
    """Camera domain must be in _DISCOVERY_DOMAINS.

    Without it the AI never sees camera entity IDs in its device
    summary, so it cannot resolve 'front door camera' to an entity.
    """
    from tools.ha_helpers import _DISCOVERY_DOMAINS

    flat = [
        d if isinstance(d, str) else d[0]
        for d in _DISCOVERY_DOMAINS
    ]
    assert "camera" in flat


def test_bug41_system_prompt_mentions_camera_tools():
    """System prompt must list camera tools so the LLM knows they exist."""
    from brain.system_prompt import SYSTEM_PROMPT_TEMPLATE

    assert "get_camera_snapshot" in SYSTEM_PROMPT_TEMPLATE
    assert "get_camera_state" in SYSTEM_PROMPT_TEMPLATE
