"""Tests for memory.knowledge_store."""

import pytest
from memory.knowledge_store import (
    KnowledgeStore,
    _deserialize_embedding,
    _serialize_embedding,
)


def test_serialize_deserialize_embedding_roundtrip():
    """Embedding serialization round-trip preserves values (float32 precision)."""
    vec = [0.1, 0.2, -0.5, 1.0]
    blob = _serialize_embedding(vec)
    back = _deserialize_embedding(blob)
    assert len(back) == len(vec)
    for a, b in zip(back.tolist(), vec, strict=False):
        assert abs(a - b) < 1e-5


@pytest.mark.asyncio
async def test_knowledge_store_add_and_search_keyword(
    temp_db_path, mock_embed
):
    """Store a fact and retrieve it via keyword search."""
    store = KnowledgeStore(temp_db_path)
    store.set_embed_function(mock_embed)
    await store.initialize()

    await store.store_fact("preference", "coffee", "likes dark roast", 1.0)
    results = await store.search_keyword("coffee", limit=5)
    await store.close()

    assert len(results) == 1
    assert results[0]["key"] == "coffee"
    assert results[0]["value"] == "likes dark roast"
    assert results[0]["category"] == "preference"


@pytest.mark.asyncio
async def test_knowledge_store_search_semantic_returns_results(
    temp_db_path, mock_embed
):
    """With mock embed, semantic search returns stored facts."""
    store = KnowledgeStore(temp_db_path)
    store.set_embed_function(mock_embed)
    await store.initialize()

    await store.store_fact("fact", "test_key", "test value", 1.0)
    results = await store.search_semantic("test", limit=5)
    await store.close()

    assert len(results) >= 1
    assert any(r["key"] == "test_key" for r in results)
