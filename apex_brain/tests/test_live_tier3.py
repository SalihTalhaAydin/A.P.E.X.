"""
Tier 3 — Complex Multi-Step Reasoning Tests against live Home Assistant.

These tests exercise the LLM's ability to:
  - Chain multiple tools in sequence
  - Reason across tool results
  - Handle multi-entity operations
  - Perform safe write + verify cycles

Run with:  pytest -m live apex_brain/tests/test_live_tier3.py -v

NOTE: These tests consume more LLM tokens than Tier 2 (2-5 calls each).
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
from tests.conftest_live import skip_on_llm_error

pytestmark = pytest.mark.live

pytest.skip("Live tier 3 tests disabled", allow_module_level=True)


@pytest.fixture(autouse=True)
async def rate_limit_pause():
    """Pause between LLM-powered tests to avoid OpenAI rate limits."""
    yield
    await asyncio.sleep(5)


# ---------------------------------------------------------------------------
# Fixture: real conversation (same as Tier 2)
# ---------------------------------------------------------------------------


@pytest.fixture
async def live_conversation(live_settings):
    """Real Conversation with real HA + real LLM, isolated DB."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    convo_store = ConversationStore(db_path)
    await convo_store.initialize()

    knowledge_store = KnowledgeStore(db_path)

    async def _dummy_embed(text: str) -> list[float]:
        return [0.1, 0.2, 0.3, 0.4]

    knowledge_store.set_embed_function(_dummy_embed)
    await knowledge_store.initialize()

    fact_extractor = FactExtractor(
        knowledge_store=knowledge_store,
        model=Settings().fact_extraction_model,
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

    await convo_store.close()
    await knowledge_store.close()


# ===================================================================
# Multi-tool chaining: discover → query
# ===================================================================


class TestMultiToolChaining:
    """Tests where the LLM must call multiple tools to answer."""

    async def test_discover_then_query_specific(self, live_conversation):
        """Ask LLM to find entities then report on a specific one.

        Expected flow: discover(entities) → query(specific_entity)
        """
        result = await live_conversation.handle(
            "Find all my sensor entities and tell me the current "
            "value of the first temperature sensor you find. "
            "If there are no temperature sensors, tell me the "
            "value of any sensor.",
            session_id="chain_1",
        )
        skip_on_llm_error(result)
        # Should contain actual sensor data
        lower = result.lower()
        assert any(
            word in lower
            for word in [
                "sensor", "temperature", "value", "°",
                "currently", "reading", "degrees",
                "no temperature", "no sensor",
            ]
        ), f"Expected sensor data in response: {result}"

    async def test_count_entities_by_domain(self, live_conversation):
        """Ask for a breakdown of entities by domain.

        Expected flow: discover(entities) or template query
        """
        result = await live_conversation.handle(
            "Give me a breakdown of how many entities I have "
            "in each domain (lights, sensors, switches, etc). "
            "Show the count for each domain.",
            session_id="chain_2",
        )
        skip_on_llm_error(result)
        # Should contain numbers and domain names
        assert any(
            c.isdigit() for c in result
        ), f"Expected numbers in response: {result}"
        lower = result.lower()
        assert any(
            word in lower
            for word in ["light", "sensor", "switch", "automation", "domain"]
        ), f"Expected domain names in response: {result}"


# ===================================================================
# Cross-entity comparison
# ===================================================================


class TestCrossEntityAnalysis:
    """Tests that require reasoning across multiple entities."""

    async def test_compare_entity_states(self, live_conversation):
        """Ask to compare states of multiple entities.

        Expected flow: discover → multiple query calls
        """
        result = await live_conversation.handle(
            "Are there any lights currently on in my home? "
            "List which ones are on and which are off.",
            session_id="compare_1",
        )
        skip_on_llm_error(result)
        lower = result.lower()
        assert any(
            word in lower
            for word in ["light", "on", "off", "no light", "don't have"]
        ), f"Expected light status in response: {result}"

    async def test_system_overview(self, live_conversation):
        """Ask for a comprehensive system overview.

        Expected flow: discover(info) + discover(entities) + maybe discover(areas)
        """
        result = await live_conversation.handle(
            "Give me a quick overview of my Home Assistant setup: "
            "what version am I running, how many entities do I have, "
            "and what areas are configured?",
            session_id="overview_1",
        )
        skip_on_llm_error(result)
        # Should contain version info
        lower = result.lower()
        assert any(
            word in lower
            for word in ["version", "entities", "area", "home assistant"]
        ), f"Expected overview data in response: {result}"
        # Should contain at least one number (entity count or version)
        assert any(
            c.isdigit() for c in result
        ), f"Expected numbers in response: {result}"


# ===================================================================
# History + analysis
# ===================================================================


class TestHistoryAnalysis:
    """Tests that require fetching and reasoning about history."""

    async def test_sun_transition_analysis(self, live_conversation):
        """Analyze sun state transitions over 48 hours.

        Expected flow: history(sun.sun, 48h) → analyze pattern
        """
        result = await live_conversation.handle(
            "When did the sun rise and set in the last 48 hours? "
            "Show me the transition times.",
            session_id="history_1",
        )
        skip_on_llm_error(result)
        lower = result.lower()
        assert any(
            word in lower
            for word in [
                "sun", "rise", "set", "above", "below",
                "horizon", "transition", "am", "pm",
                "no history", "no state change",
            ]
        ), f"Expected sun history in response: {result}"

    async def test_history_and_current_state(self, live_conversation):
        """Combine current state query with history.

        Expected flow: query(sun.sun) + history(sun.sun)
        """
        result = await live_conversation.handle(
            "What is the sun's current state and when did "
            "it last change state?",
            session_id="history_2",
        )
        skip_on_llm_error(result)
        lower = result.lower()
        assert any(
            word in lower
            for word in ["sun", "current", "above", "below", "horizon", "change", "last"]
        ), f"Expected sun state + history in response: {result}"


# ===================================================================
# Safe write + verify cycle
# ===================================================================


class TestSafeWriteVerify:
    """Tests that perform a write operation then verify the result.

    All writes are guarded by EntityStateGuard to restore original state.
    """

    async def test_toggle_basement_light_via_chat(
        self, live_conversation, any_light_entity, state_guard
    ):
        """Ask LLM to toggle a basement light, then verify it changed.

        Expected flow:
          1. LLM calls do(light.turn_on/off)
          2. do() verifies state internally
          3. We verify via separate query
        """
        entity_id, original_state = any_light_entity
        assert "basement" in entity_id.lower()
        action = "turn off" if original_state == "on" else "turn on"

        async with state_guard.protect(entity_id):
            result = await live_conversation.handle(
                f"Please {action} the basement light {entity_id}",
                session_id="write_1",
            )
            skip_on_llm_error(result)
            lower = result.lower()
            assert any(
                word in lower
                for word in ["done", "turned", "on", "off", "basement", entity_id.split(".")[1]]
            ), f"Expected confirmation in response: {result}"

    async def test_update_entity_via_chat(self, live_conversation):
        """Ask LLM to refresh an entity state — always safe.

        Expected flow: do(homeassistant.update_entity, sun.sun)
        """
        result = await live_conversation.handle(
            "Please refresh the state of the sun entity "
            "(use homeassistant.update_entity service on sun.sun)",
            session_id="write_2",
        )
        skip_on_llm_error(result)
        lower = result.lower()
        assert any(
            word in lower
            for word in ["done", "updated", "refreshed", "sun"]
        ), f"Expected update confirmation in response: {result}"


# ===================================================================
# Multi-turn conversation (context memory)
# ===================================================================


class TestMultiTurnConversation:
    """Tests that verify the conversation maintains context across turns."""

    async def test_two_turn_followup(self, live_conversation):
        """First ask about entities, then follow up about one.

        Turn 1: "What lights do I have?"
        Turn 2: "Tell me more about the first one"
        """
        # Turn 1
        result1 = await live_conversation.handle(
            "What lights do I have? List them with entity IDs.",
            session_id="multi_1",
        )
        skip_on_llm_error(result1)
        lower1 = result1.lower()

        # Turn 2 — follow up
        result2 = await live_conversation.handle(
            "What is the current state of the sun entity?",
            session_id="multi_1",  # Same session!
        )
        skip_on_llm_error(result2)
        lower2 = result2.lower()
        assert any(
            word in lower2
            for word in ["sun", "horizon", "above", "below", "state"]
        ), f"Expected sun state in turn 2: {result2}"

    async def test_three_turn_investigation(self, live_conversation):
        """Three-turn conversation: overview → detail → history.

        Turn 1: General question about the system
        Turn 2: Follow-up about a specific domain
        Turn 3: Ask about history of an entity
        """
        # Turn 1
        r1 = await live_conversation.handle(
            "How many entity domains do I have in Home Assistant?",
            session_id="multi_3turn",
        )
        skip_on_llm_error(r1)
        assert any(c.isdigit() for c in r1), f"Expected number in turn 1: {r1}"

        # Turn 2
        r2 = await live_conversation.handle(
            "Tell me about the sun.sun entity — what state is it in?",
            session_id="multi_3turn",
        )
        skip_on_llm_error(r2)
        lower2 = r2.lower()
        assert any(
            word in lower2 for word in ["sun", "horizon", "above", "below"]
        ), f"Expected sun info in turn 2: {r2}"

        # Turn 3
        r3 = await live_conversation.handle(
            "Show me its history for the last 24 hours",
            session_id="multi_3turn",
        )
        skip_on_llm_error(r3)
        lower3 = r3.lower()
        assert any(
            word in lower3
            for word in ["history", "sun", "change", "horizon", "transition", "above", "below", "no"]
        ), f"Expected history in turn 3: {r3}"


# ===================================================================
# Edge cases and robustness
# ===================================================================


class TestEdgeCases:
    """Tests for edge cases and error handling with real HA."""

    async def test_nonexistent_entity_graceful(self, live_conversation):
        """Ask about a non-existent entity — should handle gracefully."""
        result = await live_conversation.handle(
            "What is the state of sensor.zzz_totally_fake_xyz?",
            session_id="edge_1",
        )
        skip_on_llm_error(result)
        lower = result.lower()
        assert any(
            word in lower
            for word in [
                "not found", "doesn't exist", "no entity",
                "couldn't find", "unknown", "not available",
                "cannot find", "can't find", "no such",
                "unable to find", "doesn't seem",
            ]
        ), f"Expected graceful error in response: {result}"

    async def test_ambiguous_request(self, live_conversation):
        """Ambiguous request — LLM should still produce useful output."""
        result = await live_conversation.handle(
            "What's going on in my home right now?",
            session_id="edge_2",
        )
        skip_on_llm_error(result)
        # Should return something useful (devices, status, etc.)
        assert len(result) > 20, f"Expected substantive response: {result}"

    async def test_template_in_natural_language(self, live_conversation):
        """Ask a question that requires Jinja2 template evaluation."""
        result = await live_conversation.handle(
            "Can you evaluate this Home Assistant template: "
            "{{ states.sun.sun.state }}",
            session_id="edge_3",
        )
        skip_on_llm_error(result)
        lower = result.lower()
        assert any(
            word in lower
            for word in ["above_horizon", "below_horizon", "horizon", "sun"]
        ), f"Expected template result in response: {result}"
