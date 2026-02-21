"""Tests for the Curator - self-curation logic."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from brain.curator import Curator


@pytest.fixture
def mock_conversation():
    conv = AsyncMock()
    conv.handle = AsyncMock(return_value="OK")
    return conv


@pytest.fixture
def mock_knowledge_store():
    ks = AsyncMock()
    ks.decay_confidence = AsyncMock(return_value=5)
    ks.cleanup_expired = AsyncMock(return_value=2)
    ks.get_low_confidence_facts = AsyncMock(return_value=[])
    ks.get_contradictory_facts = AsyncMock(return_value=[])
    ks.delete_fact_by_id = AsyncMock(return_value=True)
    return ks


@pytest.fixture
def curator(mock_conversation, mock_knowledge_store):
    return Curator(mock_conversation, mock_knowledge_store)


# ------------------------------------------------------------------ #
# Fact audit tests
# ------------------------------------------------------------------ #
class TestAuditFacts:
    @pytest.mark.asyncio
    async def test_audit_runs_decay_and_cleanup(self, curator, mock_knowledge_store):
        result = await curator.audit_facts()
        mock_knowledge_store.decay_confidence.assert_awaited_once()
        mock_knowledge_store.cleanup_expired.assert_awaited_once()
        assert "Decayed 5" in result
        assert "Removed 2" in result

    @pytest.mark.asyncio
    async def test_audit_prunes_low_confidence(self, curator, mock_knowledge_store):
        mock_knowledge_store.get_low_confidence_facts = AsyncMock(
            return_value=[
                {"id": 1, "key": "old_fact", "confidence": 0.2},
                {"id": 2, "key": "stale_fact", "confidence": 0.1},
            ]
        )
        result = await curator.audit_facts()
        assert mock_knowledge_store.delete_fact_by_id.await_count == 2
        assert "Pruned 2" in result

    @pytest.mark.asyncio
    async def test_audit_healthy_when_nothing_to_do(self, curator, mock_knowledge_store):
        mock_knowledge_store.decay_confidence = AsyncMock(return_value=0)
        mock_knowledge_store.cleanup_expired = AsyncMock(return_value=0)
        result = await curator.audit_facts()
        assert result == "Facts healthy"

    @pytest.mark.asyncio
    async def test_audit_handles_errors_gracefully(self, curator, mock_knowledge_store):
        mock_knowledge_store.decay_confidence = AsyncMock(side_effect=Exception("db error"))
        mock_knowledge_store.cleanup_expired = AsyncMock(return_value=0)
        result = await curator.audit_facts()
        # Should not crash, just skip the failed step
        assert isinstance(result, str)


# ------------------------------------------------------------------ #
# Contradiction resolution tests
# ------------------------------------------------------------------ #
class TestContradictionResolution:
    @pytest.mark.asyncio
    async def test_higher_confidence_wins(self, curator, mock_knowledge_store):
        contradictions = [
            (
                {"id": 1, "key": "drink", "value": "coffee", "confidence": 0.9, "updated_at": "2025-01-01"},
                {"id": 2, "key": "drink", "value": "tea", "confidence": 0.5, "updated_at": "2025-01-02"},
            )
        ]
        resolved = await curator._resolve_contradictions(contradictions)
        assert resolved == 1
        mock_knowledge_store.delete_fact_by_id.assert_awaited_once_with(2)

    @pytest.mark.asyncio
    async def test_recency_wins_on_tie(self, curator, mock_knowledge_store):
        contradictions = [
            (
                {"id": 1, "key": "drink", "value": "coffee", "confidence": 0.8, "updated_at": "2025-01-01"},
                {"id": 2, "key": "drink", "value": "tea", "confidence": 0.8, "updated_at": "2025-06-01"},
            )
        ]
        resolved = await curator._resolve_contradictions(contradictions)
        assert resolved == 1
        # fact_a updated_at < fact_b updated_at, so fact_a should be deleted
        mock_knowledge_store.delete_fact_by_id.assert_awaited_once_with(1)

    @pytest.mark.asyncio
    async def test_no_contradictions(self, curator, mock_knowledge_store):
        resolved = await curator._resolve_contradictions([])
        assert resolved == 0

    @pytest.mark.asyncio
    async def test_consolidate_facts_no_issues(self, curator, mock_knowledge_store):
        result = await curator.consolidate_facts()
        assert "No contradictions" in result


# ------------------------------------------------------------------ #
# AI-driven audit tests
# ------------------------------------------------------------------ #
class TestAIAudits:
    @pytest.mark.asyncio
    async def test_automation_audit_sends_message(self, curator, mock_conversation):
        await curator.audit_automations()
        mock_conversation.handle.assert_awaited_once()
        call_args = mock_conversation.handle.call_args
        assert "SYSTEM AUDIT" in call_args[0][0]
        assert call_args[1]["session_id"] == "apex_curator"

    @pytest.mark.asyncio
    async def test_entity_audit_sends_message(self, curator, mock_conversation):
        await curator.audit_entities()
        mock_conversation.handle.assert_awaited_once()
        call_args = mock_conversation.handle.call_args
        assert "health check" in call_args[0][0].lower()
        assert call_args[1]["session_id"] == "apex_curator"

    @pytest.mark.asyncio
    async def test_automation_audit_handles_error(self, curator, mock_conversation):
        mock_conversation.handle = AsyncMock(side_effect=Exception("LLM down"))
        # Should not raise
        await curator.audit_automations()

    @pytest.mark.asyncio
    async def test_entity_audit_handles_error(self, curator, mock_conversation):
        mock_conversation.handle = AsyncMock(side_effect=Exception("LLM down"))
        await curator.audit_entities()
