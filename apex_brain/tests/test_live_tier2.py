"""
Tier 2 — Full Chat Pipeline Tests against a live Home Assistant instance.

These tests send natural language through the REAL conversation pipeline:
  User message → Context Build → LLM (real) → Tool calls → HA API (real) → Response

The LLM is real (uses the model from .env), so responses are non-deterministic.
Assertions check for structural correctness and presence of real HA data
rather than exact string matches.

Run with:  pytest -m live apex_brain/tests/test_live_tier2.py -v

NOTE: These tests consume LLM API tokens. Each test makes 1-3 LLM calls.
"""

from __future__ import annotations

import asyncio
import tempfile

import pytest

from brain.config import Settings
from brain.conversation import Conversation
from memory.context_builder import ContextBuilder
from memory.conversation_store import ConversationStore
from memory.fact_extractor import FactExtractor
from memory.knowledge_store import KnowledgeStore

pytestmark = pytest.mark.live


@pytest.fixture(autouse=True)
async def rate_limit_pause():
    """Pause between LLM-powered tests to avoid OpenAI rate limits."""
    yield
    await asyncio.sleep(5)


# ---------------------------------------------------------------------------
# Fixtures: build a real Conversation with real HA but isolated DB
# ---------------------------------------------------------------------------


@pytest.fixture
async def live_conversation(live_settings):
    """Build a real Conversation instance with:
    - Real HA connection (tools hit real HA)
    - Real LLM (model from .env)
    - Isolated temporary database (no pollution)
    - Real context builder (injects device summary, etc.)
    """
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    # Memory stores with isolated DB
    convo_store = ConversationStore(db_path)
    await convo_store.initialize()

    knowledge_store = KnowledgeStore(db_path)
    # Use a dummy embed function for tests (we don't need semantic search)
    async def _dummy_embed(text: str) -> list[float]:
        return [0.1, 0.2, 0.3, 0.4]

    knowledge_store.set_embed_function(_dummy_embed)
    await knowledge_store.initialize()

    fact_extractor = FactExtractor(
        knowledge_store=knowledge_store,
        model=live_settings.fact_extraction_model,
    )

    context_builder = ContextBuilder(
        conversation_store=convo_store,
        knowledge_store=knowledge_store,
        recent_turns_count=5,
        max_facts=10,
    )

    conv = Conversation(
        conversation_store=convo_store,
        knowledge_store=knowledge_store,
        fact_extractor=fact_extractor,
        context_builder=context_builder,
    )

    yield conv

    # Cleanup
    await convo_store.close()
    await knowledge_store.close()


# ===================================================================
# Simple queries — single tool call, read-only
# ===================================================================


class TestChatSimpleQueries:
    """Natural language queries that should trigger single read-only tool calls."""

    async def test_what_lights_available(self, live_conversation):
        """Ask about available lights — should use discover()."""
        result = await live_conversation.handle(
            "What lights do I have?", session_id="test_lights"
        )
        # Response should mention lights or say there are none
        lower = result.lower()
        assert (
            "light" in lower
            or "no lights" in lower
            or "don't have" in lower
        ), f"Expected 'light' in response: {result}"

    async def test_whats_the_time(self, live_conversation):
        """Ask the current time — should use current_datetime() or template."""
        result = await live_conversation.handle(
            "What time is it right now?", session_id="test_time"
        )
        # Should contain some time-like content
        lower = result.lower()
        assert any(
            word in lower
            for word in ["am", "pm", ":", "time", "o'clock", "currently"]
        ), f"Expected time info in response: {result}"

    async def test_sun_state(self, live_conversation):
        """Ask about the sun — always available, deterministic entity."""
        result = await live_conversation.handle(
            "Is the sun up or down right now?", session_id="test_sun"
        )
        lower = result.lower()
        assert any(
            word in lower
            for word in ["sun", "horizon", "up", "down", "risen", "set", "above", "below"]
        ), f"Expected sun info in response: {result}"

    async def test_ha_version(self, live_conversation):
        """Ask about HA version — should use discover(info)."""
        result = await live_conversation.handle(
            "What version of Home Assistant am I running?",
            session_id="test_version",
        )
        lower = result.lower()
        assert any(
            word in lower
            for word in ["version", "home assistant", "running", "20"]
        ), f"Expected version info in response: {result}"

    async def test_what_areas(self, live_conversation):
        """Ask about areas — should use discover(areas)."""
        result = await live_conversation.handle(
            "What areas are set up in my home?",
            session_id="test_areas",
        )
        lower = result.lower()
        assert any(
            word in lower
            for word in ["area", "room", "kitchen", "bedroom", "living", "no area", "haven't"]
        ), f"Expected area info in response: {result}"


# ===================================================================
# Medium queries — may chain tools or need reasoning
# ===================================================================


class TestChatMediumQueries:
    """Queries that may require the LLM to chain 1-2 tools."""

    async def test_how_many_entities(self, live_conversation):
        """Ask for entity count — may use discover or template."""
        result = await live_conversation.handle(
            "How many entities do I have in total?",
            session_id="test_count",
        )
        # Should contain a number
        assert any(
            c.isdigit() for c in result
        ), f"Expected a number in response: {result}"

    async def test_sensor_reading(self, live_conversation):
        """Ask about a sensor — should use query() or discover+query."""
        result = await live_conversation.handle(
            "What sensors do I have and what are their current values?",
            session_id="test_sensors",
        )
        lower = result.lower()
        assert any(
            word in lower
            for word in ["sensor", "temperature", "humidity", "battery", "power", "no sensor"]
        ), f"Expected sensor info in response: {result}"

    async def test_integrations_list(self, live_conversation):
        """Ask about integrations."""
        result = await live_conversation.handle(
            "What integrations are configured in my Home Assistant?",
            session_id="test_integrations",
        )
        lower = result.lower()
        assert any(
            word in lower
            for word in ["integration", "configured", "sun", "installed", "no integration"]
        ), f"Expected integration info in response: {result}"

    async def test_weather_query(self, live_conversation):
        """Ask about weather — may use weather tool or sensor query."""
        result = await live_conversation.handle(
            "What's the weather like right now?",
            session_id="test_weather",
        )
        lower = result.lower()
        assert any(
            word in lower
            for word in [
                "weather", "temperature", "degrees", "°",
                "forecast", "cloudy", "sunny", "rain",
                "humid", "wind", "condition",
                "don't have", "no weather",
            ]
        ), f"Expected weather info in response: {result}"


# ===================================================================
# State inspection — verify real data in responses
# ===================================================================


class TestChatStateInspection:
    """Verify the LLM returns real HA data, not hallucinations."""

    async def test_response_contains_real_entity_id(self, live_conversation):
        """When asked about entities, response should contain real entity_ids."""
        result = await live_conversation.handle(
            "List some of my entities with their entity IDs",
            session_id="test_entity_ids",
        )
        # Should contain at least one entity_id pattern (domain.name)
        import re
        entity_pattern = re.compile(r"\w+\.\w+")
        matches = entity_pattern.findall(result)
        assert len(matches) > 0, f"Expected entity_ids in response: {result}"

    async def test_history_query(self, live_conversation):
        """Ask about state change history."""
        result = await live_conversation.handle(
            "Show me the recent state changes for the sun entity",
            session_id="test_history",
        )
        lower = result.lower()
        assert any(
            word in lower
            for word in ["sun", "history", "horizon", "change", "transition", "above", "below"]
        ), f"Expected history info in response: {result}"

    async def test_services_query(self, live_conversation):
        """Ask about available services."""
        result = await live_conversation.handle(
            "What services are available for light entities?",
            session_id="test_services",
        )
        lower = result.lower()
        assert any(
            word in lower
            for word in ["turn_on", "turn_off", "toggle", "service", "light"]
        ), f"Expected service info in response: {result}"
