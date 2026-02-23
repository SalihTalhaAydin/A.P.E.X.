"""Tests for knowledge tool (remember, recall, forget)."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from tools.base import TOOL_REGISTRY
from tools.knowledge import remember, recall, forget, set_knowledge_store


@pytest.fixture(scope="module")
def _tools_loaded():
    from tools import discover_tools
    discover_tools()


@pytest.mark.usefixtures("_tools_loaded")
def test_remember_registered():
    """remember is in the registry with key and value params."""
    info = TOOL_REGISTRY.get("remember")
    assert info is not None
    req = info["parameters"]["required"]
    assert "key" in req
    assert "value" in req


@pytest.mark.usefixtures("_tools_loaded")
def test_recall_registered():
    """recall is in the registry with query param."""
    info = TOOL_REGISTRY.get("recall")
    assert info is not None
    req = info["parameters"]["required"]
    assert "query" in req


@pytest.mark.usefixtures("_tools_loaded")
def test_forget_registered():
    """forget is in the registry with key param."""
    info = TOOL_REGISTRY.get("forget")
    assert info is not None
    req = info["parameters"]["required"]
    assert "key" in req


@pytest.mark.asyncio
async def test_remember_without_store_returns_message():
    """remember returns init message when _knowledge_store is None."""
    set_knowledge_store(None)
    result = await remember("test_key", "test_value")
    assert "not initialized" in result.lower()


@pytest.mark.asyncio
async def test_remember_stores_fact():
    """remember calls store_fact with correct args when store is set."""
    mock_store = AsyncMock()
    set_knowledge_store(mock_store)

    result = await remember("wifi_password", "secret123")

    mock_store.store_fact.assert_called_once_with(
        category="explicit",
        key="wifi_password",
        value="secret123",
        confidence=1.0,
        source="explicit",
    )
    assert "Got it" in result or "remember" in result.lower()


@pytest.mark.asyncio
async def test_recall_without_store_returns_message():
    """recall returns init message when _knowledge_store is None."""
    set_knowledge_store(None)
    result = await recall("test query")
    assert "not initialized" in result.lower()


@pytest.mark.asyncio
async def test_recall_with_no_results():
    """recall returns empty message when search returns nothing."""
    mock_store = MagicMock()
    mock_store.search_semantic = AsyncMock(return_value=[])
    set_knowledge_store(mock_store)

    result = await recall("nonexistent")

    assert "don't have" in result.lower() or "nothing" in result.lower()


@pytest.mark.asyncio
async def test_recall_formats_results():
    """recall formats search results as bullet list."""
    mock_store = MagicMock()
    mock_store.search_semantic = AsyncMock(
        return_value=[
            {
                "category": "explicit",
                "key": "coffee",
                "value": "likes espresso",
            },
            {"category": "", "key": "dog", "value": "Max"},
        ]
    )
    set_knowledge_store(mock_store)

    result = await recall("coffee")

    assert "- coffee: likes espresso" in result
    assert "- dog: Max" in result


@pytest.mark.asyncio
async def test_forget_without_store_returns_message():
    """forget returns init message when _knowledge_store is None."""
    set_knowledge_store(None)
    result = await forget("some_key")
    assert "not initialized" in result.lower()


@pytest.mark.asyncio
async def test_forget_when_deleted_explicit():
    """forget returns success when delete_fact finds explicit fact."""
    mock_store = MagicMock()
    mock_store.delete_fact = AsyncMock(side_effect=[True, False])
    set_knowledge_store(mock_store)

    result = await forget("old_key")

    assert "Done" in result or "Forgot" in result
    mock_store.delete_fact.assert_any_call("old_key", category="explicit")


@pytest.mark.asyncio
async def test_forget_when_not_found():
    """forget returns not-found when delete_fact returns False both times."""
    mock_store = MagicMock()
    mock_store.delete_fact = AsyncMock(return_value=False)
    set_knowledge_store(mock_store)

    result = await forget("unknown_key")

    assert "don't have" in result.lower() or "nothing" in result.lower()


@pytest.mark.asyncio
async def test_recall_includes_category_label_when_present():
    """recall formats results with category in brackets when category is non-empty."""
    mock_store = MagicMock()
    mock_store.search_semantic = AsyncMock(
        return_value=[
            {"category": "explicit", "key": "wifi", "value": "secret123"},
            {"category": "inferred", "key": "preference", "value": "dark mode"},
        ]
    )
    set_knowledge_store(mock_store)

    result = await recall("wifi")

    assert "[explicit]" in result
    assert "[inferred]" in result
    assert "wifi: secret123" in result
    assert "preference: dark mode" in result


@pytest.mark.asyncio
async def test_remember_and_recall_roundtrip():
    """remember stores and recall retrieves with same key/value semantics."""
    mock_store = MagicMock()
    mock_store.store_fact = AsyncMock()
    mock_store.search_semantic = AsyncMock(
        return_value=[
            {"category": "explicit", "key": "coffee_order", "value": "double espresso"},
        ]
    )
    set_knowledge_store(mock_store)

    await remember("coffee_order", "double espresso")
    result = await recall("coffee")

    mock_store.store_fact.assert_called_once_with(
        category="explicit",
        key="coffee_order",
        value="double espresso",
        confidence=1.0,
        source="explicit",
    )
    assert "coffee_order" in result or "espresso" in result


@pytest.mark.asyncio
async def test_recall_handles_result_with_missing_fields():
    """recall handles results with missing key or value gracefully."""
    mock_store = MagicMock()
    mock_store.search_semantic = AsyncMock(
        return_value=[
            {"category": "explicit", "key": "partial", "value": ""},
            {"category": "", "key": "?", "value": "fallback"},
        ]
    )
    set_knowledge_store(mock_store)

    result = await recall("anything")

    assert "partial" in result
    assert "fallback" in result or "?" in result
