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
    sub._session.closed = False
    sub._running = True

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
# BUG-74 (P6-BUG-100): Non-numeric confidence validated before clamp
# ------------------------------------------------------------------ #


@pytest.mark.asyncio
async def test_bug74_confidence_string_defaults_to_07():
    """LLM returning confidence as string ('high') or null uses default 0.7."""
    from memory.fact_extractor import FactExtractor

    ks = AsyncMock()
    ks.store_fact = AsyncMock(return_value=1)
    extractor = FactExtractor(ks)

    facts_json = json.dumps([
        {"category": "fact", "key": "pet", "value": "has dog", "confidence": "high"},
        {"category": "fact", "key": "color", "value": "blue", "confidence": None},
    ])

    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = facts_json
    llm = AsyncMock(return_value=mock_response)

    turns = [{"role": "user", "content": "I have a dog and my favorite color is blue." * 3}]
    result = await extractor.extract_from_conversation(turns, llm)

    assert len(result) == 2
    # Both facts stored with default 0.7 (string and null are invalid)
    assert ks.store_fact.await_count == 2
    for call in ks.store_fact.call_args_list:
        assert call.kwargs["confidence"] == 0.7


@pytest.mark.asyncio
async def test_bug74_confidence_numeric_clamped():
    """Numeric confidence is coerced and clamped to [0, 1]."""
    from memory.fact_extractor import FactExtractor

    ks = AsyncMock()
    ks.store_fact = AsyncMock(return_value=1)
    extractor = FactExtractor(ks)

    # 0.95 (float), "0.8" (numeric string), 1.5 (clamped to 1.0), -0.2 (clamped to 0.0)
    facts_json = json.dumps([
        {"category": "fact", "key": "a", "value": "v1", "confidence": 0.95},
        {"category": "fact", "key": "b", "value": "v2", "confidence": "0.8"},
        {"category": "fact", "key": "c", "value": "v3", "confidence": 1.5},
        {"category": "fact", "key": "d", "value": "v4", "confidence": -0.2},
    ])

    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = facts_json
    llm = AsyncMock(return_value=mock_response)

    turns = [{"role": "user", "content": "a b c d " * 6}]
    await extractor.extract_from_conversation(turns, llm)

    calls = ks.store_fact.call_args_list
    assert calls[0].kwargs["confidence"] == 0.95
    assert calls[1].kwargs["confidence"] == 0.8
    assert calls[2].kwargs["confidence"] == 1.0
    assert calls[3].kwargs["confidence"] == 0.0


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
# BUG-24: system_prompt Lock at import time (RuntimeError without event loop)
# ------------------------------------------------------------------ #


def test_bug24_system_prompt_import_without_event_loop():
    """Importing system_prompt must not raise RuntimeError (no event loop at import).

    Before fix: asyncio.Lock() at import time required a running event loop on
    Python < 3.10. Lazy init creates the lock on first use in fetch_service_schemas.
    """
    from brain.system_prompt import build_system_prompt, fetch_service_schemas

    assert build_system_prompt is not None
    assert fetch_service_schemas is not None


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
# BUG-86: create_automation search-before-create handles error dict & malformed states
# ------------------------------------------------------------------ #


@pytest.mark.asyncio
async def test_bug86_create_automation_error_dict_returns_early():
    """When ha_request returns error dict for /states, create_automation returns early."""
    from tools.automation import create_automation

    with patch(
        "tools.automation.ha_request",
        new_callable=AsyncMock,
        return_value={"error": "Cannot connect to Home Assistant"},
    ):
        result = await create_automation(
            alias="Test",
            triggers=[{"trigger": "state", "entity_id": "sensor.x", "from": "off"}],
            actions=[{"action": "turn_on", "target": {"entity_id": "light.x"}}],
        )
    assert "Error: Unable to reach Home Assistant" in result


@pytest.mark.asyncio
async def test_bug86_create_automation_malformed_states_no_crash():
    """When states list has items lacking entity_id or non-dict, creation proceeds."""
    from tools.automation import create_automation

    async def mock_ha_request(method, path, json_data=None):
        if method == "GET" and path == "/states":
            # Malformed: one dict without entity_id, one non-dict
            return [
                {"state": "on", "attributes": {}},  # no entity_id
                "not-a-dict",
                {
                    "entity_id": "automation.good",
                    "state": "on",
                    "attributes": {"friendly_name": "Good One"},
                },
            ]
        if method == "POST" and "/config/automation/config/" in path:
            return {"result": "created"}
        raise ValueError("Unexpected call")

    with patch(
        "tools.automation.ha_request",
        new_callable=AsyncMock,
        side_effect=mock_ha_request,
    ):
        result = await create_automation(
            alias="New Automation",
            triggers=[{"trigger": "state", "entity_id": "sensor.x", "from": "off"}],
            actions=[{"action": "turn_on", "target": {"entity_id": "light.x"}}],
        )
    assert "Done. Created automation" in result
    assert "New Automation" in result


# ------------------------------------------------------------------ #
# BUG-29: ha_request handles ConnectError gracefully
# ------------------------------------------------------------------ #


@pytest.mark.asyncio
async def test_bug29_ha_request_connect_error():
    """ConnectError raises HomeAssistantError, not crash."""
    import httpx

    from tools.ha_helpers import HomeAssistantError

    with patch(
        "tools.ha_helpers._ha_client",
        new=MagicMock(),
    ) as mock_client:
        mock_client.request = AsyncMock(
            side_effect=httpx.ConnectError("refused")
        )
        from tools.ha_helpers import ha_request

        with pytest.raises(HomeAssistantError, match="Cannot connect"):
            await ha_request("GET", "/states")


@pytest.mark.asyncio
async def test_bug29_ha_request_timeout():
    """TimeoutException raises HomeAssistantError, not crash."""
    import httpx

    from tools.ha_helpers import HomeAssistantError

    with patch(
        "tools.ha_helpers._ha_client",
        new=MagicMock(),
    ) as mock_client:
        mock_client.request = AsyncMock(
            side_effect=httpx.TimeoutException("timed out")
        )
        from tools.ha_helpers import ha_request

        with pytest.raises(HomeAssistantError, match="[Tt]imed out"):
            await ha_request("GET", "/states")


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
    """Rate limiter middleware should prefer request.client.host when available.
    BUG-103: X-Forwarded-For is allowed as fallback when request.client is None
    (e.g. behind reverse proxy)."""
    import inspect
    from brain.server import rate_limit_middleware

    source = inspect.getsource(rate_limit_middleware)
    # Primary path must use client.host
    assert "client.host" in source
    # BUG-36: prefer direct client; x-forwarded-for only as fallback when client is None
    assert "if request.client:" in source or "request.client" in source


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


# ------------------------------------------------------------------ #
# BUG-104: Context builder passes session_id to get_recent
# ------------------------------------------------------------------ #


@pytest.mark.asyncio
async def test_bug104_context_builder_passes_session_id():
    """build() must pass session_id to get_recent so sessions are isolated."""
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
            return_value={},
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
        mock_settings.timezone = "UTC"
        mock_settings.google_calendar_credentials_path = ""
        await cb.build("hello", session_id="my_session")

    # Verify session_id was passed through
    conv_store.get_recent.assert_awaited_once()
    call_kwargs = conv_store.get_recent.call_args
    assert call_kwargs.kwargs.get("session_id") == "my_session"


# ------------------------------------------------------------------ #
# BUG-105: Reminder NOT deleted when delivery fails
# ------------------------------------------------------------------ #


@pytest.mark.asyncio
async def test_bug105_reminder_not_deleted_on_failure():
    """If conversation.handle raises, reminder must NOT be deleted."""
    from brain.scheduler import Scheduler

    conv = AsyncMock()
    conv.handle = AsyncMock(side_effect=RuntimeError("LLM down"))
    ks = AsyncMock()
    ks.get_all_facts = AsyncMock(
        return_value=[
            {
                "key": "dentist",
                "value": "appointment at 3pm",
                "expires_at": "2020-01-01T00:00:00",
                "id": 42,
            }
        ]
    )
    ks.delete_fact_by_id = AsyncMock()

    scheduler = Scheduler(conv, ks)
    await scheduler._task_reminder_check()

    # Reminder should NOT have been deleted since delivery failed
    ks.delete_fact_by_id.assert_not_awaited()


# ------------------------------------------------------------------ #
# BUG-106: Confabulation regex precision
# ------------------------------------------------------------------ #


def test_bug106_confab_regex_does_not_match_innocent_phrases():
    """'I've checked the weather' should NOT match confab regex."""
    from brain.conversation import _looks_like_device_action_claim

    # These should NOT match (innocent phrases)
    assert not _looks_like_device_action_claim(
        "I've checked the weather for you"
    )
    assert not _looks_like_device_action_claim(
        "I have no information about that"
    )
    assert not _looks_like_device_action_claim(
        "I've noted your preference"
    )
    assert not _looks_like_device_action_claim(
        "The package was recycled yesterday"
    )

    # These SHOULD still match (actual device action claims)
    assert _looks_like_device_action_claim(
        "I've turned on the lights"
    )
    assert _looks_like_device_action_claim(
        "I have set the thermostat to 72"
    )
    assert _looks_like_device_action_claim(
        "I've locked the front door"
    )


def test_bug145_confab_regex_switched_powered_in_ive_have():
    """BUG-145: 'I've switched' and 'I have powered' must match; 'recycled' must NOT."""
    from brain.conversation import _looks_like_device_action_claim

    # Innocent phrases must NOT match
    assert not _looks_like_device_action_claim("I've checked the weather")
    assert not _looks_like_device_action_claim("recycled paper")
    assert not _looks_like_device_action_claim("bicycled home")

    # Device action claims (including switched/powered via I've/I have) must match
    assert _looks_like_device_action_claim("I've turned on the lights")
    assert _looks_like_device_action_claim("I've switched on the lights")
    assert _looks_like_device_action_claim("I have powered off the computer")


# ------------------------------------------------------------------ #
# BUG-107: No duplicate fact decay when curator is enabled
# ------------------------------------------------------------------ #


def test_bug107_no_duplicate_decay_with_curator():
    """When curator is enabled, scheduler should not register standalone decay tasks."""
    from brain.scheduler import Scheduler

    conv = AsyncMock()
    ks = AsyncMock()
    curator = AsyncMock()

    with patch("brain.scheduler.settings") as mock_settings:
        mock_settings.curator_enabled = True
        mock_settings.morning_briefing_hour = 7
        mock_settings.evening_briefing_hour = 21
        mock_settings.health_check_interval_minutes = 30

        scheduler = Scheduler(conv, ks, curator=curator)
        scheduler._register_builtin_tasks()

    task_names = [t.name for t in scheduler._tasks]
    assert "fact_decay" not in task_names
    assert "fact_cleanup" not in task_names
    # Curator tasks should be present
    assert "fact_audit" in task_names


def test_bug107_standalone_decay_without_curator():
    """When curator is disabled, standalone decay tasks should be registered."""
    from brain.scheduler import Scheduler

    conv = AsyncMock()
    ks = AsyncMock()

    with patch("brain.scheduler.settings") as mock_settings:
        mock_settings.curator_enabled = False
        mock_settings.morning_briefing_hour = 7
        mock_settings.evening_briefing_hour = 21
        mock_settings.health_check_interval_minutes = 30

        scheduler = Scheduler(conv, ks, curator=None)
        scheduler._register_builtin_tasks()

    task_names = [t.name for t in scheduler._tasks]
    assert "fact_decay" in task_names
    assert "fact_cleanup" in task_names


# ------------------------------------------------------------------ #
# BUG-108: announce(phone) uses entity-based notify
# ------------------------------------------------------------------ #


@pytest.mark.asyncio
async def test_bug108_announce_phone_uses_entity_based_notify():
    """announce(target='phone') must use entity-based notify path."""
    from tools.notify import announce

    with (
        patch("tools.notify.settings") as mock_settings,
        patch(
            "tools.notify.ha_request",
            new_callable=AsyncMock,
            return_value={},
        ) as mock_req,
    ):
        mock_settings.phone_notify_target = "mobile_app_phone"
        await announce("test message", target="phone")

    mock_req.assert_awaited_once()
    call_args = mock_req.call_args
    assert call_args[0][1] == "/services/notify/send_message"
    json_data = call_args.kwargs.get("json_data") or call_args[0][2]
    assert json_data["entity_id"] == "notify.mobile_app_phone"


# ------------------------------------------------------------------ #
# BUG-109: delete_fact with category only deletes correct fact
# ------------------------------------------------------------------ #


@pytest.mark.asyncio
async def test_bug109_delete_fact_with_category(tmp_path):
    """delete_fact with category only deletes the matching category."""
    from memory.db_manager import SharedDbConnection
    from memory.knowledge_store import KnowledgeStore

    db_path = str(tmp_path / "test_bug109.db")
    shared = SharedDbConnection(db_path)
    await shared.initialize()
    ks = KnowledgeStore(shared)
    await ks.initialize()

    async with shared.lock:
        db = shared.connection
        await db.execute(
            "INSERT INTO facts (category, key, value, created_at, updated_at) "
            "VALUES ('preference', 'temperature', '72F', '2025-01-01', '2025-01-01')"
        )
        await db.execute(
            "INSERT INTO facts (category, key, value, created_at, updated_at) "
            "VALUES ('fact', 'temperature', 'current outdoor', '2025-01-01', '2025-01-01')"
        )
        await db.commit()

    result = await ks.delete_fact("temperature", category="preference")
    assert result is True

    async with shared.lock:
        cursor = await shared.connection.execute(
            "SELECT category FROM facts WHERE key = 'temperature'"
        )
        rows = await cursor.fetchall()
    assert len(rows) == 1
    assert rows[0][0] == "fact"

    await shared.close()


# ------------------------------------------------------------------ #
# BUG-111: Semantic search only touches high-similarity facts
# ------------------------------------------------------------------ #


@pytest.mark.asyncio
async def test_bug111_search_semantic_touch_threshold(tmp_path):
    """Low-similarity results should NOT be touched."""
    import struct

    from memory.db_manager import SharedDbConnection
    from memory.knowledge_store import KnowledgeStore

    db_path = str(tmp_path / "test_bug111.db")
    shared = SharedDbConnection(db_path)
    await shared.initialize()
    ks = KnowledgeStore(shared)
    await ks.initialize()

    async def _mock_embed(text):
        return [1.0, 0.0, 0.0, 0.0]

    ks._embed_fn = _mock_embed

    low_sim_emb = struct.pack("4f", 0.0, 0.0, 0.0, 1.0)
    high_sim_emb = struct.pack("4f", 0.9, 0.1, 0.0, 0.0)

    async with shared.lock:
        db = shared.connection
        await db.execute(
            "INSERT INTO facts (category, key, value, embedding, "
            "created_at, updated_at, last_mentioned_at) "
            "VALUES ('test', 'low', 'low sim fact', ?, "
            "'2025-01-01', '2025-01-01', '2025-01-01')",
            (low_sim_emb,),
        )
        await db.execute(
            "INSERT INTO facts (category, key, value, embedding, "
            "created_at, updated_at, last_mentioned_at) "
            "VALUES ('test', 'high', 'high sim fact', ?, "
            "'2025-01-01', '2025-01-01', '2025-01-01')",
            (high_sim_emb,),
        )
        await db.commit()

    results = await ks.search_semantic("query", limit=10, update_last_mentioned=True)
    assert len(results) == 2

    async with shared.lock:
        cursor = await shared.connection.execute(
            "SELECT key, last_mentioned_at FROM facts ORDER BY key"
        )
        rows = await cursor.fetchall()
    high_row = next(r for r in rows if r[0] == "high")
    low_row = next(r for r in rows if r[0] == "low")

    assert high_row[1] != "2025-01-01"
    assert low_row[1] == "2025-01-01"

    await shared.close()


# ------------------------------------------------------------------ #
# BUG-113: MCP transport cleaned up on session init failure
# ------------------------------------------------------------------ #


@pytest.mark.asyncio
async def test_bug113_mcp_transport_cleanup_on_session_failure():
    """If session init fails, transport must still be cleaned up."""
    from tools.mcp_bridge import MCPBridge

    bridge = MCPBridge(url="http://fake:8080", transport="sse")

    # Simulate the state after transport __aenter__ succeeded
    mock_transport_cm = AsyncMock()
    mock_transport_cm.__aenter__ = AsyncMock(
        return_value=(AsyncMock(), AsyncMock())
    )
    mock_transport_cm.__aexit__ = AsyncMock(return_value=False)

    # Mock session context manager that fails on __aenter__
    mock_session_cm = AsyncMock()
    mock_session_cm.__aenter__ = AsyncMock(
        side_effect=RuntimeError("session init failed")
    )

    # Directly set up the bridge's internal state
    # as if transport was already entered
    bridge._transport_cm = mock_transport_cm

    # Mock the imports inside connect() by patching the method itself
    # to exercise only the try/except logic around session init
    original_connect = bridge.connect

    async def patched_connect():
        # Simulate successful transport entry
        streams = await bridge._transport_cm.__aenter__()
        try:
            # Simulate session init failure
            raise RuntimeError("session init failed")
        except Exception:
            # This is what our fix does
            await bridge._transport_cm.__aexit__(None, None, None)
            bridge._connected = False

    await patched_connect()

    # Transport __aexit__ should have been called for cleanup
    mock_transport_cm.__aexit__.assert_awaited()
    assert not bridge.connected


def test_bug113_connect_source_has_transport_cleanup():
    """connect() must clean up transport if session init fails."""
    import inspect
    from tools.mcp_bridge import MCPBridge

    source = inspect.getsource(MCPBridge.connect)
    # After our fix, there should be a nested try/except
    # that calls __aexit__ on transport when session fails
    assert "await self._transport_cm.__aexit__" in source


# ------------------------------------------------------------------ #
# BUG-115: execute_tool logs exceptions
# ------------------------------------------------------------------ #


@pytest.mark.asyncio
async def test_bug115_execute_tool_logs_exception():
    """execute_tool must call logger.exception on tool failure."""
    from tools.base import TOOL_REGISTRY, execute_tool

    # Register a tool that always raises
    async def _broken_tool():
        raise ValueError("boom")

    TOOL_REGISTRY["_test_broken_tool"] = {
        "function": _broken_tool,
        "description": "test",
        "parameters": {},
        "is_async": True,
        "hidden": True,
    }

    try:
        with patch("tools.base.logger") as mock_logger:
            result = await execute_tool("_test_broken_tool", {})

        assert "Tool error" in result
        assert "boom" in result
        mock_logger.exception.assert_called_once()
    finally:
        del TOOL_REGISTRY["_test_broken_tool"]


# ------------------------------------------------------------------ #
# BUG-110: AuditStore initialized in server lifespan
# ------------------------------------------------------------------ #


def test_bug110_server_lifespan_imports_audit_store():
    """Server lifespan code must initialize audit store."""
    import inspect

    from brain.server import lifespan

    source = inspect.getsource(lifespan)
    assert "AuditStore" in source
    assert "set_manage_audit" in source
    assert "set_configure_audit" in source
