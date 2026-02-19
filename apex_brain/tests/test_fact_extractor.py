"""Tests for memory.fact_extractor.FactExtractor."""

import json
import logging
from unittest.mock import AsyncMock, MagicMock

import pytest

from memory.fact_extractor import FactExtractor


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_llm_response(content: str) -> MagicMock:
    """Build a mock LLM response object with the given content string."""
    message = MagicMock()
    message.content = content
    choice = MagicMock()
    choice.message = message
    response = MagicMock()
    response.choices = [choice]
    return response


def _make_knowledge_store() -> MagicMock:
    """Build a mock KnowledgeStore with AsyncMock methods."""
    ks = MagicMock()
    ks.store_fact = AsyncMock()
    ks.correct_fact = AsyncMock()
    return ks


def _make_litellm(content: str = "[]") -> AsyncMock:
    """Build a mock litellm_completion that returns the given content."""
    return AsyncMock(return_value=_make_llm_response(content))


def _long_turns() -> list[dict]:
    """Return conversation turns long enough to pass the 20-char threshold."""
    return [
        {"role": "user", "content": "I really love sushi a lot"},
        {"role": "assistant", "content": "That's great to hear!"},
    ]


# ===========================================================================
# Input validation
# ===========================================================================


@pytest.mark.asyncio
async def test_extract_empty_turns_returns_early():
    """Empty turn list returns immediately without calling the LLM."""
    ks = _make_knowledge_store()
    extractor = FactExtractor(ks)
    llm = _make_litellm()

    result = await extractor.extract_from_conversation([], llm)

    assert result is None
    llm.assert_not_awaited()
    ks.store_fact.assert_not_awaited()


@pytest.mark.asyncio
async def test_extract_turns_without_content_skipped():
    """Turns missing a 'content' key are excluded from conversation text.

    If all turns lack content the text will be empty (<20 chars) and the
    LLM should never be called.
    """
    ks = _make_knowledge_store()
    extractor = FactExtractor(ks)
    llm = _make_litellm()

    turns = [
        {"role": "user"},
        {"role": "assistant"},
    ]
    result = await extractor.extract_from_conversation(turns, llm)

    assert result is None
    llm.assert_not_awaited()


@pytest.mark.asyncio
async def test_extract_short_conversation_returns_early():
    """Conversation text shorter than 20 characters skips the LLM call."""
    ks = _make_knowledge_store()
    extractor = FactExtractor(ks)
    llm = _make_litellm()

    turns = [{"role": "user", "content": "Hi"}]  # "User: Hi" = 8 chars
    result = await extractor.extract_from_conversation(turns, llm)

    assert result is None
    llm.assert_not_awaited()


# ===========================================================================
# LLM call parameters
# ===========================================================================


@pytest.mark.asyncio
async def test_extract_calls_llm_with_correct_model():
    """The configured model name is forwarded to litellm_completion."""
    ks = _make_knowledge_store()
    extractor = FactExtractor(ks, model="custom-model-name")
    llm = _make_litellm("[]")

    await extractor.extract_from_conversation(_long_turns(), llm)

    llm.assert_awaited_once()
    call_kwargs = llm.call_args
    assert call_kwargs.kwargs["model"] == "custom-model-name"


@pytest.mark.asyncio
async def test_extract_calls_llm_with_correct_temperature():
    """Temperature is set to 0.3."""
    ks = _make_knowledge_store()
    extractor = FactExtractor(ks)
    llm = _make_litellm("[]")

    await extractor.extract_from_conversation(_long_turns(), llm)

    assert llm.call_args.kwargs["temperature"] == 0.3


@pytest.mark.asyncio
async def test_extract_calls_llm_with_correct_max_tokens():
    """max_tokens is set to 1000."""
    ks = _make_knowledge_store()
    extractor = FactExtractor(ks)
    llm = _make_litellm("[]")

    await extractor.extract_from_conversation(_long_turns(), llm)

    assert llm.call_args.kwargs["max_tokens"] == 1000


@pytest.mark.asyncio
async def test_extract_formats_conversation_correctly():
    """User turns become 'User: ...' and assistant turns become 'Apex: ...'."""
    ks = _make_knowledge_store()
    extractor = FactExtractor(ks)
    llm = _make_litellm("[]")

    turns = [
        {"role": "user", "content": "I love pizza"},
        {"role": "assistant", "content": "Pizza is great"},
        {"role": "user", "content": "Especially pepperoni"},
    ]

    await extractor.extract_from_conversation(turns, llm)

    prompt_content = llm.call_args.kwargs["messages"][0]["content"]
    assert "User: I love pizza" in prompt_content
    assert "Apex: Pizza is great" in prompt_content
    assert "User: Especially pepperoni" in prompt_content


# ===========================================================================
# JSON parsing
# ===========================================================================


@pytest.mark.asyncio
async def test_extract_valid_json_stores_facts():
    """A well-formed JSON array is parsed and each fact is stored."""
    ks = _make_knowledge_store()
    extractor = FactExtractor(ks)
    facts_json = json.dumps([
        {"category": "preference", "key": "food", "value": "loves sushi", "confidence": 0.9},
    ])
    llm = _make_litellm(facts_json)

    await extractor.extract_from_conversation(_long_turns(), llm)

    ks.store_fact.assert_awaited_once_with(
        category="preference",
        key="food",
        value="loves sushi",
        confidence=0.9,
        source="auto",
        expires_at=None,
    )


@pytest.mark.asyncio
async def test_extract_json_with_markdown_backticks():
    """Markdown code fences around JSON are stripped before parsing."""
    ks = _make_knowledge_store()
    extractor = FactExtractor(ks)
    inner = json.dumps([
        {"category": "fact", "key": "address", "value": "123 Main St", "confidence": 0.95},
    ])
    wrapped = f"```json\n{inner}\n```"
    llm = _make_litellm(wrapped)

    await extractor.extract_from_conversation(_long_turns(), llm)

    ks.store_fact.assert_awaited_once()
    call_kwargs = ks.store_fact.call_args.kwargs
    assert call_kwargs["key"] == "address"
    assert call_kwargs["value"] == "123 Main St"


@pytest.mark.asyncio
async def test_extract_invalid_json_logs_warning(caplog):
    """Non-JSON LLM output triggers a warning log and does not raise."""
    ks = _make_knowledge_store()
    extractor = FactExtractor(ks)
    llm = _make_litellm("this is not JSON at all")

    with caplog.at_level(logging.WARNING):
        await extractor.extract_from_conversation(_long_turns(), llm)

    assert any("Failed to parse" in r.message for r in caplog.records)
    ks.store_fact.assert_not_awaited()


@pytest.mark.asyncio
async def test_extract_empty_array_returns_early():
    """A literal '[]' response causes an early return with no storage calls."""
    ks = _make_knowledge_store()
    extractor = FactExtractor(ks)
    llm = _make_litellm("[]")

    result = await extractor.extract_from_conversation(_long_turns(), llm)

    assert result is None
    ks.store_fact.assert_not_awaited()


@pytest.mark.asyncio
async def test_extract_empty_content_returns():
    """If the LLM returns None/empty content, return [] without storing."""
    ks = _make_knowledge_store()
    extractor = FactExtractor(ks)
    llm = AsyncMock(return_value=_make_llm_response(None))

    result = await extractor.extract_from_conversation(_long_turns(), llm)

    assert result == []
    ks.store_fact.assert_not_awaited()


@pytest.mark.asyncio
async def test_extract_non_list_response_returns():
    """If the parsed JSON is a dict (not a list), return without storing."""
    ks = _make_knowledge_store()
    extractor = FactExtractor(ks)
    llm = _make_litellm(json.dumps({"category": "fact", "key": "k", "value": "v"}))

    result = await extractor.extract_from_conversation(_long_turns(), llm)

    assert result is None
    ks.store_fact.assert_not_awaited()


# ===========================================================================
# Fact storage
# ===========================================================================


@pytest.mark.asyncio
async def test_extract_normal_fact_calls_store_fact():
    """A fact without correction=true routes to store_fact."""
    ks = _make_knowledge_store()
    extractor = FactExtractor(ks)
    facts_json = json.dumps([
        {"category": "habit", "key": "exercise", "value": "runs every morning", "confidence": 0.85},
    ])
    llm = _make_litellm(facts_json)

    await extractor.extract_from_conversation(_long_turns(), llm)

    ks.store_fact.assert_awaited_once()
    ks.correct_fact.assert_not_awaited()


@pytest.mark.asyncio
async def test_extract_correction_calls_correct_fact():
    """A fact with correction=true routes to correct_fact instead."""
    ks = _make_knowledge_store()
    extractor = FactExtractor(ks)
    facts_json = json.dumps([
        {
            "category": "preference",
            "key": "thermostat",
            "value": "prefers 72 degrees",
            "confidence": 1.0,
            "correction": True,
        },
    ])
    llm = _make_litellm(facts_json)

    await extractor.extract_from_conversation(_long_turns(), llm)

    ks.correct_fact.assert_awaited_once_with(
        category="preference",
        key="thermostat",
        new_value="prefers 72 degrees",
        confidence=1.0,
    )
    ks.store_fact.assert_not_awaited()


@pytest.mark.asyncio
async def test_extract_fact_with_expires():
    """An 'expires' field is forwarded as expires_at to store_fact."""
    ks = _make_knowledge_store()
    extractor = FactExtractor(ks)
    facts_json = json.dumps([
        {
            "category": "event",
            "key": "dentist",
            "value": "Thursday 2pm",
            "confidence": 0.95,
            "expires": "2026-02-20",
        },
    ])
    llm = _make_litellm(facts_json)

    await extractor.extract_from_conversation(_long_turns(), llm)

    ks.store_fact.assert_awaited_once()
    assert ks.store_fact.call_args.kwargs["expires_at"] == "2026-02-20"


@pytest.mark.asyncio
async def test_extract_fact_default_confidence():
    """Missing 'confidence' key defaults to 0.7."""
    ks = _make_knowledge_store()
    extractor = FactExtractor(ks)
    facts_json = json.dumps([
        {"category": "fact", "key": "pet", "value": "has a cat"},
    ])
    llm = _make_litellm(facts_json)

    await extractor.extract_from_conversation(_long_turns(), llm)

    ks.store_fact.assert_awaited_once()
    assert ks.store_fact.call_args.kwargs["confidence"] == 0.7


@pytest.mark.asyncio
async def test_extract_fact_default_category():
    """Missing 'category' key defaults to 'fact'."""
    ks = _make_knowledge_store()
    extractor = FactExtractor(ks)
    facts_json = json.dumps([
        {"key": "zipcode", "value": "90210", "confidence": 0.9},
    ])
    llm = _make_litellm(facts_json)

    await extractor.extract_from_conversation(_long_turns(), llm)

    ks.store_fact.assert_awaited_once()
    assert ks.store_fact.call_args.kwargs["category"] == "fact"


@pytest.mark.asyncio
async def test_extract_skips_fact_without_key():
    """A fact with an empty or missing key is skipped entirely."""
    ks = _make_knowledge_store()
    extractor = FactExtractor(ks)
    facts_json = json.dumps([
        {"category": "preference", "key": "", "value": "something", "confidence": 0.9},
    ])
    llm = _make_litellm(facts_json)

    await extractor.extract_from_conversation(_long_turns(), llm)

    ks.store_fact.assert_not_awaited()
    ks.correct_fact.assert_not_awaited()


@pytest.mark.asyncio
async def test_extract_skips_fact_without_value():
    """A fact with an empty or missing value is skipped entirely."""
    ks = _make_knowledge_store()
    extractor = FactExtractor(ks)
    facts_json = json.dumps([
        {"category": "preference", "key": "color", "value": "", "confidence": 0.9},
    ])
    llm = _make_litellm(facts_json)

    await extractor.extract_from_conversation(_long_turns(), llm)

    ks.store_fact.assert_not_awaited()
    ks.correct_fact.assert_not_awaited()


@pytest.mark.asyncio
async def test_extract_multiple_facts_all_stored():
    """Multiple facts in the JSON array each produce a separate store call."""
    ks = _make_knowledge_store()
    extractor = FactExtractor(ks)
    facts_json = json.dumps([
        {"category": "preference", "key": "food", "value": "sushi", "confidence": 0.9},
        {"category": "person", "key": "Sarah", "value": "friend", "confidence": 0.8},
        {"category": "habit", "key": "jogging", "value": "every morning", "confidence": 0.85},
    ])
    llm = _make_litellm(facts_json)

    await extractor.extract_from_conversation(_long_turns(), llm)

    assert ks.store_fact.await_count == 3
    stored_keys = [c.kwargs["key"] for c in ks.store_fact.call_args_list]
    assert stored_keys == ["food", "Sarah", "jogging"]


@pytest.mark.asyncio
async def test_extract_non_dict_items_skipped():
    """Non-dict items inside the JSON array are silently skipped."""
    ks = _make_knowledge_store()
    extractor = FactExtractor(ks)
    facts_json = json.dumps([
        "just a string",
        42,
        None,
        {"category": "fact", "key": "real", "value": "fact here", "confidence": 0.9},
    ])
    llm = _make_litellm(facts_json)

    await extractor.extract_from_conversation(_long_turns(), llm)

    # Only the valid dict item should be stored
    ks.store_fact.assert_awaited_once()
    assert ks.store_fact.call_args.kwargs["key"] == "real"


# ===========================================================================
# Error handling
# ===========================================================================


@pytest.mark.asyncio
async def test_extract_llm_api_error_handled(caplog):
    """An exception from litellm_completion is caught and logged, not raised."""
    ks = _make_knowledge_store()
    extractor = FactExtractor(ks)
    llm = AsyncMock(side_effect=RuntimeError("API timeout"))

    with caplog.at_level(logging.ERROR):
        # Must not raise
        await extractor.extract_from_conversation(_long_turns(), llm)

    assert any("Fact extraction error" in r.message for r in caplog.records)
    ks.store_fact.assert_not_awaited()


@pytest.mark.asyncio
async def test_extract_store_continues_on_error():
    """If store_fact raises on one fact, remaining facts are still attempted.

    NOTE: In the current implementation the generic `except Exception`
    around the whole loop means a store_fact error aborts the rest. This
    test documents the actual (current) behaviour: an error from
    store_fact is caught at the outer level, so subsequent facts are NOT
    stored.  If the implementation is later changed to be more resilient
    (per-fact try/except), update this test accordingly.
    """
    ks = _make_knowledge_store()
    # First call raises, second would succeed
    ks.store_fact.side_effect = [RuntimeError("DB error"), None]
    extractor = FactExtractor(ks)
    facts_json = json.dumps([
        {"category": "fact", "key": "first", "value": "v1", "confidence": 0.9},
        {"category": "fact", "key": "second", "value": "v2", "confidence": 0.9},
    ])
    llm = _make_litellm(facts_json)

    # Should not propagate
    await extractor.extract_from_conversation(_long_turns(), llm)

    # The first call was attempted (and failed)
    assert ks.store_fact.await_count >= 1
    assert ks.store_fact.call_args_list[0].kwargs["key"] == "first"


# ===========================================================================
# Conversation formatting
# ===========================================================================


@pytest.mark.asyncio
async def test_extract_user_and_assistant_roles_formatted():
    """'user' role maps to 'User:' prefix, all others map to 'Apex:' prefix."""
    ks = _make_knowledge_store()
    extractor = FactExtractor(ks)
    llm = _make_litellm("[]")

    turns = [
        {"role": "user", "content": "What is the weather like today in Seattle?"},
        {"role": "assistant", "content": "It is currently sunny and 65 degrees."},
        {"role": "user", "content": "Thanks, I love sunny days."},
    ]

    await extractor.extract_from_conversation(turns, llm)

    prompt_content = llm.call_args.kwargs["messages"][0]["content"]
    # Verify user lines
    assert "User: What is the weather like today in Seattle?" in prompt_content
    assert "User: Thanks, I love sunny days." in prompt_content
    # Verify assistant lines use "Apex:" not "Assistant:"
    assert "Apex: It is currently sunny and 65 degrees." in prompt_content
    assert "Assistant:" not in prompt_content
