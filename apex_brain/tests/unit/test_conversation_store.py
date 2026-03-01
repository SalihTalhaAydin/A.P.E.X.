"""
Tests for the ConversationStore — conversation history management.
"""

from __future__ import annotations

import pytest
from memory.conversation_store import ConversationStore


@pytest.fixture
async def store(tmp_path):
    """Create a ConversationStore with a temp DB for testing."""
    db_path = str(tmp_path / "test_conversations.db")
    s = ConversationStore(db_path)
    await s.initialize()
    yield s
    await s.close()


@pytest.mark.asyncio
async def test_save_turn_truncates_content_to_10000_chars(store):
    """BUG-124: Content over 10,000 chars is truncated to prevent DB bloat."""
    huge = "x" * 15000
    await store.save_turn("user", huge, session_id="s1")

    recent = await store.get_recent(n=1, session_id="s1")
    assert len(recent) == 1
    assert len(recent[0]["content"]) == 10000
    assert recent[0]["content"] == "x" * 10000


@pytest.mark.asyncio
async def test_save_turn_preserves_content_under_limit(store):
    """Normal content under 10,000 chars is stored unchanged."""
    content = "Hello, this is a normal message."
    await store.save_turn("assistant", content)

    recent = await store.get_recent(n=1)
    assert len(recent) == 1
    assert recent[0]["content"] == content


@pytest.mark.asyncio
async def test_save_turn_early_return_for_empty_content(store):
    """Empty or whitespace-only content is not stored."""
    await store.save_turn("user", "")
    await store.save_turn("user", "   \n\t  ")

    recent = await store.get_recent(n=10)
    assert len(recent) == 0


# ── Bug 17 regression: uninitialized store raises RuntimeError ──


@pytest.mark.asyncio
async def test_conversation_store_uninitialized_raises_runtime_error(
    tmp_path,
):
    """Regression for Bug 17: methods raise RuntimeError when initialize() not called."""
    db_path = str(tmp_path / "test.db")
    store = ConversationStore(db_path)

    with pytest.raises(RuntimeError, match="Store not initialized"):
        await store.save_turn("user", "hello")

    with pytest.raises(RuntimeError, match="Store not initialized"):
        await store.get_recent(n=5)

    with pytest.raises(RuntimeError, match="Store not initialized"):
        await store.search("query")

    with pytest.raises(RuntimeError, match="Store not initialized"):
        await store.get_turns_since(since_hours=24)


@pytest.mark.asyncio
async def test_conversation_store_after_close_raises_runtime_error(store):
    """Regression for Bug 17: after close(), methods raise RuntimeError not AttributeError."""
    await store.close()

    with pytest.raises(RuntimeError, match="Store not initialized"):
        await store.save_turn("user", "hello")

    with pytest.raises(RuntimeError, match="Store not initialized"):
        await store.get_recent(n=5)


# ── Bug 12 (P3-GAP-1): _escape_like and search tests ──


def test_escape_like_escapes_percent():
    """_escape_like escapes % so LIKE doesn't treat it as wildcard."""
    escaped = ConversationStore._escape_like("50%")
    assert escaped == "50\\%"
    assert "%" not in escaped.replace("\\%", "")


def test_escape_like_escapes_underscore():
    """_escape_like escapes _ so LIKE doesn't treat it as single-char wildcard."""
    escaped = ConversationStore._escape_like("user_name")
    assert escaped == "user\\_name"
    assert "_" not in escaped.replace("\\_", "")


def test_escape_like_escapes_backslash():
    """_escape_like escapes \\ so it doesn't break ESCAPE '\\'."""
    escaped = ConversationStore._escape_like("path\\to\\file")
    assert escaped == "path\\\\to\\\\file"


def test_escape_like_combined_special_chars():
    """_escape_like handles all special chars together."""
    escaped = ConversationStore._escape_like("%_\\%")
    assert escaped == "\\%\\_\\\\\\%"


@pytest.mark.asyncio
async def test_search_escapes_user_input(store):
    """Search with %, _, \\ in query matches literally, not as SQL wildcards (Bug 12)."""
    await store.save_turn("user", "The temperature is 50% today")
    await store.save_turn("user", "user_name is alice")
    await store.save_turn("user", "path\\to\\file")

    # Query with % - should match "50%" literally, not arbitrary strings
    results = await store.search("50%", limit=10)
    assert len(results) == 1
    assert "50%" in results[0]["content"]

    # Query with _ - should match "user_name" literally
    results = await store.search("user_name", limit=10)
    assert len(results) == 1
    assert "user_name" in results[0]["content"]

    # Query with \\ - should match "path\to\file" literally
    results = await store.search("path\\to", limit=10)
    assert len(results) == 1
    assert (
        "path" in results[0]["content"] and "file" in results[0]["content"]
    )


@pytest.mark.asyncio
async def test_search_returns_matching_turns(store):
    """search() returns turns containing the query in chronological order."""
    await store.save_turn("user", "Hello world")
    await store.save_turn("assistant", "Hi there")
    await store.save_turn("user", "world peace")

    results = await store.search("world", limit=20)
    assert len(results) == 2
    assert results[0]["content"] == "world peace"  # newest first
    assert results[1]["content"] == "Hello world"


@pytest.mark.asyncio
async def test_get_turns_since_returns_recent(store):
    """get_turns_since returns turns within the time window."""
    await store.save_turn("user", "Turn 1")
    await store.save_turn("assistant", "Turn 2")

    results = await store.get_turns_since(since_hours=24, limit=100)
    assert len(results) >= 2
    contents = [r["content"] for r in results]
    assert "Turn 1" in contents
    assert "Turn 2" in contents
