"""Tests for memory.context_builder.ContextBuilder."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers: sample data factories
# ---------------------------------------------------------------------------

def _make_fact(id_: int, key: str = "k", value: str = "v", confidence: float = 1.0):
    """Return a minimal fact dict matching KnowledgeStore output."""
    return {
        "id": id_,
        "category": "general",
        "key": key,
        "value": value,
        "confidence": confidence,
        "created_at": "2025-01-01T00:00:00",
        "updated_at": "2025-01-01T00:00:00",
    }


def _make_turn(role: str, content: str):
    """Return a minimal conversation turn dict."""
    return {"role": role, "content": content, "timestamp": "2025-01-01T00:00:00"}


FAKE_TIME_CONTEXT = {
    "period": "morning",
    "season": "winter",
    "hour": 9,
    "formatted": "Monday, January 01, 2025 at 09:00 AM",
}

FAKE_SYSTEM_PROMPT = "<<assembled-system-prompt>>"


# ---------------------------------------------------------------------------
# Fixture: builds a ContextBuilder with fully-mocked dependencies
# ---------------------------------------------------------------------------

@pytest.fixture
def builder():
    """Return a ContextBuilder with mocked stores (default max_facts=20)."""
    from memory.context_builder import ContextBuilder

    conv_store = AsyncMock()
    conv_store.get_recent = AsyncMock(return_value=[])

    know_store = AsyncMock()
    know_store.search_semantic = AsyncMock(return_value=[])
    know_store.search_keyword = AsyncMock(return_value=[])
    know_store.get_all_facts = AsyncMock(return_value=[])

    cb = ContextBuilder(
        conversation_store=conv_store,
        knowledge_store=know_store,
        recent_turns_count=10,
        max_facts=20,
    )
    return cb


# ---------------------------------------------------------------------------
# Shared patcher helper — patches everything external to ContextBuilder.build
# ---------------------------------------------------------------------------

def _common_patches():
    """Return a dict of patch context managers used by most tests.

    Callers can override individual mocks after entering the patches.
    """
    return {
        "time_ctx": patch(
            "memory.context_builder._build_time_context",
            return_value=FAKE_TIME_CONTEXT,
        ),
        "sys_prompt": patch(
            "memory.context_builder.build_system_prompt",
            return_value=FAKE_SYSTEM_PROMPT,
        ),
        "presence": patch(
            "tools.presence.get_presence_summary",
            new_callable=AsyncMock,
            return_value="Everyone home",
        ),
        "device": patch(
            "tools.ha_helpers.get_device_summary",
            new_callable=AsyncMock,
            return_value="light.kitchen, switch.garage",
        ),
        "calendar": patch(
            "tools.calendar_tool.get_today_schedule",
            new_callable=AsyncMock,
            return_value="10am: Meeting",
        ),
        "settings": patch(
            "memory.context_builder.settings",
        ),
    }


# ---------------------------------------------------------------------------
# Basic build tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_build_calls_conversation_store_get_recent(builder):
    """get_recent is called with the configured recent_turns_count."""
    with (
        patch("memory.context_builder._build_time_context", return_value=FAKE_TIME_CONTEXT),
        patch("memory.context_builder.build_system_prompt", return_value=FAKE_SYSTEM_PROMPT),
        patch("tools.presence.get_presence_summary", new_callable=AsyncMock, return_value=""),
        patch("tools.ha_helpers.get_device_summary", new_callable=AsyncMock, return_value=""),
        patch("memory.context_builder.settings") as mock_settings,
    ):
        mock_settings.timezone = "UTC"
        mock_settings.google_calendar_credentials_path = ""

        await builder.build("hello")

    builder.conversation_store.get_recent.assert_awaited_once_with(
        n=10, session_id="default"
    )


@pytest.mark.asyncio
async def test_build_with_user_message_does_semantic_search(builder):
    """When user_message is non-empty, search_semantic is called."""
    with (
        patch("memory.context_builder._build_time_context", return_value=FAKE_TIME_CONTEXT),
        patch("memory.context_builder.build_system_prompt", return_value=FAKE_SYSTEM_PROMPT),
        patch("tools.presence.get_presence_summary", new_callable=AsyncMock, return_value=""),
        patch("tools.ha_helpers.get_device_summary", new_callable=AsyncMock, return_value=""),
        patch("memory.context_builder.settings") as mock_settings,
    ):
        mock_settings.timezone = "UTC"
        mock_settings.google_calendar_credentials_path = ""
        builder.knowledge_store.search_semantic.return_value = [_make_fact(1)]

        await builder.build("turn on lights")

    builder.knowledge_store.search_semantic.assert_awaited_once_with(
        query="turn on lights", limit=20
    )


@pytest.mark.asyncio
async def test_build_with_empty_message_skips_semantic_search(builder):
    """When user_message is empty string, no search is performed."""
    with (
        patch("memory.context_builder._build_time_context", return_value=FAKE_TIME_CONTEXT),
        patch("memory.context_builder.build_system_prompt", return_value=FAKE_SYSTEM_PROMPT),
        patch("tools.presence.get_presence_summary", new_callable=AsyncMock, return_value=""),
        patch("tools.ha_helpers.get_device_summary", new_callable=AsyncMock, return_value=""),
        patch("memory.context_builder.settings") as mock_settings,
    ):
        mock_settings.timezone = "UTC"
        mock_settings.google_calendar_credentials_path = ""

        await builder.build("")

    builder.knowledge_store.search_semantic.assert_not_awaited()
    builder.knowledge_store.search_keyword.assert_not_awaited()


@pytest.mark.asyncio
async def test_build_no_explicit_keyword_fallback(builder):
    """When semantic search returns empty, context_builder does NOT call search_keyword.
    search_semantic falls back to search_keyword internally when embeddings unavailable."""
    with (
        patch("memory.context_builder._build_time_context", return_value=FAKE_TIME_CONTEXT),
        patch("memory.context_builder.build_system_prompt", return_value=FAKE_SYSTEM_PROMPT),
        patch("tools.presence.get_presence_summary", new_callable=AsyncMock, return_value=""),
        patch("tools.ha_helpers.get_device_summary", new_callable=AsyncMock, return_value=""),
        patch("memory.context_builder.settings") as mock_settings,
    ):
        mock_settings.timezone = "UTC"
        mock_settings.google_calendar_credentials_path = ""
        builder.knowledge_store.search_semantic.return_value = []  # empty

        await builder.build("some query")

    builder.knowledge_store.search_semantic.assert_awaited_once_with(
        query="some query", limit=20
    )
    builder.knowledge_store.search_keyword.assert_not_awaited()


@pytest.mark.asyncio
async def test_build_no_keyword_fallback_when_semantic_has_results(builder):
    """When semantic search returns results, keyword search is NOT called."""
    with (
        patch("memory.context_builder._build_time_context", return_value=FAKE_TIME_CONTEXT),
        patch("memory.context_builder.build_system_prompt", return_value=FAKE_SYSTEM_PROMPT),
        patch("tools.presence.get_presence_summary", new_callable=AsyncMock, return_value=""),
        patch("tools.ha_helpers.get_device_summary", new_callable=AsyncMock, return_value=""),
        patch("memory.context_builder.settings") as mock_settings,
    ):
        mock_settings.timezone = "UTC"
        mock_settings.google_calendar_credentials_path = ""
        builder.knowledge_store.search_semantic.return_value = [_make_fact(1)]

        await builder.build("some query")

    builder.knowledge_store.search_keyword.assert_not_awaited()


# ---------------------------------------------------------------------------
# Core facts tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_build_adds_high_confidence_core_facts(builder):
    """Core facts with confidence >= 0.9 are appended to relevant_facts."""
    high_conf_fact = _make_fact(100, key="fav_color", value="blue", confidence=0.95)

    with (
        patch("memory.context_builder._build_time_context", return_value=FAKE_TIME_CONTEXT),
        patch("memory.context_builder.build_system_prompt", return_value=FAKE_SYSTEM_PROMPT) as mock_prompt,
        patch("tools.presence.get_presence_summary", new_callable=AsyncMock, return_value=""),
        patch("tools.ha_helpers.get_device_summary", new_callable=AsyncMock, return_value=""),
        patch("memory.context_builder.settings") as mock_settings,
    ):
        mock_settings.timezone = "UTC"
        mock_settings.google_calendar_credentials_path = ""
        builder.knowledge_store.search_semantic.return_value = []
        builder.knowledge_store.get_all_facts.return_value = [high_conf_fact]

        await builder.build("")

    # The high-confidence fact should appear in relevant_facts passed to build_system_prompt
    call_kwargs = mock_prompt.call_args[1]
    assert high_conf_fact in call_kwargs["relevant_facts"]


@pytest.mark.asyncio
async def test_build_skips_low_confidence_core_facts(builder):
    """Core facts with confidence < 0.9 are NOT added."""
    low_conf_fact = _make_fact(200, key="maybe", value="unsure", confidence=0.5)

    with (
        patch("memory.context_builder._build_time_context", return_value=FAKE_TIME_CONTEXT),
        patch("memory.context_builder.build_system_prompt", return_value=FAKE_SYSTEM_PROMPT) as mock_prompt,
        patch("tools.presence.get_presence_summary", new_callable=AsyncMock, return_value=""),
        patch("tools.ha_helpers.get_device_summary", new_callable=AsyncMock, return_value=""),
        patch("memory.context_builder.settings") as mock_settings,
    ):
        mock_settings.timezone = "UTC"
        mock_settings.google_calendar_credentials_path = ""
        builder.knowledge_store.search_semantic.return_value = []
        builder.knowledge_store.get_all_facts.return_value = [low_conf_fact]

        await builder.build("")

    call_kwargs = mock_prompt.call_args[1]
    assert low_conf_fact not in call_kwargs["relevant_facts"]


@pytest.mark.asyncio
async def test_build_deduplicates_semantic_and_core_facts(builder):
    """A core fact whose id already exists in semantic results is not duplicated."""
    shared_fact = _make_fact(42, key="dup", value="val", confidence=1.0)

    with (
        patch("memory.context_builder._build_time_context", return_value=FAKE_TIME_CONTEXT),
        patch("memory.context_builder.build_system_prompt", return_value=FAKE_SYSTEM_PROMPT) as mock_prompt,
        patch("tools.presence.get_presence_summary", new_callable=AsyncMock, return_value=""),
        patch("tools.ha_helpers.get_device_summary", new_callable=AsyncMock, return_value=""),
        patch("memory.context_builder.settings") as mock_settings,
    ):
        mock_settings.timezone = "UTC"
        mock_settings.google_calendar_credentials_path = ""
        # Semantic search already returns this fact
        builder.knowledge_store.search_semantic.return_value = [shared_fact]
        # Core facts returns the same id
        builder.knowledge_store.get_all_facts.return_value = [shared_fact]

        await builder.build("query")

    call_kwargs = mock_prompt.call_args[1]
    ids = [f["id"] for f in call_kwargs["relevant_facts"]]
    assert ids.count(42) == 1  # appears exactly once


@pytest.mark.asyncio
async def test_build_respects_max_facts_limit(builder):
    """Once relevant_facts reaches max_facts, no more core facts are added."""
    from memory.context_builder import ContextBuilder

    conv_store = AsyncMock()
    conv_store.get_recent = AsyncMock(return_value=[])

    know_store = AsyncMock()
    know_store.search_semantic = AsyncMock(return_value=[])
    know_store.search_keyword = AsyncMock(return_value=[])

    max_facts = 3
    cb = ContextBuilder(
        conversation_store=conv_store,
        knowledge_store=know_store,
        recent_turns_count=10,
        max_facts=max_facts,
    )

    # Core facts: 5 high-confidence facts, but max_facts is 3
    core = [_make_fact(i, key=f"k{i}", confidence=1.0) for i in range(5)]
    know_store.get_all_facts = AsyncMock(return_value=core)

    with (
        patch("memory.context_builder._build_time_context", return_value=FAKE_TIME_CONTEXT),
        patch("memory.context_builder.build_system_prompt", return_value=FAKE_SYSTEM_PROMPT) as mock_prompt,
        patch("tools.presence.get_presence_summary", new_callable=AsyncMock, return_value=""),
        patch("tools.ha_helpers.get_device_summary", new_callable=AsyncMock, return_value=""),
        patch("memory.context_builder.settings") as mock_settings,
    ):
        mock_settings.timezone = "UTC"
        mock_settings.google_calendar_credentials_path = ""

        await cb.build("")  # empty message, no semantic search

    call_kwargs = mock_prompt.call_args[1]
    assert len(call_kwargs["relevant_facts"]) <= max_facts


# ---------------------------------------------------------------------------
# Context integration tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_build_includes_presence_summary(builder):
    """Presence summary is fetched and forwarded to build_system_prompt."""
    with (
        patch("memory.context_builder._build_time_context", return_value=FAKE_TIME_CONTEXT),
        patch("memory.context_builder.build_system_prompt", return_value=FAKE_SYSTEM_PROMPT) as mock_prompt,
        patch("tools.presence.get_presence_summary", new_callable=AsyncMock, return_value="Alice: home") as mock_pres,
        patch("tools.ha_helpers.get_device_summary", new_callable=AsyncMock, return_value=""),
        patch("memory.context_builder.settings") as mock_settings,
    ):
        mock_settings.timezone = "UTC"
        mock_settings.google_calendar_credentials_path = ""

        await builder.build("hi")

    mock_pres.assert_awaited_once()
    call_kwargs = mock_prompt.call_args[1]
    assert call_kwargs["presence_summary"] == "Alice: home"


@pytest.mark.asyncio
async def test_build_handles_presence_failure(builder):
    """If presence fetch raises expected error (ConnectionError), empty string is used."""
    with (
        patch("memory.context_builder._build_time_context", return_value=FAKE_TIME_CONTEXT),
        patch("memory.context_builder.build_system_prompt", return_value=FAKE_SYSTEM_PROMPT) as mock_prompt,
        patch("tools.presence.get_presence_summary", new_callable=AsyncMock, side_effect=ConnectionError("offline")),
        patch("tools.ha_helpers.get_device_summary", new_callable=AsyncMock, return_value=""),
        patch("memory.context_builder.settings") as mock_settings,
    ):
        mock_settings.timezone = "UTC"
        mock_settings.google_calendar_credentials_path = ""

        await builder.build("hi")  # should NOT raise

    call_kwargs = mock_prompt.call_args[1]
    assert call_kwargs["presence_summary"] == ""


@pytest.mark.asyncio
async def test_build_includes_device_summary(builder):
    """Device summary is fetched and forwarded to build_system_prompt."""
    with (
        patch("memory.context_builder._build_time_context", return_value=FAKE_TIME_CONTEXT),
        patch("memory.context_builder.build_system_prompt", return_value=FAKE_SYSTEM_PROMPT) as mock_prompt,
        patch("tools.presence.get_presence_summary", new_callable=AsyncMock, return_value=""),
        patch("tools.ha_helpers.get_device_summary", new_callable=AsyncMock, return_value="light.living_room") as mock_dev,
        patch("memory.context_builder.settings") as mock_settings,
    ):
        mock_settings.timezone = "UTC"
        mock_settings.google_calendar_credentials_path = ""

        await builder.build("hi")

    mock_dev.assert_awaited_once()
    call_kwargs = mock_prompt.call_args[1]
    assert call_kwargs["device_summary"] == "light.living_room"


@pytest.mark.asyncio
async def test_build_handles_device_failure(builder):
    """If device summary fetch raises, empty string is used."""
    with (
        patch("memory.context_builder._build_time_context", return_value=FAKE_TIME_CONTEXT),
        patch("memory.context_builder.build_system_prompt", return_value=FAKE_SYSTEM_PROMPT) as mock_prompt,
        patch("tools.presence.get_presence_summary", new_callable=AsyncMock, return_value=""),
        patch("tools.ha_helpers.get_device_summary", new_callable=AsyncMock, side_effect=ConnectionError("offline")),
        patch("memory.context_builder.settings") as mock_settings,
    ):
        mock_settings.timezone = "UTC"
        mock_settings.google_calendar_credentials_path = ""

        await builder.build("hi")  # should NOT raise

    call_kwargs = mock_prompt.call_args[1]
    assert call_kwargs["device_summary"] == ""


@pytest.mark.asyncio
async def test_build_includes_calendar_when_credentials_set(builder):
    """Calendar is fetched when google_calendar_credentials_path is set."""
    with (
        patch("memory.context_builder._build_time_context", return_value=FAKE_TIME_CONTEXT),
        patch("memory.context_builder.build_system_prompt", return_value=FAKE_SYSTEM_PROMPT) as mock_prompt,
        patch("tools.presence.get_presence_summary", new_callable=AsyncMock, return_value=""),
        patch("tools.ha_helpers.get_device_summary", new_callable=AsyncMock, return_value=""),
        patch("tools.calendar_tool.get_today_schedule", new_callable=AsyncMock, return_value="3pm: Dentist") as mock_cal,
        patch("memory.context_builder.settings") as mock_settings,
    ):
        mock_settings.timezone = "UTC"
        mock_settings.google_calendar_credentials_path = "/path/to/creds.json"

        await builder.build("hi")

    mock_cal.assert_awaited_once()
    call_kwargs = mock_prompt.call_args[1]
    assert call_kwargs["calendar_summary"] == "3pm: Dentist"


@pytest.mark.asyncio
async def test_build_skips_calendar_without_credentials(builder):
    """Calendar fetch is skipped when credentials path is empty."""
    with (
        patch("memory.context_builder._build_time_context", return_value=FAKE_TIME_CONTEXT),
        patch("memory.context_builder.build_system_prompt", return_value=FAKE_SYSTEM_PROMPT) as mock_prompt,
        patch("tools.presence.get_presence_summary", new_callable=AsyncMock, return_value=""),
        patch("tools.ha_helpers.get_device_summary", new_callable=AsyncMock, return_value=""),
        patch("tools.calendar_tool.get_today_schedule", new_callable=AsyncMock, return_value="should not appear") as mock_cal,
        patch("memory.context_builder.settings") as mock_settings,
    ):
        mock_settings.timezone = "UTC"
        mock_settings.google_calendar_credentials_path = ""

        await builder.build("hi")

    mock_cal.assert_not_awaited()
    call_kwargs = mock_prompt.call_args[1]
    assert call_kwargs["calendar_summary"] == ""


# ---------------------------------------------------------------------------
# Output tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_build_passes_all_context_to_system_prompt(builder):
    """All assembled pieces are forwarded to build_system_prompt with correct keys."""
    semantic_fact = _make_fact(1, key="name", value="Salih")
    recent = [_make_turn("user", "hello"), _make_turn("assistant", "hi")]

    with (
        patch("memory.context_builder._build_time_context", return_value=FAKE_TIME_CONTEXT),
        patch("memory.context_builder.build_system_prompt", return_value=FAKE_SYSTEM_PROMPT) as mock_prompt,
        patch("tools.presence.get_presence_summary", new_callable=AsyncMock, return_value="Salih: home"),
        patch("tools.ha_helpers.get_device_summary", new_callable=AsyncMock, return_value="light.office"),
        patch("tools.calendar_tool.get_today_schedule", new_callable=AsyncMock, return_value="9am: standup"),
        patch("memory.context_builder.settings") as mock_settings,
    ):
        mock_settings.timezone = "UTC"
        mock_settings.google_calendar_credentials_path = "/creds.json"

        builder.knowledge_store.search_semantic.return_value = [semantic_fact]
        builder.knowledge_store.get_all_facts.return_value = []
        builder.conversation_store.get_recent.return_value = recent

        await builder.build("good morning")

    mock_prompt.assert_called_once()
    kw = mock_prompt.call_args[1]

    assert kw["calendar_summary"] == "9am: standup"
    assert kw["presence_summary"] == "Salih: home"
    assert kw["time_context"] == FAKE_TIME_CONTEXT
    assert kw["device_summary"] == "light.office"
    assert kw["recent_turns"] == recent
    # relevant_facts should contain the semantic fact
    assert any(f["id"] == 1 for f in kw["relevant_facts"])


@pytest.mark.asyncio
async def test_build_returns_string(builder):
    """The return value of build() is a string (the assembled system prompt)."""
    with (
        patch("memory.context_builder._build_time_context", return_value=FAKE_TIME_CONTEXT),
        patch("memory.context_builder.build_system_prompt", return_value=FAKE_SYSTEM_PROMPT),
        patch("tools.presence.get_presence_summary", new_callable=AsyncMock, return_value=""),
        patch("tools.ha_helpers.get_device_summary", new_callable=AsyncMock, return_value=""),
        patch("memory.context_builder.settings") as mock_settings,
    ):
        mock_settings.timezone = "UTC"
        mock_settings.google_calendar_credentials_path = ""

        result = await builder.build("test")

    assert isinstance(result, str)
    assert result == FAKE_SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# Timezone fallback tests (Bug #26 regression)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_build_valid_timezone_is_used(builder):
    """A valid timezone string (e.g. 'America/New_York') is applied."""
    import datetime
    from zoneinfo import ZoneInfo

    with (
        patch(
            "memory.context_builder._build_time_context",
            return_value=FAKE_TIME_CONTEXT,
        ) as mock_tc,
        patch(
            "memory.context_builder.build_system_prompt",
            return_value=FAKE_SYSTEM_PROMPT,
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
        mock_settings.timezone = "America/New_York"
        mock_settings.google_calendar_credentials_path = ""

        await builder.build("hi")

    # The datetime passed to _build_time_context should use the
    # requested timezone, NOT UTC.
    now_arg = mock_tc.call_args[0][0]
    assert now_arg.tzinfo is not None
    assert str(now_arg.tzinfo) == "America/New_York"


@pytest.mark.asyncio
async def test_build_invalid_timezone_falls_back_to_utc(builder):
    """An invalid timezone name (KeyError) triggers a UTC fallback."""
    import datetime

    with (
        patch(
            "memory.context_builder._build_time_context",
            return_value=FAKE_TIME_CONTEXT,
        ) as mock_tc,
        patch(
            "memory.context_builder.build_system_prompt",
            return_value=FAKE_SYSTEM_PROMPT,
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
        mock_settings.timezone = "Not/A_Real_Timezone"
        mock_settings.google_calendar_credentials_path = ""

        await builder.build("hi")  # should NOT raise

    now_arg = mock_tc.call_args[0][0]
    assert now_arg.tzinfo == datetime.timezone.utc


@pytest.mark.asyncio
async def test_build_malformed_timezone_falls_back_to_utc(builder):
    """A malformed timezone string (ValueError from ZoneInfo) triggers UTC fallback."""
    import datetime
    from zoneinfo import ZoneInfo

    with (
        patch(
            "memory.context_builder.ZoneInfo",
            side_effect=ValueError("bad tz"),
        ),
        patch(
            "memory.context_builder._build_time_context",
            return_value=FAKE_TIME_CONTEXT,
        ) as mock_tc,
        patch(
            "memory.context_builder.build_system_prompt",
            return_value=FAKE_SYSTEM_PROMPT,
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
        mock_settings.timezone = "\x00bad"
        mock_settings.google_calendar_credentials_path = ""

        await builder.build("hi")  # should NOT raise

    now_arg = mock_tc.call_args[0][0]
    assert now_arg.tzinfo == datetime.timezone.utc


@pytest.mark.asyncio
async def test_build_does_not_catch_import_error(builder):
    """ImportError from ZoneInfo must NOT be silenced -- it should propagate."""
    with (
        patch(
            "memory.context_builder.ZoneInfo",
            side_effect=ImportError("no zoneinfo"),
        ),
        patch(
            "memory.context_builder._build_time_context",
            return_value=FAKE_TIME_CONTEXT,
        ),
        patch(
            "memory.context_builder.build_system_prompt",
            return_value=FAKE_SYSTEM_PROMPT,
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

        with pytest.raises(ImportError):
            await builder.build("hi")


@pytest.mark.asyncio
async def test_build_does_not_catch_runtime_error(builder):
    """RuntimeError from ZoneInfo must NOT be silenced -- it should propagate."""
    with (
        patch(
            "memory.context_builder.ZoneInfo",
            side_effect=RuntimeError("broken"),
        ),
        patch(
            "memory.context_builder._build_time_context",
            return_value=FAKE_TIME_CONTEXT,
        ),
        patch(
            "memory.context_builder.build_system_prompt",
            return_value=FAKE_SYSTEM_PROMPT,
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

        with pytest.raises(RuntimeError):
            await builder.build("hi")
