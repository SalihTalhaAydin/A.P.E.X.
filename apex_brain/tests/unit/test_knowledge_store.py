"""Tests for memory.knowledge_store."""


from datetime import timezone

import numpy as np
import pytest
from memory.knowledge_store import (
    KnowledgeStore,
    _cosine_similarity,
    _deserialize_embedding,
    _serialize_embedding,
)


def test_cosine_similarity_normal_vectors():
    """_cosine_similarity returns 1.0 for identical vectors, 0 for orthogonal."""
    a = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    b = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    assert _cosine_similarity(a, b) == pytest.approx(1.0, abs=1e-6)

    orth_a = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    orth_b = np.array([0.0, 1.0, 0.0], dtype=np.float32)
    assert _cosine_similarity(orth_a, orth_b) == pytest.approx(
        0.0, abs=1e-6
    )


def test_cosine_similarity_zero_norm_returns_zero():
    """_cosine_similarity returns 0.0 when either vector has zero norm."""
    zero = np.array([0.0, 0.0, 0.0], dtype=np.float32)
    nonzero = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    assert _cosine_similarity(zero, nonzero) == 0.0
    assert _cosine_similarity(nonzero, zero) == 0.0
    assert _cosine_similarity(zero, zero) == 0.0


def test_serialize_deserialize_embedding_roundtrip():
    """Embedding serialization round-trip preserves values (float32 precision)."""
    vec = [0.1, 0.2, -0.5, 1.0]
    blob = _serialize_embedding(vec)
    back = _deserialize_embedding(blob)
    assert len(back) == len(vec)
    for a, b in zip(back.tolist(), vec):
        assert abs(a - b) < 1e-5


def test_deserialize_embedding_empty_blob():
    """Empty blob returns empty float32 array (BUG-80)."""
    result = _deserialize_embedding(b"")
    assert result.shape == (0,)
    assert result.dtype == np.float32


def test_deserialize_embedding_truncated_blob_raises():
    """Truncated blob (len not divisible by 4) raises ValueError (BUG-80)."""
    with pytest.raises(ValueError) as exc_info:
        _deserialize_embedding(b"\x00\x00\x00\x00\x00")  # 5 bytes
    assert "5" in str(exc_info.value)
    assert "not divisible by 4" in str(exc_info.value)


@pytest.mark.asyncio
async def test_set_embed_function_accepts_callable(
    temp_db_path, mock_embed
):
    """set_embed_function accepts a callable; semantic search uses it for embeddings."""
    store = KnowledgeStore(temp_db_path)
    store.set_embed_function(mock_embed)
    await store.initialize()

    await store.store_fact("pref", "key", "value", 1.0)
    results = await store.search_semantic("key", limit=5)
    assert len(results) >= 1
    assert "similarity" in results[0]
    await store.close()


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


@pytest.mark.asyncio
async def test_embed_text_pydantic_like_response_no_attribute_error(
    temp_db_path,
):
    """Regression for Bug 7: Pydantic/named-tuple items (no .get) must not raise AttributeError."""

    # Pydantic-like object: has .embedding attribute but no .get method
    class PydanticLikeItem:
        def __init__(self, embedding):
            self.embedding = embedding

    async def embed_fn(_text):
        return type(
            "EmbeddingResponse",
            (),
            {"data": [PydanticLikeItem([0.1, 0.2, 0.3, 0.4])]},
        )()

    store = KnowledgeStore(temp_db_path)
    store.set_embed_function(embed_fn)
    await store.initialize()

    result = await store._embed_text("test")
    await store.close()

    assert result is not None
    assert isinstance(result, np.ndarray)
    assert list(result) == [0.1, 0.2, 0.3, 0.4]


@pytest.mark.asyncio
async def test_embed_text_pydantic_like_no_embedding_attr_no_attribute_error(
    temp_db_path,
):
    """Regression for Bug 7: Object with no .get and no .embedding must not raise AttributeError."""

    # Object with no .embedding and no .get - the exact Bug 7 case
    class PydanticLikeItem:
        pass

    async def embed_fn(_text):
        return type(
            "EmbeddingResponse", (), {"data": [PydanticLikeItem()]}
        )()

    store = KnowledgeStore(temp_db_path)
    store.set_embed_function(embed_fn)
    await store.initialize()

    result = await store._embed_text("test")
    await store.close()

    # No embedding found, returns None (graceful degradation)
    assert result is None


@pytest.mark.asyncio
async def test_embed_text_dict_style_response_item(temp_db_path):
    """Regression for Bug 7: dict-style items use .get() correctly."""

    # Dict-style item: common in raw JSON / older LiteLLM responses
    async def embed_fn(_text):
        return type(
            "EmbeddingResponse",
            (),
            {"data": [{"embedding": [0.5, 0.6, 0.7, 0.8]}]},
        )()

    store = KnowledgeStore(temp_db_path)
    store.set_embed_function(embed_fn)
    await store.initialize()

    result = await store._embed_text("test")
    await store.close()

    assert result is not None
    assert isinstance(result, np.ndarray)
    assert list(result) == pytest.approx([0.5, 0.6, 0.7, 0.8], abs=1e-5)


@pytest.mark.asyncio
async def test_embed_text_dict_response_with_data_key(temp_db_path):
    """Regression for Bug 7: pure dict response (response['data']) works."""

    # Entire response is a dict, not an object
    async def embed_fn(_text):
        return {"data": [{"embedding": [0.9, 0.1, 0.2, 0.3]}]}

    store = KnowledgeStore(temp_db_path)
    store.set_embed_function(embed_fn)
    await store.initialize()

    result = await store._embed_text("test")
    await store.close()

    assert result is not None
    assert isinstance(result, np.ndarray)
    assert list(result) == pytest.approx([0.9, 0.1, 0.2, 0.3], abs=1e-5)


@pytest.mark.asyncio
async def test_embed_text_empty_data_non_numeric_response_returns_none(
    temp_db_path,
):
    """Regression for Bug 77 (P5-BUG-85): when data is empty and response is
    a dict/LiteLLM object (not a list of floats), return None instead of
    np.array() creating invalid object array and breaking cosine similarity.
    """

    async def embed_fn(_text):
        # LiteLLM-style response with empty/None data; response itself is dict
        return {"choices": [], "model": "embedding-model"}

    store = KnowledgeStore(temp_db_path)
    store.set_embed_function(embed_fn)
    await store.initialize()

    result = await store._embed_text("test")
    await store.close()

    assert result is None


@pytest.mark.asyncio
async def test_embed_text_empty_data_raw_list_works(temp_db_path):
    """When data is empty, raw list of floats (direct embed output) still works."""

    async def embed_fn(_text):
        return [0.5, 0.5, 0.5, 0.5]

    store = KnowledgeStore(temp_db_path)
    store.set_embed_function(embed_fn)
    await store.initialize()

    result = await store._embed_text("test")
    await store.close()

    assert result is not None
    assert isinstance(result, np.ndarray)
    assert list(result) == pytest.approx([0.5, 0.5, 0.5, 0.5], abs=1e-5)


@pytest.mark.asyncio
async def test_get_due_reminders_returns_expired_reminders_only(
    temp_db_path,
):
    """get_due_reminders returns reminders with expires_at <= now.

    Regression for Bug 4: get_all_facts excluded expired facts and did not
    include expires_at in the SELECT; get_due_reminders fixes both.
    """
    from datetime import datetime, timedelta

    store = KnowledgeStore(temp_db_path)
    await store.initialize()

    now = datetime.now(timezone.utc)
    past = (now - timedelta(hours=1)).isoformat()
    future = (now + timedelta(hours=1)).isoformat()

    # Store due reminder (expires_at in past)
    await store.store_fact(
        "reminder", "due_reminder", "pick up milk", expires_at=past
    )
    # Store future reminder (expires_at in future)
    await store.store_fact(
        "reminder", "future_reminder", "tomorrow task", expires_at=future
    )
    # Store reminder with no expires_at (should not appear)
    await store.store_fact("reminder", "no_expiry", "someday task")

    due = await store.get_due_reminders(limit=20)
    await store.close()

    assert len(due) == 1
    assert due[0]["key"] == "due_reminder"
    assert due[0]["value"] == "pick up milk"
    assert due[0]["expires_at"] == past


# ── Bug 3 regression tests (string comparison of ISO timestamps) ──


@pytest.mark.asyncio
async def test_get_due_reminders_naive_and_tzaware_both_returned(
    temp_db_path,
):
    """Regression for Bug 3 (P9-BUG-144): reminders with naive and tz-aware
    expires_at, both in the past, must both be returned by get_due_reminders.

    This verifies the fix: datetime.fromisoformat() + proper comparison
    instead of string comparison.
    """
    from datetime import datetime, timedelta, timezone

    store = KnowledgeStore(temp_db_path)
    await store.initialize()

    utc_now = datetime.now(timezone.utc)
    past = utc_now - timedelta(hours=1)
    tz_plus5 = timezone(timedelta(hours=5))

    # Naive past (no timezone) - treat as UTC
    naive_past = past.strftime("%Y-%m-%dT%H:%M:%S")
    # Tz-aware past (+05:00 offset)
    tzaware_past = (past.astimezone(tz_plus5)).isoformat()

    await store.store_fact(
        "reminder",
        "naive_past",
        "pick up milk",
        expires_at=naive_past,
    )
    await store.store_fact(
        "reminder",
        "tzaware_past",
        "call dentist",
        expires_at=tzaware_past,
    )

    due = await store.get_due_reminders(limit=20)
    await store.close()

    keys = {r["key"] for r in due}
    assert keys == {"naive_past", "tzaware_past"}
    assert len(due) == 2


@pytest.mark.asyncio
async def test_get_due_reminders_timezone_offset_comparison(temp_db_path):
    """Regression for Bug 3: expires_at with non-UTC timezone offset
    must be compared correctly using datetime parsing, not string comparison.

    String comparison of "2026-02-22T10:00:00+05:00" vs
    "2026-02-22T06:00:00+00:00" yields wrong result because it compares
    lexicographically. The +05:00 timestamp is actually 05:00 UTC,
    which is BEFORE 06:00 UTC.
    """
    from datetime import datetime, timedelta, timezone

    store = KnowledgeStore(temp_db_path)
    await store.initialize()

    # Create a reminder that expired 2 hours ago in UTC, but is
    # stored with a +05:00 offset so the local time looks "later"
    # than now_utc when compared as strings.
    utc_now = datetime.now(timezone.utc)
    tz_plus5 = timezone(timedelta(hours=5))
    # 2 hours ago in UTC, expressed in +05:00
    expired_dt = (utc_now - timedelta(hours=2)).astimezone(tz_plus5)
    expired_str = expired_dt.isoformat()

    await store.store_fact(
        "reminder",
        "tz_offset_reminder",
        "call dentist",
        expires_at=expired_str,
    )

    due = await store.get_due_reminders(limit=20)
    await store.close()

    # This reminder IS due (it expired 2h ago), regardless of
    # the +05:00 offset that makes the string look "larger"
    assert len(due) == 1
    assert due[0]["key"] == "tz_offset_reminder"


@pytest.mark.asyncio
async def test_get_due_reminders_naive_timestamp(temp_db_path):
    """Regression for Bug 3: naive (no timezone) expires_at values
    must be treated as UTC and compared correctly."""
    from datetime import datetime, timedelta

    store = KnowledgeStore(temp_db_path)
    await store.initialize()

    utc_now = datetime.now(timezone.utc)
    # Naive timestamp (no timezone info) in the past
    past_naive = (utc_now - timedelta(hours=1)).strftime(
        "%Y-%m-%dT%H:%M:%S"
    )
    # Naive timestamp in the future
    future_naive = (utc_now + timedelta(hours=1)).strftime(
        "%Y-%m-%dT%H:%M:%S"
    )

    await store.store_fact(
        "reminder",
        "past_naive",
        "past task",
        expires_at=past_naive,
    )
    await store.store_fact(
        "reminder",
        "future_naive",
        "future task",
        expires_at=future_naive,
    )

    due = await store.get_due_reminders(limit=20)
    await store.close()

    assert len(due) == 1
    assert due[0]["key"] == "past_naive"


@pytest.mark.asyncio
async def test_get_due_reminders_date_only_string(temp_db_path):
    """Regression for Bug 3: date-only expires_at like '2020-01-01'
    must be parsed and compared correctly as midnight UTC."""

    store = KnowledgeStore(temp_db_path)
    await store.initialize()

    # A date far in the past (always due)
    await store.store_fact(
        "reminder",
        "old_date_reminder",
        "old task",
        expires_at="2020-01-01",
    )
    # A date far in the future (never due)
    await store.store_fact(
        "reminder",
        "future_date_reminder",
        "future task",
        expires_at="2099-12-31",
    )

    due = await store.get_due_reminders(limit=20)
    await store.close()

    assert len(due) == 1
    assert due[0]["key"] == "old_date_reminder"


@pytest.mark.asyncio
async def test_get_due_reminders_z_suffix(temp_db_path):
    """Regression for Bug 3: expires_at with 'Z' suffix must be
    handled correctly (equivalent to +00:00)."""
    from datetime import datetime, timedelta

    store = KnowledgeStore(temp_db_path)
    await store.initialize()

    utc_now = datetime.now(timezone.utc)
    past_z = (utc_now - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")

    await store.store_fact(
        "reminder",
        "z_reminder",
        "z task",
        expires_at=past_z,
    )

    due = await store.get_due_reminders(limit=20)
    await store.close()

    assert len(due) == 1
    assert due[0]["key"] == "z_reminder"


# ── Bug 8 regression tests ──────────────────────


@pytest.mark.asyncio
async def test_store_fact_no_transaction_within_transaction(
    temp_db_path,
):
    """Regression for Bug 8 issue 1: store_fact()
    must not raise OperationalError from BEGIN
    IMMEDIATE when an implicit transaction is active.

    Before the fix, aiosqlite's default
    isolation_level="" caused an implicit transaction,
    and BEGIN IMMEDIATE raised "cannot start a
    transaction within a transaction".
    """
    store = KnowledgeStore(temp_db_path)
    await store.initialize()

    # This must not raise OperationalError
    fact_id = await store.store_fact("preference", "color", "blue", 1.0)
    assert isinstance(fact_id, int)
    assert fact_id > 0

    # Verify the fact was actually persisted
    results = await store.search_keyword("color")
    assert len(results) == 1
    assert results[0]["value"] == "blue"
    await store.close()


@pytest.mark.asyncio
async def test_store_fact_multiple_calls_no_txn_error(
    temp_db_path,
):
    """Regression for Bug 8 issue 1: multiple
    sequential store_fact() calls must all succeed
    without transaction nesting errors.
    """
    store = KnowledgeStore(temp_db_path)
    await store.initialize()

    id1 = await store.store_fact("pref", "food", "pizza", 0.9)
    id2 = await store.store_fact("pref", "drink", "water", 0.8)
    id3 = await store.store_fact("pref", "sport", "tennis", 0.7)

    assert id1 > 0
    assert id2 > 0
    assert id3 > 0
    assert len({id1, id2, id3}) == 3  # all unique

    all_facts = await store.get_all_facts()
    assert len(all_facts) == 3
    await store.close()


@pytest.mark.asyncio
async def test_store_fact_conflict_update_no_txn_error(
    temp_db_path,
):
    """Regression for Bug 8 issue 1: updating an
    existing fact (same category+key, higher
    confidence) must work without transaction errors.
    """
    store = KnowledgeStore(temp_db_path)
    await store.initialize()

    id1 = await store.store_fact("pref", "color", "red", 0.5)
    # Same key, higher confidence → should update
    id2 = await store.store_fact("pref", "color", "blue", 0.9)

    assert id1 == id2  # same fact updated
    results = await store.search_keyword("color")
    assert results[0]["value"] == "blue"
    await store.close()


@pytest.mark.asyncio
async def test_store_fact_rollback_does_not_mask_exception(
    temp_db_path,
):
    """Regression for Bug 8 issue 2: if store_fact()
    fails mid-transaction and rollback also fails,
    the original exception must still propagate (not
    be replaced by the rollback error).
    """
    store = KnowledgeStore(temp_db_path)
    await store.initialize()

    db = store._shared.connection
    original_execute = db.execute

    async def failing_execute(sql, *args, **kwargs):
        # Fail on the SELECT inside store_fact
        if "SELECT" in sql and "FROM facts" in sql:
            raise RuntimeError("simulated DB error")
        return await original_execute(sql, *args, **kwargs)

    db.execute = failing_execute

    # Make rollback itself fail
    async def failing_rollback():
        raise OSError("disk full during rollback")

    db.rollback = failing_rollback

    with pytest.raises(RuntimeError, match="simulated DB error"):
        await store.store_fact("pref", "color", "green", 1.0)

    await store.close()


@pytest.mark.asyncio
async def test_store_fact_rollback_succeeds_on_error(
    temp_db_path,
):
    """Regression for Bug 8 issue 2: when store_fact
    fails mid-transaction, a successful rollback
    still lets the original exception propagate.
    """
    store = KnowledgeStore(temp_db_path)
    await store.initialize()

    db = store._shared.connection
    original_execute = db.execute
    rollback_called = False
    original_rollback = db.rollback

    async def failing_execute(sql, *args, **kwargs):
        if "SELECT" in sql and "FROM facts" in sql:
            raise ValueError("simulated select failure")
        return await original_execute(sql, *args, **kwargs)

    async def tracking_rollback():
        nonlocal rollback_called
        rollback_called = True
        return await original_rollback()

    db.execute = failing_execute
    db.rollback = tracking_rollback

    with pytest.raises(ValueError, match="simulated select failure"):
        await store.store_fact("pref", "color", "green", 1.0)

    # Verify rollback was actually called
    assert rollback_called
    await store.close()


@pytest.mark.asyncio
async def test_isolation_level_set_after_initialize(
    temp_db_path,
):
    """Regression for Bug 8: after initialize(),
    the underlying connection's isolation_level must
    be None (manual transaction management).
    """
    store = KnowledgeStore(temp_db_path)
    await store.initialize()

    assert store._shared.connection._conn.isolation_level is None
    await store.close()


# ── Bug 31 regression tests (correct_fact atomicity) ──


@pytest.mark.asyncio
async def test_correct_fact_atomic_concurrent_correct_fact_and_store_fact(
    temp_db_path,
    mock_embed,
):
    """Regression for BUG-31 (P3-BUG-102, P6-BUG-93): correct_fact is atomic.

    Concurrent correct_fact + store_fact on the same (category, key) must not
    corrupt the store (no duplicates, no false 'Updated' with 0 rows changed).
    Two separate connections to the same DB simulate concurrent tasks.
    """
    import asyncio

    store1 = KnowledgeStore(temp_db_path)
    store2 = KnowledgeStore(temp_db_path)
    store1.set_embed_function(mock_embed)
    store2.set_embed_function(mock_embed)
    await store1.initialize()
    await store2.initialize()

    # Seed: one fact
    await store1.store_fact("pref", "favorite_color", "blue", 1.0)

    # Run correct_fact and store_fact concurrently to stress the race
    await asyncio.gather(
        store1.correct_fact("pref", "favorite_color", "corrected", 1.0),
        store2.store_fact("pref", "favorite_color", "stored", 0.9),
    )

    # Verify: exactly one fact for (pref, favorite_color)
    facts = await store1.get_all_facts(category="pref")
    color_facts = [f for f in facts if f["key"] == "favorite_color"]
    assert len(color_facts) == 1, (
        f"Expected 1 fact for favorite_color, got {len(color_facts)}: "
        f"{color_facts}"
    )

    # No contradictory facts (same cat+key, different values)
    contrad = await store1.get_contradictory_facts()
    assert len(contrad) == 0, f"Found contradictory facts: {contrad}"

    await store1.close()
    await store2.close()


# ── Bug 30 & 31 regression tests (correct_fact) ──


@pytest.mark.asyncio
async def test_correct_fact_sets_source_user(temp_db_path, mock_embed):
    """Regression for Bug 30: correct_fact() must set source='user' when updating.

    decay_confidence() skips facts with source='user'. Corrected facts
    must retain user source so they are not decayed.
    """

    store = KnowledgeStore(temp_db_path)
    store.set_embed_function(mock_embed)
    await store.initialize()

    # Store fact (source=auto by default)
    await store.store_fact("pref", "coffee", "likes latte", 0.8)
    # Correct it — must set source='user'
    await store.correct_fact("pref", "coffee", "likes espresso", 1.0)

    # Verify source is user via raw query (get_all_facts does not return source)
    async with store._shared.lock:
        db = store._shared.connection
        cursor = await db.execute(
            "SELECT source FROM facts WHERE category = ? AND key = ?",
            ("pref", "coffee"),
        )
        row = await cursor.fetchone()
    await store.close()

    assert row is not None
    assert row[0] == "user"


@pytest.mark.asyncio
async def test_correct_fact_source_user_skips_decay(
    temp_db_path, mock_embed
):
    """Regression for Bug 30: corrected facts (source='user') must not decay.

    decay_confidence() skips source='user'. After correct_fact, running
    decay should leave the fact's confidence unchanged.
    """
    from datetime import datetime, timedelta

    store = KnowledgeStore(temp_db_path)
    store.set_embed_function(mock_embed)
    await store.initialize()

    await store.store_fact("pref", "tea", "likes green tea", 0.9)
    await store.correct_fact("pref", "tea", "likes matcha", 1.0)

    # Set last_mentioned_at to 60 days ago so it would decay if source were auto
    old_date = (
        datetime.now(timezone.utc) - timedelta(days=60)
    ).isoformat()
    async with store._shared.lock:
        db = store._shared.connection
        await db.execute(
            "UPDATE facts SET last_mentioned_at = ? "
            "WHERE category = ? AND key = ?",
            (old_date, "pref", "tea"),
        )
        await db.commit()

    decayed = await store.decay_confidence(
        decay_rate=0.1, min_confidence=0.3
    )
    # User facts are skipped; nothing should decay
    assert decayed == 0

    async with store._shared.lock:
        db = store._shared.connection
        cursor = await db.execute(
            "SELECT confidence FROM facts WHERE category = ? AND key = ?",
            ("pref", "tea"),
        )
        row = await cursor.fetchone()
    await store.close()

    assert row is not None
    assert row[0] == 1.0


@pytest.mark.asyncio
async def test_correct_fact_transaction_atomic_update(
    temp_db_path, mock_embed
):
    """Regression for Bug 31: correct_fact uses BEGIN IMMEDIATE for atomicity.

    Verifies correct_fact atomically updates existing facts and does not
    raise when run (transaction protection in place).
    """
    store = KnowledgeStore(temp_db_path)
    store.set_embed_function(mock_embed)
    await store.initialize()

    await store.store_fact("pref", "fruit", "likes apples", 0.7)
    result = await store.correct_fact(
        "pref", "fruit", "likes oranges", 1.0
    )

    assert "Updated" in result
    results = await store.search_keyword("fruit")
    assert len(results) == 1
    assert results[0]["value"] == "likes oranges"
    await store.close()


@pytest.mark.asyncio
async def test_correct_fact_transaction_insert_when_missing(
    temp_db_path, mock_embed
):
    """Regression for Bug 31: correct_fact inserts when no existing fact.

    When (category, key) does not exist, correct_fact calls store_fact
    within the same transaction flow to insert with source='user'.
    """
    store = KnowledgeStore(temp_db_path)
    store.set_embed_function(mock_embed)
    await store.initialize()

    result = await store.correct_fact("pref", "newkey", "new value", 1.0)

    assert "Updated" in result
    results = await store.search_keyword("newkey")
    assert len(results) == 1
    assert results[0]["value"] == "new value"
    # Inserted via store_fact with source='user'
    async with store._shared.lock:
        db = store._shared.connection
        cursor = await db.execute(
            "SELECT source FROM facts WHERE category = ? AND key = ?",
            ("pref", "newkey"),
        )
        row = await cursor.fetchone()
    await store.close()
    assert row is not None
    assert row[0] == "user"


# ── Bug 45 / TEST-GAP-13: correct_fact source/decay interaction ──


@pytest.mark.asyncio
async def test_correct_fact_sets_source_user_when_updating_auto_fact(
    temp_db_path, mock_embed
):
    """Bug 45: Store fact with source='auto', call correct_fact() → fact has source='user'.

    correct_fact() must set source='user' when updating an existing fact so
    decay_confidence() will skip it. Corrected facts must NOT decay.
    """
    store = KnowledgeStore(temp_db_path)
    store.set_embed_function(mock_embed)
    await store.initialize()

    await store.store_fact(
        "pref", "coffee", "likes latte", 0.8, source="auto"
    )
    await store.correct_fact("pref", "coffee", "likes espresso", 1.0)

    async with store._shared.lock:
        db = store._shared.connection
        cursor = await db.execute(
            "SELECT source FROM facts WHERE category = ? AND key = ?",
            ("pref", "coffee"),
        )
        row = await cursor.fetchone()
    await store.close()

    assert row is not None
    assert row[0] == "user"


@pytest.mark.asyncio
async def test_decay_skips_user_source_decays_auto_source(
    temp_db_path, mock_embed
):
    """Bug 45: source='user' facts are NOT decayed; source='auto' facts ARE decayed.

    decay_confidence() skips facts with source='user'. Corrected facts (and any
    user-stated facts) must retain full confidence. Auto-inferred facts decay
    when last_mentioned_at is older than 30 days.
    """
    from datetime import datetime, timedelta

    store = KnowledgeStore(temp_db_path)
    store.set_embed_function(mock_embed)
    await store.initialize()

    # Fact with source='auto' (will decay when old)
    await store.store_fact(
        "pref", "auto_drink", "likes soda", 0.9, source="auto"
    )
    # Fact with source='user' (correct_fact sets this; must not decay)
    await store.store_fact(
        "pref", "user_drink", "likes water", 0.9, source="user"
    )

    # Set both last_mentioned_at to 60 days ago so decay would apply
    old_date = (
        datetime.now(timezone.utc) - timedelta(days=60)
    ).isoformat()

    async with store._shared.lock:
        db = store._shared.connection
        await db.execute(
            "UPDATE facts SET last_mentioned_at = ? "
            "WHERE category = ? AND key IN ('auto_drink', 'user_drink')",
            (old_date, "pref"),
        )
        await db.commit()

    decayed = await store.decay_confidence(
        decay_rate=0.1, min_confidence=0.3
    )

    # At least the auto fact should have decayed
    assert decayed >= 1

    async with store._shared.lock:
        db = store._shared.connection
        cursor = await db.execute(
            "SELECT key, source, confidence FROM facts "
            "WHERE category = ? AND key IN ('auto_drink', 'user_drink')",
            ("pref",),
        )
        rows = await cursor.fetchall()
    await store.close()

    by_key = {
        r[0]: (r[1], r[2]) for r in rows
    }  # key -> (source, confidence)

    # user fact: unchanged (confidence 0.9)
    assert "user_drink" in by_key
    assert by_key["user_drink"][1] == 0.9

    # auto fact: decayed (confidence < 0.9, >= min_confidence 0.3)
    assert "auto_drink" in by_key
    assert by_key["auto_drink"][1] < 0.9
    assert by_key["auto_drink"][1] >= 0.3


@pytest.mark.asyncio
async def test_correct_fact_preserves_source_user_when_already_user(
    temp_db_path, mock_embed
):
    """Bug 45: correct_fact() preserves source='user' when fact already has it.

    When correcting a fact that was originally stored with source='user',
    correct_fact must keep source='user' (or set it, as it always does).
    This ensures user-stated facts survive decay even after corrections.
    """
    store = KnowledgeStore(temp_db_path)
    store.set_embed_function(mock_embed)
    await store.initialize()

    # Store with source='user' explicitly
    await store.store_fact(
        "pref", "user_pref", "original value", 0.9, source="user"
    )
    await store.correct_fact("pref", "user_pref", "corrected value", 1.0)

    async with store._shared.lock:
        db = store._shared.connection
        cursor = await db.execute(
            "SELECT source, value FROM facts WHERE category = ? AND key = ?",
            ("pref", "user_pref"),
        )
        row = await cursor.fetchone()
    await store.close()

    assert row is not None
    assert row[0] == "user"
    assert row[1] == "corrected value"


@pytest.mark.asyncio
async def test_decay_confidence_skips_source_user_facts(
    temp_db_path, mock_embed
):
    """Bug 45: decay_confidence() does NOT decay facts with source='user'.

    Facts with source='user' are excluded from decay via WHERE source != 'user'.
    Run decay with old last_mentioned_at; user facts must keep their confidence.
    """
    from datetime import datetime, timedelta

    store = KnowledgeStore(temp_db_path)
    store.set_embed_function(mock_embed)
    await store.initialize()

    await store.store_fact(
        "pref", "user_fact", "user stated", 0.95, source="user"
    )

    old_date = (
        datetime.now(timezone.utc) - timedelta(days=90)
    ).isoformat()
    async with store._shared.lock:
        db = store._shared.connection
        await db.execute(
            "UPDATE facts SET last_mentioned_at = ? "
            "WHERE category = ? AND key = ?",
            (old_date, "pref", "user_fact"),
        )
        await db.commit()

    decayed = await store.decay_confidence(
        decay_rate=0.1, min_confidence=0.3
    )
    assert decayed == 0

    async with store._shared.lock:
        db = store._shared.connection
        cursor = await db.execute(
            "SELECT confidence FROM facts WHERE key = ?", ("user_fact",)
        )
        row = await cursor.fetchone()
    await store.close()

    assert row is not None
    assert row[0] == 0.95


@pytest.mark.asyncio
async def test_corrected_facts_survive_decay_cycles(
    temp_db_path, mock_embed
):
    """Bug 45: Corrected facts (source='user') survive multiple decay cycles.

    Critical interaction: store_fact (auto) → correct_fact (sets source=user)
    → decay runs multiple times → fact must retain value and confidence.
    """
    from datetime import datetime, timedelta

    store = KnowledgeStore(temp_db_path)
    store.set_embed_function(mock_embed)
    await store.initialize()

    # 1. Store fact with source=auto (inferred)
    await store.store_fact(
        "pref", "beverage", "likes tea", 0.7, source="auto"
    )

    # 2. User explicitly corrects it → must set source='user'
    await store.correct_fact("pref", "beverage", "likes coffee", 1.0)

    # 3. Backdate last_mentioned_at so decay would apply if source were auto
    old_date = (
        datetime.now(timezone.utc) - timedelta(days=120)
    ).isoformat()
    async with store._shared.lock:
        db = store._shared.connection
        await db.execute(
            "UPDATE facts SET last_mentioned_at = ? "
            "WHERE category = ? AND key = ?",
            (old_date, "pref", "beverage"),
        )
        await db.commit()

    # 4. Run decay multiple times (simulates repeated scheduler runs)
    for _ in range(5):
        decayed = await store.decay_confidence(
            decay_rate=0.2, min_confidence=0.3
        )
        assert decayed == 0, "User-corrected fact must never decay"

    # 5. Verify fact survived: value and confidence intact
    facts = await store.search_keyword("beverage")
    await store.close()

    assert len(facts) == 1
    assert facts[0]["value"] == "likes coffee"
    assert facts[0]["confidence"] == 1.0


# ── Bug 28 regression test: get_contradictory_facts ──
#
# Bug 28: The original self-JOIN looked for a.category = b.category AND
# a.key = b.key, but UNIQUE INDEX on (category, key) means only one row
# per (category, key) exists — the join could never match.
#
# Fix: Detect semantic contradictions instead — facts with similar
# embeddings but different values. Works with the unique constraint.


@pytest.mark.asyncio
async def test_get_contradictory_facts_finds_semantic_contradictions(
    temp_db_path, mock_embed
):
    """Regression for Bug 28: get_contradictory_facts must find facts that
    are semantically similar but have conflicting values.

    mock_embed uses semantic clusters (coffee/espresso/cappuccino) so
    "likes espresso" and "prefers cappuccino" get high similarity.
    Use different categories so store_fact's semantic dedup won't merge.
    """
    store = KnowledgeStore(temp_db_path)
    store.set_embed_function(mock_embed)
    await store.initialize()

    # Two facts with different categories (so dedup won't merge), same
    # embedding (mock), different values → contradiction
    await store.store_fact(
        "preference", "coffee_choice", "likes espresso", 0.9
    )
    await store.store_fact(
        "fact", "morning_drink", "prefers cappuccino", 0.5
    )

    contradictions = await store.get_contradictory_facts(
        similarity_threshold=0.85, limit=200
    )
    await store.close()

    # Must find at least one contradiction pair (both have same embedding,
    # different values)
    assert len(contradictions) >= 1
    pair = contradictions[0]
    assert len(pair) == 2
    fact_a, fact_b = pair
    assert fact_a["value"] != fact_b["value"]
    assert fact_a["id"] != fact_b["id"]


@pytest.mark.asyncio
async def test_get_contradictory_facts_empty_when_values_match(
    temp_db_path, mock_embed
):
    """Semantically similar facts with same value are NOT contradictions."""
    store = KnowledgeStore(temp_db_path)
    store.set_embed_function(mock_embed)
    await store.initialize()

    await store.store_fact("preference", "drink_a", "likes espresso", 0.9)
    await store.store_fact("preference", "drink_b", "likes espresso", 0.8)

    contradictions = await store.get_contradictory_facts(
        similarity_threshold=0.85, limit=200
    )
    await store.close()

    # Same value (after normalization) → not a contradiction
    assert len(contradictions) == 0


# ── Bug 17 regression: uninitialized store raises RuntimeError ──


@pytest.mark.asyncio
async def test_knowledge_store_uninitialized_raises_runtime_error(
    temp_db_path,
):
    """Regression for Bug 17: methods raise RuntimeError when initialize() not called."""
    store = KnowledgeStore(temp_db_path)

    with pytest.raises(RuntimeError, match="Store not initialized"):
        await store.store_fact("pref", "key", "value")

    with pytest.raises(RuntimeError, match="Store not initialized"):
        await store.search_keyword("query")

    with pytest.raises(RuntimeError, match="Store not initialized"):
        await store.get_all_facts()


@pytest.mark.asyncio
async def test_knowledge_store_after_close_raises_runtime_error(
    temp_db_path, mock_embed
):
    """Regression for Bug 17: after close(), methods raise RuntimeError not AttributeError."""
    store = KnowledgeStore(temp_db_path)
    store.set_embed_function(mock_embed)
    await store.initialize()
    await store.close()

    with pytest.raises(RuntimeError, match="Store not initialized"):
        await store.store_fact("pref", "key", "value")

    with pytest.raises(RuntimeError, match="Store not initialized"):
        await store.search_keyword("query")


# ── get_contradictory_facts (BUG-28 / P3-BUG-100) ──


@pytest.mark.asyncio
async def test_get_contradictory_facts_returns_empty_when_insufficient_facts(
    temp_db_path, mock_embed
):
    """BUG-28: With UNIQUE(category, key), same-key contradictions are impossible.
    get_contradictory_facts uses semantic similarity. With 0 or 1 fact, returns []."""
    store = KnowledgeStore(temp_db_path)
    store.set_embed_function(mock_embed)
    await store.initialize()

    # 0 facts
    contrad = await store.get_contradictory_facts()
    assert contrad == []

    # 1 fact
    await store.store_fact("pref", "coffee", "dark roast", 1.0)
    contrad = await store.get_contradictory_facts()
    assert contrad == []
    await store.close()


@pytest.mark.asyncio
async def test_get_contradictory_facts_finds_semantic_contradictions(
    temp_db_path, mock_embed
):
    """BUG-28: Semantic contradiction detection finds facts that are similar
    in meaning (embedding) but have different values. mock_embed gives identical
    embeddings, so any two facts with different values are contradictions."""
    store = KnowledgeStore(temp_db_path)
    store.set_embed_function(mock_embed)
    await store.initialize()

    await store.store_fact(
        "beverages", "coffee_a", "likes dark roast", 1.0
    )
    await store.store_fact("drinks", "coffee_b", "likes light roast", 1.0)
    contrad = await store.get_contradictory_facts()
    await store.close()

    assert len(contrad) == 1
    (fa, fb) = contrad[0]
    assert fa["value"] != fb["value"]
    assert fa["value"] in ("likes dark roast", "likes light roast")
    assert fb["value"] in ("likes dark roast", "likes light roast")


@pytest.mark.asyncio
async def test_get_contradictory_facts_excludes_same_value_pairs(
    temp_db_path, mock_embed
):
    """BUG-28: Facts with same value (normalized) are not contradictions
    even if semantically similar."""
    store = KnowledgeStore(temp_db_path)
    store.set_embed_function(mock_embed)
    await store.initialize()

    await store.store_fact("pref", "key1", "dark roast", 1.0)
    await store.store_fact(
        "pref", "key2", "Dark Roast", 1.0
    )  # same when normalized
    contrad = await store.get_contradictory_facts()
    await store.close()

    assert len(contrad) == 0


@pytest.mark.asyncio
async def test_get_contradictory_facts_returns_empty_when_no_embeddings(
    temp_db_path,
):
    """BUG-28: Without embedding function, facts have no embeddings.
    get_contradictory_facts only considers facts with embeddings, so returns []."""
    store = KnowledgeStore(temp_db_path)
    await store.initialize()

    await store.store_fact("pref", "coffee", "dark roast", 1.0)
    await store.store_fact("pref", "tea", "green tea", 1.0)
    # store_fact without embed_fn stores NULL embeddings
    contrad = await store.get_contradictory_facts()
    await store.close()

    assert contrad == []


# ── Additional coverage: delete_fact, decay_confidence, get_all_facts,
#    get_due_reminders, cleanup_expired, correct_fact, touch_fact ──


@pytest.mark.asyncio
async def test_delete_fact_by_key(temp_db_path, mock_embed):
    """delete_fact removes fact by key when category is empty."""
    store = KnowledgeStore(temp_db_path)
    store.set_embed_function(mock_embed)
    await store.initialize()

    await store.store_fact("pref", "color", "blue", 1.0)
    results_before = await store.get_all_facts()
    assert len(results_before) == 1

    deleted = await store.delete_fact("color")
    assert deleted is True

    results_after = await store.get_all_facts()
    assert len(results_after) == 0
    await store.close()


@pytest.mark.asyncio
async def test_delete_fact_by_key_and_category(temp_db_path, mock_embed):
    """delete_fact with category only deletes matching (category, key)."""
    store = KnowledgeStore(temp_db_path)
    store.set_embed_function(mock_embed)
    await store.initialize()

    await store.store_fact("pref", "drink", "coffee", 1.0)
    await store.store_fact("fact", "drink", "water", 1.0)

    deleted = await store.delete_fact("drink", category="pref")
    assert deleted is True

    facts = await store.get_all_facts()
    assert len(facts) == 1
    assert facts[0]["key"] == "drink" and facts[0]["value"] == "water"
    await store.close()


@pytest.mark.asyncio
async def test_delete_fact_returns_false_when_not_found(temp_db_path):
    """delete_fact returns False when no fact matches."""
    store = KnowledgeStore(temp_db_path)
    await store.initialize()

    deleted = await store.delete_fact("nonexistent")
    assert deleted is False
    await store.close()


@pytest.mark.asyncio
async def test_decay_confidence_reduces_confidence(
    temp_db_path, mock_embed
):
    """decay_confidence reduces confidence of facts not mentioned in 30+ days."""
    from datetime import datetime, timedelta

    store = KnowledgeStore(temp_db_path)
    store.set_embed_function(mock_embed)
    await store.initialize()

    await store.store_fact("pref", "old_fact", "value", 0.9, source="auto")
    old_date = (
        datetime.now(timezone.utc) - timedelta(days=60)
    ).isoformat()
    async with store._shared.lock:
        await store._shared.connection.execute(
            "UPDATE facts SET last_mentioned_at = ? WHERE key = ?",
            (old_date, "old_fact"),
        )
        await store._shared.connection.commit()

    decayed = await store.decay_confidence(
        decay_rate=0.5, min_confidence=0.3
    )
    assert decayed == 1

    facts = await store.get_all_facts()
    assert facts[0]["confidence"] < 0.9
    assert facts[0]["confidence"] >= 0.3
    await store.close()


@pytest.mark.asyncio
async def test_decay_confidence_skips_user_facts(temp_db_path, mock_embed):
    """decay_confidence skips facts with source='user'."""
    from datetime import datetime, timedelta

    store = KnowledgeStore(temp_db_path)
    store.set_embed_function(mock_embed)
    await store.initialize()

    await store.store_fact("pref", "user_fact", "value", 0.9)
    await store.correct_fact("pref", "user_fact", "corrected value", 1.0)
    old_date = (
        datetime.now(timezone.utc) - timedelta(days=60)
    ).isoformat()
    async with store._shared.lock:
        await store._shared.connection.execute(
            "UPDATE facts SET last_mentioned_at = ? WHERE key = ?",
            (old_date, "user_fact"),
        )
        await store._shared.connection.commit()

    decayed = await store.decay_confidence(
        decay_rate=0.5, min_confidence=0.3
    )
    assert decayed == 0

    facts = await store.get_all_facts()
    assert facts[0]["confidence"] == 1.0
    await store.close()


@pytest.mark.asyncio
async def test_decay_confidence_tz_aware_non_utc_converted_to_utc(
    temp_db_path, mock_embed
):
    """Regression for Bug 78 (P6-BUG-101): last_mentioned_at with timezone-aware
    non-UTC timestamps must be converted via astimezone(timezone.utc) for
    correct age calculation. Naive timestamps use replace(tzinfo=timezone.utc).
    """
    from datetime import datetime, timedelta, timezone

    store = KnowledgeStore(temp_db_path)
    store.set_embed_function(mock_embed)
    await store.initialize()

    await store.store_fact(
        "pref", "tz_aware_old", "value", 0.9, source="auto"
    )

    # 60 days ago in UTC, expressed as +05:00 (timezone-aware non-UTC)
    utc_60_days_ago = datetime.now(timezone.utc) - timedelta(days=60)
    tz_plus5 = timezone(timedelta(hours=5))
    last_mentioned_tz5 = utc_60_days_ago.astimezone(tz_plus5).isoformat()

    async with store._shared.lock:
        await store._shared.connection.execute(
            "UPDATE facts SET last_mentioned_at = ? WHERE key = ?",
            (last_mentioned_tz5, "tz_aware_old"),
        )
        await store._shared.connection.commit()

    decayed = await store.decay_confidence(
        decay_rate=0.5, min_confidence=0.3
    )
    assert decayed == 1

    facts = await store.get_all_facts()
    assert facts[0]["confidence"] < 0.9
    assert facts[0]["confidence"] >= 0.3
    await store.close()


@pytest.mark.asyncio
async def test_decay_confidence_naive_timestamp_treated_as_utc(
    temp_db_path, mock_embed
):
    """Regression for Bug 78: naive last_mentioned_at (no Z/tz in string) must
    be treated as UTC via replace(tzinfo=timezone.utc) for correct age calc.
    """
    from datetime import datetime, timedelta

    store = KnowledgeStore(temp_db_path)
    store.set_embed_function(mock_embed)
    await store.initialize()

    await store.store_fact(
        "pref", "naive_old", "value", 0.9, source="auto"
    )

    # 60 days ago, stored as naive ISO string (no timezone) — must be treated as UTC
    utc_60_days_ago = datetime.now(timezone.utc) - timedelta(days=60)
    naive_iso = utc_60_days_ago.replace(tzinfo=None).isoformat()

    async with store._shared.lock:
        await store._shared.connection.execute(
            "UPDATE facts SET last_mentioned_at = ? WHERE key = ?",
            (naive_iso, "naive_old"),
        )
        await store._shared.connection.commit()

    decayed = await store.decay_confidence(
        decay_rate=0.5, min_confidence=0.3
    )
    assert decayed == 1

    facts = await store.get_all_facts()
    assert facts[0]["confidence"] < 0.9
    assert facts[0]["confidence"] >= 0.3
    await store.close()


@pytest.mark.asyncio
async def test_decay_confidence_respects_min_confidence(
    temp_db_path, mock_embed
):
    """decay_confidence does not reduce below min_confidence."""
    from datetime import datetime, timedelta

    store = KnowledgeStore(temp_db_path)
    store.set_embed_function(mock_embed)
    await store.initialize()

    await store.store_fact("pref", "very_old", "value", 0.5, source="auto")
    old_date = (
        datetime.now(timezone.utc) - timedelta(days=120)
    ).isoformat()
    async with store._shared.lock:
        await store._shared.connection.execute(
            "UPDATE facts SET last_mentioned_at = ? WHERE key = ?",
            (old_date, "very_old"),
        )
        await store._shared.connection.commit()

    decayed = await store.decay_confidence(
        decay_rate=0.99, min_confidence=0.4
    )
    assert decayed == 1

    facts = await store.get_all_facts()
    assert facts[0]["confidence"] == 0.4
    await store.close()


@pytest.mark.asyncio
async def test_get_all_facts_returns_all(temp_db_path, mock_embed):
    """get_all_facts returns all non-expired facts when category is None."""
    store = KnowledgeStore(temp_db_path)
    store.set_embed_function(mock_embed)
    await store.initialize()

    await store.store_fact("pref", "a", "val1", 1.0)
    await store.store_fact("fact", "b", "val2", 1.0)
    await store.store_fact("pref", "c", "val3", 1.0)

    facts = await store.get_all_facts()
    assert len(facts) == 3
    keys = {f["key"] for f in facts}
    assert keys == {"a", "b", "c"}
    await store.close()


@pytest.mark.asyncio
async def test_get_all_facts_filters_by_category(temp_db_path, mock_embed):
    """get_all_facts with category returns only facts in that category."""
    store = KnowledgeStore(temp_db_path)
    store.set_embed_function(mock_embed)
    await store.initialize()

    await store.store_fact("pref", "x", "val", 1.0)
    await store.store_fact("fact", "y", "val", 1.0)
    await store.store_fact("pref", "z", "val", 1.0)

    facts = await store.get_all_facts(category="pref")
    assert len(facts) == 2
    assert all(f["category"] == "pref" for f in facts)
    await store.close()


@pytest.mark.asyncio
async def test_get_all_facts_respects_limit(temp_db_path, mock_embed):
    """get_all_facts respects limit parameter."""
    store = KnowledgeStore(temp_db_path)
    store.set_embed_function(mock_embed)
    await store.initialize()

    for i in range(5):
        await store.store_fact("pref", f"key_{i}", f"val{i}", 1.0)

    facts = await store.get_all_facts(limit=2)
    assert len(facts) == 2
    await store.close()


@pytest.mark.asyncio
async def test_get_all_facts_excludes_expired(temp_db_path, mock_embed):
    """get_all_facts excludes facts with expires_at in the past."""
    from datetime import datetime, timedelta

    store = KnowledgeStore(temp_db_path)
    store.set_embed_function(mock_embed)
    await store.initialize()

    now = datetime.now(timezone.utc)
    past = (now - timedelta(hours=1)).isoformat()
    future = (now + timedelta(hours=1)).isoformat()

    await store.store_fact("pref", "expired", "old", 1.0, expires_at=past)
    await store.store_fact("pref", "valid", "new", 1.0, expires_at=future)

    facts = await store.get_all_facts()
    assert len(facts) == 1
    assert facts[0]["key"] == "valid"
    await store.close()


@pytest.mark.asyncio
async def test_get_due_reminders_respects_limit(temp_db_path):
    """get_due_reminders respects limit parameter."""
    from datetime import datetime, timedelta

    store = KnowledgeStore(temp_db_path)
    await store.initialize()

    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    for i in range(5):
        await store.store_fact(
            "reminder", f"rem_{i}", f"task {i}", expires_at=past
        )

    due = await store.get_due_reminders(limit=2)
    assert len(due) == 2
    await store.close()


@pytest.mark.asyncio
async def test_cleanup_expired_deletes_expired_facts(
    temp_db_path, mock_embed
):
    """cleanup_expired deletes facts with expires_at in the past."""
    from datetime import datetime, timedelta

    store = KnowledgeStore(temp_db_path)
    store.set_embed_function(mock_embed)
    await store.initialize()

    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()

    await store.store_fact("pref", "expired", "old", 1.0, expires_at=past)
    await store.store_fact("pref", "valid", "new", 1.0, expires_at=future)

    deleted = await store.cleanup_expired()
    assert deleted == 1

    facts = await store.get_all_facts()
    assert len(facts) == 1
    assert facts[0]["key"] == "valid"
    await store.close()


@pytest.mark.asyncio
async def test_cleanup_expired_keeps_non_expired(temp_db_path, mock_embed):
    """cleanup_expired leaves non-expired facts and those without expires_at."""
    from datetime import datetime, timedelta

    store = KnowledgeStore(temp_db_path)
    store.set_embed_function(mock_embed)
    await store.initialize()

    future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()

    await store.store_fact("pref", "no_expiry", "stays forever", 1.0)
    await store.store_fact(
        "pref", "future_expiry", "expires later", 1.0, expires_at=future
    )

    deleted = await store.cleanup_expired()
    assert deleted == 0

    facts = await store.get_all_facts()
    assert len(facts) == 2
    await store.close()


@pytest.mark.asyncio
async def test_cleanup_expired_returns_count(temp_db_path, mock_embed):
    """cleanup_expired returns the number of deleted rows."""
    from datetime import datetime, timedelta

    store = KnowledgeStore(temp_db_path)
    store.set_embed_function(mock_embed)
    await store.initialize()

    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    await store.store_fact("pref", "e1", "v1", 1.0, expires_at=past)
    await store.store_fact("pref", "e2", "v2", 1.0, expires_at=past)

    deleted = await store.cleanup_expired()
    assert deleted == 2
    await store.close()


@pytest.mark.asyncio
async def test_correct_fact_updates_existing(temp_db_path, mock_embed):
    """correct_fact force-updates existing fact regardless of confidence."""
    store = KnowledgeStore(temp_db_path)
    store.set_embed_function(mock_embed)
    await store.initialize()

    await store.store_fact("pref", "color", "red", 0.9)
    result = await store.correct_fact("pref", "color", "blue", 0.5)

    assert "Updated" in result
    assert "blue" in result
    facts = await store.search_keyword("color")
    assert len(facts) == 1
    assert facts[0]["value"] == "blue"
    await store.close()


@pytest.mark.asyncio
async def test_touch_fact_updates_last_mentioned(temp_db_path, mock_embed):
    """touch_fact updates last_mentioned_at for the given fact_id."""
    from datetime import datetime, timedelta

    store = KnowledgeStore(temp_db_path)
    store.set_embed_function(mock_embed)
    await store.initialize()

    await store.store_fact("pref", "touch_target", "value", 1.0)
    facts_before = await store.get_all_facts()
    fact_id = facts_before[0]["id"]

    old_date = (
        datetime.now(timezone.utc) - timedelta(days=60)
    ).isoformat()
    async with store._shared.lock:
        await store._shared.connection.execute(
            "UPDATE facts SET last_mentioned_at = ? WHERE id = ?",
            (old_date, fact_id),
        )
        await store._shared.connection.commit()

    await store.touch_fact(fact_id)

    async with store._shared.lock:
        cursor = await store._shared.connection.execute(
            "SELECT last_mentioned_at FROM facts WHERE id = ?",
            (fact_id,),
        )
        row = await cursor.fetchone()
    assert row is not None
    assert row[0] != old_date
    await store.close()


# ── Bug 14 / P3-GAP-2: coverage for get_low_confidence_facts,
#    get_stale_facts, delete_fact_by_id, store_fact edge cases,
#    search_semantic fallback, search_keyword edge cases ──


@pytest.mark.asyncio
async def test_get_low_confidence_facts_returns_below_threshold(
    temp_db_path, mock_embed
):
    """get_low_confidence_facts returns facts with confidence below threshold."""
    store = KnowledgeStore(temp_db_path)
    store.set_embed_function(mock_embed)
    await store.initialize()

    await store.store_fact("pref", "low", "v1", 0.3)
    await store.store_fact("pref", "mid", "v2", 0.5)
    await store.store_fact("pref", "high", "v3", 0.9)

    low = await store.get_low_confidence_facts(threshold=0.4)
    assert len(low) == 1
    assert low[0]["key"] == "low"
    assert low[0]["confidence"] == 0.3
    await store.close()


@pytest.mark.asyncio
async def test_get_low_confidence_facts_respects_limit(
    temp_db_path, mock_embed
):
    """get_low_confidence_facts respects limit parameter."""
    store = KnowledgeStore(temp_db_path)
    store.set_embed_function(mock_embed)
    await store.initialize()

    for i in range(5):
        await store.store_fact("pref", f"low_{i}", f"v{i}", 0.2)

    low = await store.get_low_confidence_facts(threshold=0.5, limit=2)
    assert len(low) == 2
    await store.close()


@pytest.mark.asyncio
async def test_get_low_confidence_facts_excludes_expired(
    temp_db_path, mock_embed
):
    """get_low_confidence_facts excludes facts with expires_at in the past."""
    from datetime import datetime, timedelta

    store = KnowledgeStore(temp_db_path)
    store.set_embed_function(mock_embed)
    await store.initialize()

    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    await store.store_fact(
        "pref", "expired_low", "v", 0.2, expires_at=past
    )
    await store.store_fact("pref", "valid_low", "v", 0.3)

    low = await store.get_low_confidence_facts(threshold=0.5)
    assert len(low) == 1
    assert low[0]["key"] == "valid_low"
    await store.close()


@pytest.mark.asyncio
async def test_get_stale_facts_returns_old_mentions(
    temp_db_path, mock_embed
):
    """get_stale_facts returns facts not mentioned in N days."""
    from datetime import datetime, timedelta

    store = KnowledgeStore(temp_db_path)
    store.set_embed_function(mock_embed)
    await store.initialize()

    await store.store_fact("pref", "recent", "v1", 1.0)
    await store.store_fact("pref", "old", "v2", 1.0)

    old_date = (
        datetime.now(timezone.utc) - timedelta(days=100)
    ).isoformat()
    async with store._shared.lock:
        await store._shared.connection.execute(
            "UPDATE facts SET last_mentioned_at = ? WHERE key = ?",
            (old_date, "old"),
        )
        await store._shared.connection.commit()

    stale = await store.get_stale_facts(days=90, limit=10)
    assert len(stale) == 1
    assert stale[0]["key"] == "old"
    assert "last_mentioned_at" in stale[0]
    await store.close()


@pytest.mark.asyncio
async def test_get_stale_facts_respects_limit(temp_db_path, mock_embed):
    """get_stale_facts respects limit parameter."""
    from datetime import datetime, timedelta

    store = KnowledgeStore(temp_db_path)
    store.set_embed_function(mock_embed)
    await store.initialize()

    old_date = (
        datetime.now(timezone.utc) - timedelta(days=100)
    ).isoformat()
    for i in range(5):
        await store.store_fact("pref", f"stale_{i}", f"v{i}", 1.0)
    async with store._shared.lock:
        db = store._shared.connection
        await db.execute(
            "UPDATE facts SET last_mentioned_at = ?",
            (old_date,),
        )
        await db.commit()

    stale = await store.get_stale_facts(days=90, limit=2)
    assert len(stale) == 2
    await store.close()


@pytest.mark.asyncio
async def test_delete_fact_by_id_removes_fact(temp_db_path, mock_embed):
    """delete_fact_by_id removes the fact with the given ID."""
    store = KnowledgeStore(temp_db_path)
    store.set_embed_function(mock_embed)
    await store.initialize()

    fact_id = await store.store_fact("pref", "to_delete", "value", 1.0)
    assert fact_id > 0

    deleted = await store.delete_fact_by_id(fact_id)
    assert deleted is True

    results = await store.get_all_facts()
    assert len(results) == 0
    await store.close()


@pytest.mark.asyncio
async def test_delete_fact_by_id_returns_false_when_not_found(
    temp_db_path,
):
    """delete_fact_by_id returns False when no fact has that ID."""
    store = KnowledgeStore(temp_db_path)
    await store.initialize()

    deleted = await store.delete_fact_by_id(99999)
    assert deleted is False
    await store.close()


@pytest.mark.asyncio
async def test_store_fact_force_updates_regardless_of_confidence(
    temp_db_path, mock_embed
):
    """store_fact with force=True updates even when new confidence < old."""
    store = KnowledgeStore(temp_db_path)
    store.set_embed_function(mock_embed)
    await store.initialize()

    await store.store_fact("pref", "color", "red", 0.9)
    fact_id = await store.store_fact(
        "pref", "color", "blue", 0.3, force=True
    )
    assert fact_id > 0

    facts = await store.search_keyword("color")
    assert len(facts) == 1
    assert facts[0]["value"] == "blue"
    await store.close()


@pytest.mark.asyncio
async def test_store_fact_with_expires_at(temp_db_path, mock_embed):
    """store_fact stores expires_at correctly."""
    from datetime import datetime, timedelta

    store = KnowledgeStore(temp_db_path)
    store.set_embed_function(mock_embed)
    await store.initialize()

    future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    fact_id = await store.store_fact(
        "reminder", "task", "do something", 1.0, expires_at=future
    )
    assert fact_id > 0

    facts = await store.get_all_facts(category="reminder")
    assert len(facts) == 1
    await store.close()


@pytest.mark.asyncio
async def test_store_fact_same_value_touches_only(
    temp_db_path, mock_embed
):
    """store_fact with same value updates last_mentioned_at only, same fact_id."""
    store = KnowledgeStore(temp_db_path)
    store.set_embed_function(mock_embed)
    await store.initialize()

    fact_id1 = await store.store_fact("pref", "key", "value", 1.0)
    fact_id2 = await store.store_fact("pref", "key", "value", 0.5)

    assert fact_id1 == fact_id2
    facts = await store.get_all_facts()
    assert len(facts) == 1
    assert facts[0]["value"] == "value"
    await store.close()


@pytest.mark.asyncio
async def test_search_semantic_fallback_to_keyword_when_no_embed(
    temp_db_path,
):
    """search_semantic falls back to search_keyword when no embedding fn set."""
    store = KnowledgeStore(temp_db_path)
    await store.initialize()

    await store.store_fact("pref", "coffee", "dark roast", 1.0)
    results = await store.search_semantic("coffee", limit=5)

    assert len(results) == 1
    assert results[0]["key"] == "coffee"
    assert "similarity" not in results[0]
    await store.close()


@pytest.mark.asyncio
async def test_search_semantic_fallback_when_embed_returns_none(
    temp_db_path,
):
    """search_semantic falls back to search_keyword when embed_fn returns None (e.g. on error)."""

    async def failing_embed(_text):
        raise ValueError("embedding API error")

    store = KnowledgeStore(temp_db_path)
    store.set_embed_function(failing_embed)
    await store.initialize()

    await store.store_fact("pref", "tea", "green tea", 1.0)
    results = await store.search_semantic("tea", limit=5)

    assert len(results) == 1
    assert results[0]["key"] == "tea"
    assert "similarity" not in results[0]
    await store.close()


@pytest.mark.asyncio
async def test_search_keyword_escapes_special_chars(
    temp_db_path, mock_embed
):
    """search_keyword escapes LIKE wildcards %, _, \\ correctly."""
    store = KnowledgeStore(temp_db_path)
    store.set_embed_function(mock_embed)
    await store.initialize()

    await store.store_fact("pref", "pct", "50% sugar", 1.0)
    await store.store_fact("pref", "underscore", "a_b", 1.0)

    results_pct = await store.search_keyword("50%", limit=5)
    assert len(results_pct) == 1
    assert results_pct[0]["value"] == "50% sugar"

    results_under = await store.search_keyword("a_b", limit=5)
    assert len(results_under) == 1
    await store.close()


@pytest.mark.asyncio
async def test_search_semantic_zero_query_vector_fallback(
    temp_db_path, mock_embed
):
    """search_semantic falls back to keyword when query embedding has zero norm."""

    async def zero_embed(_text):
        return [0.0, 0.0, 0.0, 0.0]

    store = KnowledgeStore(temp_db_path)
    store.set_embed_function(zero_embed)
    await store.initialize()

    await store.store_fact("pref", "fallback_key", "fallback value", 1.0)
    results = await store.search_semantic("fallback", limit=5)

    assert len(results) == 1
    assert results[0]["key"] == "fallback_key"
    assert "similarity" not in results[0]
    await store.close()


@pytest.mark.asyncio
async def test_search_keyword_respects_limit(temp_db_path, mock_embed):
    """search_keyword respects limit parameter."""
    store = KnowledgeStore(temp_db_path)
    store.set_embed_function(mock_embed)
    await store.initialize()

    distinct_values = [
        "coffee dark",
        "weather sunny",
        "tea green",
        "rain heavy",
        "test fallback",
    ]
    for i in range(5):
        await store.store_fact(
            f"cat_{i}", f"match_{i}", distinct_values[i], 1.0
        )

    results = await store.search_keyword("match", limit=2)
    assert len(results) == 2
    await store.close()


@pytest.mark.asyncio
async def test_search_semantic_returns_similarity_score(
    temp_db_path, mock_embed
):
    """search_semantic includes similarity score in results."""
    store = KnowledgeStore(temp_db_path)
    store.set_embed_function(mock_embed)
    await store.initialize()

    await store.store_fact("fact", "test", "test value", 1.0)
    results = await store.search_semantic("test", limit=5)

    assert len(results) >= 1
    assert "similarity" in results[0]
    assert isinstance(results[0]["similarity"], (int, float))
    await store.close()


@pytest.mark.asyncio
async def test_search_semantic_ranking_relevant_facts_first(
    temp_db_path, mock_embed
):
    """Semantic search ranks relevant facts higher than irrelevant ones.

    With mock_embed returning text-dependent vectors (Bug 51 fix), query
    'weather' matches 'weather: sunny' more strongly than 'coffee: dark roast'.
    """
    store = KnowledgeStore(temp_db_path)
    store.set_embed_function(mock_embed)
    await store.initialize()

    await store.store_fact(
        "fact", "weather_key", "weather is sunny today", 1.0
    )
    await store.store_fact("fact", "coffee_key", "coffee dark roast", 1.0)

    results = await store.search_semantic("weather", limit=5)
    await store.close()

    assert len(results) >= 2
    # Most relevant (weather-related) must rank first
    assert results[0]["key"] == "weather_key"
    assert results[0]["similarity"] > results[1]["similarity"]
    assert results[1]["key"] == "coffee_key"


# ── Bug 76 (P8-BUG-137): duplicate adopts key, value, confidence, embedding ──


@pytest.mark.asyncio
async def test_store_fact_duplicate_adopts_new_key_value_confidence_embedding(
    temp_db_path, mock_embed
):
    """Regression for Bug 76: When _check_duplicate finds a semantic match,
    the existing fact is UPDATED with the new fact's key, value, confidence,
    embedding — not just last_mentioned_at."""
    store = KnowledgeStore(temp_db_path)
    store.set_embed_function(mock_embed)
    await store.initialize()

    # Store initial fact
    id1 = await store.store_fact("pref", "old_key", "old value", 0.6)
    # Semantic duplicate (different key, more specific value, higher confidence)
    # mock_embed clusters old/refined/specific/value → _check_duplicate finds it
    id2 = await store.store_fact(
        "pref", "specific_key", "refined specific value", 0.95
    )

    assert id1 == id2
    facts = await store.get_all_facts()
    assert len(facts) == 1
    assert facts[0]["key"] == "specific_key"
    assert facts[0]["value"] == "refined specific value"
    assert facts[0]["confidence"] == 0.95
    await store.close()


# ── Bug 14: _check_duplicate (semantic dedup) coverage ──


@pytest.mark.asyncio
async def test_store_fact_semantic_dedup_skips_duplicate_insert(
    temp_db_path, mock_embed
):
    """store_fact with semantically duplicate value in same category updates
    existing fact with new key/value/confidence instead of inserting.
    Regression for Bug 76: duplicate adopts incoming fact's key, value, confidence."""
    store = KnowledgeStore(temp_db_path)
    store.set_embed_function(mock_embed)
    await store.initialize()

    id1 = await store.store_fact("pref", "coffee", "likes espresso", 0.9)
    # Different key, semantically similar value (mock_embed clusters espresso)
    id2 = await store.store_fact(
        "pref", "morning_drink", "prefers espresso shots", 0.5
    )

    # Should have updated first fact with new key/value/confidence, not inserted
    assert id1 == id2
    facts = await store.get_all_facts()
    assert len(facts) == 1
    assert facts[0]["key"] == "morning_drink"
    assert facts[0]["value"] == "prefers espresso shots"
    assert facts[0]["confidence"] == 0.5
    await store.close()


@pytest.mark.asyncio
async def test_decay_confidence_skips_facts_with_null_last_mentioned(
    temp_db_path, mock_embed
):
    """decay_confidence skips facts where last_mentioned_at IS NULL."""

    store = KnowledgeStore(temp_db_path)
    store.set_embed_function(mock_embed)
    await store.initialize()

    await store.store_fact(
        "pref", "no_last_mentioned", "v", 0.5, source="auto"
    )
    async with store._shared.lock:
        db = store._shared.connection
        await db.execute(
            "UPDATE facts SET last_mentioned_at = NULL WHERE key = ?",
            ("no_last_mentioned",),
        )
        await db.commit()

    decayed = await store.decay_confidence(
        decay_rate=0.5, min_confidence=0.3
    )
    assert decayed == 0
    await store.close()


@pytest.mark.asyncio
async def test_search_semantic_fallback_when_embedding_raises(
    temp_db_path,
):
    """search_semantic falls back to search_keyword when _embed_text raises."""
    store = KnowledgeStore(temp_db_path)
    await store.initialize()

    await store.store_fact("pref", "coffee", "dark roast", 1.0)

    async def failing_embed(_text):
        raise RuntimeError("embedding API down")

    store.set_embed_function(failing_embed)

    results = await store.search_semantic("coffee", limit=5)
    await store.close()

    assert len(results) == 1
    assert results[0]["key"] == "coffee"
    assert "similarity" not in results[0]


@pytest.mark.asyncio
async def test_search_semantic_fallback_when_embedding_returns_none(
    temp_db_path,
):
    """search_semantic falls back to search_keyword when _embed_text returns None."""
    store = KnowledgeStore(temp_db_path)
    await store.initialize()

    async def none_embed(_text):
        return None

    store.set_embed_function(none_embed)
    await store.store_fact("pref", "tea", "green tea", 1.0)

    results = await store.search_semantic("tea", limit=5)
    await store.close()

    assert len(results) == 1
    assert results[0]["key"] == "tea"


@pytest.mark.asyncio
async def test_get_contradictory_facts_respects_similarity_threshold(
    temp_db_path, mock_embed
):
    """get_contradictory_facts returns empty when threshold is above similarity."""
    store = KnowledgeStore(temp_db_path)
    store.set_embed_function(mock_embed)
    await store.initialize()

    await store.store_fact("pref", "a", "value one", 1.0)
    await store.store_fact("fact", "b", "value two", 1.0)

    # With very high threshold, no pairs pass
    contrad = await store.get_contradictory_facts(
        similarity_threshold=1.01
    )
    await store.close()

    assert contrad == []


@pytest.mark.asyncio
async def test_store_fact_without_embed_fn_stores_with_null_embedding(
    temp_db_path,
):
    """store_fact without set_embed_function stores facts with embedding=NULL."""
    store = KnowledgeStore(temp_db_path)
    await store.initialize()

    fact_id = await store.store_fact("pref", "key", "value", 1.0)
    assert fact_id > 0

    async with store._shared.lock:
        cursor = await store._shared.connection.execute(
            "SELECT embedding FROM facts WHERE id = ?", (fact_id,)
        )
        row = await cursor.fetchone()
    await store.close()

    assert row is not None
    assert row[0] is None


@pytest.mark.asyncio
async def test_set_embed_function_enables_semantic_search(
    temp_db_path, mock_embed
):
    """set_embed_function enables semantic search; results include similarity."""
    store = KnowledgeStore(temp_db_path)
    store.set_embed_function(mock_embed)
    await store.initialize()

    await store.store_fact("pref", "x", "semantic value", 1.0)
    results = await store.search_semantic("semantic", limit=5)
    await store.close()

    assert len(results) >= 1
    assert "similarity" in results[0]


@pytest.mark.asyncio
async def test_get_stale_facts_returns_empty_when_all_recent(
    temp_db_path, mock_embed
):
    """get_stale_facts returns [] when all facts were mentioned recently."""
    store = KnowledgeStore(temp_db_path)
    store.set_embed_function(mock_embed)
    await store.initialize()

    await store.store_fact("pref", "recent1", "v1", 1.0)
    await store.store_fact("pref", "recent2", "v2", 1.0)

    stale = await store.get_stale_facts(days=90, limit=10)
    await store.close()

    assert stale == []


@pytest.mark.asyncio
async def test_search_keyword_returns_empty_when_no_match(
    temp_db_path, mock_embed
):
    """search_keyword returns [] when no fact matches the query."""
    store = KnowledgeStore(temp_db_path)
    store.set_embed_function(mock_embed)
    await store.initialize()

    await store.store_fact("pref", "coffee", "dark roast", 1.0)

    results = await store.search_keyword("nonexistent_term_xyz", limit=5)
    await store.close()

    assert results == []


# ── Bug 14: Additional coverage for edge cases ──


@pytest.mark.asyncio
async def test_store_fact_semantic_dedup_touches_existing(
    temp_db_path, mock_embed
):
    """_check_duplicate: storing semantically similar fact (different key) updates existing.

    Regression for Bug 76: When a duplicate is found, the existing fact adopts the
    incoming fact's key, value, confidence. mock_embed clusters likes/espresso.
    """
    store = KnowledgeStore(temp_db_path)
    store.set_embed_function(mock_embed)
    await store.initialize()

    id1 = await store.store_fact(
        "pref", "coffee_pref", "likes espresso", 0.9
    )
    # Different key, same value → same embedding with mock_embed → semantic duplicate
    id2 = await store.store_fact(
        "pref", "morning_drink", "likes espresso", 0.5
    )

    assert id1 == id2
    facts = await store.get_all_facts()
    assert len(facts) == 1
    assert facts[0]["key"] == "morning_drink"
    assert facts[0]["value"] == "likes espresso"
    assert facts[0]["confidence"] == 0.5
    await store.close()


@pytest.mark.asyncio
async def test_store_fact_lower_confidence_without_force_keeps_old_value(
    temp_db_path, mock_embed
):
    """store_fact with lower confidence and no force does NOT update existing fact."""
    store = KnowledgeStore(temp_db_path)
    store.set_embed_function(mock_embed)
    await store.initialize()

    fact_id1 = await store.store_fact("pref", "color", "blue", 0.9)
    fact_id2 = await store.store_fact("pref", "color", "red", 0.5)

    assert fact_id1 == fact_id2
    facts = await store.search_keyword("color")
    assert len(facts) == 1
    assert facts[0]["value"] == "blue"
    assert facts[0]["confidence"] == 0.9
    await store.close()


@pytest.mark.asyncio
async def test_store_fact_with_source_persisted(temp_db_path, mock_embed):
    """store_fact with source='user' persists the source correctly."""
    store = KnowledgeStore(temp_db_path)
    store.set_embed_function(mock_embed)
    await store.initialize()

    await store.store_fact(
        "pref", "user_pref", "stated by user", 1.0, source="user"
    )

    async with store._shared.lock:
        cursor = await store._shared.connection.execute(
            "SELECT source FROM facts WHERE key = ?", ("user_pref",)
        )
        row = await cursor.fetchone()
    await store.close()

    assert row is not None
    assert row[0] == "user"


@pytest.mark.asyncio
async def test_search_keyword_empty_when_no_match(
    temp_db_path, mock_embed
):
    """search_keyword returns [] when no fact matches the query."""
    store = KnowledgeStore(temp_db_path)
    store.set_embed_function(mock_embed)
    await store.initialize()

    await store.store_fact("pref", "coffee", "dark roast", 1.0)
    results = await store.search_keyword("tea", limit=5)
    await store.close()

    assert results == []


@pytest.mark.asyncio
async def test_search_semantic_empty_when_no_facts(
    temp_db_path, mock_embed
):
    """search_semantic returns [] when store has no facts."""
    store = KnowledgeStore(temp_db_path)
    store.set_embed_function(mock_embed)
    await store.initialize()

    results = await store.search_semantic("anything", limit=5)
    await store.close()

    assert results == []


@pytest.mark.asyncio
async def test_decay_confidence_skips_null_last_mentioned(
    temp_db_path, mock_embed
):
    """decay_confidence skips facts with last_mentioned_at IS NULL."""

    store = KnowledgeStore(temp_db_path)
    store.set_embed_function(mock_embed)
    await store.initialize()

    await store.store_fact(
        "pref", "no_last_mention", "value", 0.9, source="auto"
    )
    async with store._shared.lock:
        await store._shared.connection.execute(
            "UPDATE facts SET last_mentioned_at = NULL WHERE key = ?",
            ("no_last_mention",),
        )
        await store._shared.connection.commit()

    decayed = await store.decay_confidence(
        decay_rate=0.5, min_confidence=0.3
    )
    assert decayed == 0

    facts = await store.get_all_facts()
    assert facts[0]["confidence"] == 0.9
    await store.close()


@pytest.mark.asyncio
async def test_get_all_facts_empty_store_returns_empty_list(
    temp_db_path, mock_embed
):
    """get_all_facts returns empty list when store has no facts."""
    store = KnowledgeStore(temp_db_path)
    store.set_embed_function(mock_embed)
    await store.initialize()

    facts = await store.get_all_facts()
    await store.close()

    assert facts == []


@pytest.mark.asyncio
async def test_get_low_confidence_facts_empty_when_all_above_threshold(
    temp_db_path, mock_embed
):
    """get_low_confidence_facts returns [] when all facts above threshold."""
    store = KnowledgeStore(temp_db_path)
    store.set_embed_function(mock_embed)
    await store.initialize()

    await store.store_fact("pref", "high1", "v1", 0.9)
    await store.store_fact("pref", "high2", "v2", 1.0)

    low = await store.get_low_confidence_facts(threshold=0.5)
    await store.close()

    assert low == []


@pytest.mark.asyncio
async def test_decay_confidence_returns_zero_when_all_recent(
    temp_db_path, mock_embed
):
    """decay_confidence returns 0 when no facts are old enough to decay."""
    store = KnowledgeStore(temp_db_path)
    store.set_embed_function(mock_embed)
    await store.initialize()

    await store.store_fact("pref", "recent", "value", 0.9, source="auto")

    decayed = await store.decay_confidence(
        decay_rate=0.1, min_confidence=0.3
    )
    await store.close()

    assert decayed == 0


@pytest.mark.asyncio
async def test_cleanup_expired_empty_store_returns_zero(
    temp_db_path, mock_embed
):
    """cleanup_expired returns 0 when store is empty."""
    store = KnowledgeStore(temp_db_path)
    store.set_embed_function(mock_embed)
    await store.initialize()

    deleted = await store.cleanup_expired()
    await store.close()

    assert deleted == 0


@pytest.mark.asyncio
async def test_get_due_reminders_empty_when_none_due(temp_db_path):
    """get_due_reminders returns [] when no reminders are past expires_at."""
    from datetime import datetime, timedelta

    store = KnowledgeStore(temp_db_path)
    await store.initialize()

    future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    await store.store_fact(
        "reminder", "future_rem", "tomorrow", expires_at=future
    )

    due = await store.get_due_reminders(limit=20)
    await store.close()

    assert due == []


@pytest.mark.asyncio
async def test_correct_fact_returns_updated_message(
    temp_db_path, mock_embed
):
    """correct_fact returns message containing 'Updated' and new value."""
    store = KnowledgeStore(temp_db_path)
    store.set_embed_function(mock_embed)
    await store.initialize()

    await store.store_fact("pref", "key", "old_value", 0.8)
    result = await store.correct_fact("pref", "key", "new_value", 1.0)
    await store.close()

    assert "Updated" in result
    assert "new_value" in result


@pytest.mark.asyncio
async def test_knowledge_store_with_shared_connection(
    temp_db_path, mock_embed
):
    """KnowledgeStore accepts SharedDbConnection; close() does not close shared conn.

    When initialized with SharedDbConnection, _own_connection=False so close()
    does not call _shared.close(). Another store using the same connection keeps working.
    """
    from memory.db_manager import SharedDbConnection

    shared = SharedDbConnection(temp_db_path)
    await shared.initialize()

    store1 = KnowledgeStore(shared)
    store2 = KnowledgeStore(shared)
    store1.set_embed_function(mock_embed)
    store2.set_embed_function(mock_embed)
    await store1.initialize()
    await store2.initialize()

    await store1.store_fact("pref", "shared_key", "shared value", 1.0)
    await store1.close()

    facts = await store2.get_all_facts()
    assert len(facts) == 1
    assert facts[0]["key"] == "shared_key"
    await store2.close()
    await shared.close()


@pytest.mark.asyncio
async def test_delete_fact_by_id_does_not_affect_other_facts(
    temp_db_path, mock_embed
):
    """delete_fact_by_id removes only the specified fact."""
    store = KnowledgeStore(temp_db_path)
    store.set_embed_function(mock_embed)
    await store.initialize()

    id1 = await store.store_fact("pref", "keep1", "v1", 1.0)
    id2 = await store.store_fact("pref", "delete_me", "v2", 1.0)
    id3 = await store.store_fact("pref", "keep2", "v3", 1.0)

    deleted = await store.delete_fact_by_id(id2)
    assert deleted is True

    facts = await store.get_all_facts()
    keys = {f["key"] for f in facts}
    assert keys == {"keep1", "keep2"}
    await store.close()


# ── BUG-14 / P3-GAP-2: Additional coverage for _check_duplicate,
#    search_semantic fallback, edge cases, initialization ──


@pytest.mark.asyncio
async def test_store_fact_semantic_dedup_updates_existing_with_new_fact(
    temp_db_path, mock_embed
):
    """_check_duplicate: semantically duplicate fact updates existing with new key/value.

    Regression for Bug 76: When storing a NEW fact (different key) in same category
    with semantically similar value (embedding sim >= 0.92), the existing fact
    adopts the incoming fact's key, value, confidence. No duplicate row inserted.
    """
    store = KnowledgeStore(temp_db_path)
    store.set_embed_function(mock_embed)
    await store.initialize()

    id1 = await store.store_fact(
        "preference", "morning_drink", "likes espresso", 0.9
    )
    id2 = await store.store_fact(
        "preference", "coffee_choice", "prefers espresso shots", 0.8
    )

    assert id1 == id2
    facts = await store.get_all_facts(category="preference")
    assert len(facts) == 1
    assert facts[0]["key"] == "coffee_choice"
    assert facts[0]["value"] == "prefers espresso shots"
    assert facts[0]["confidence"] == 0.8
    await store.close()


@pytest.mark.asyncio
async def test_search_semantic_fallback_when_embed_raises(temp_db_path):
    """search_semantic falls back to keyword when embed_fn raises."""
    store = KnowledgeStore(temp_db_path)
    await store.initialize()

    await store.store_fact("pref", "coffee", "dark roast", 1.0)

    async def failing_embed(_text):
        raise RuntimeError("API unavailable")

    store.set_embed_function(failing_embed)
    results = await store.search_semantic("coffee", limit=5)
    assert len(results) == 1
    assert results[0]["key"] == "coffee"
    assert "similarity" not in results[0]
    await store.close()


@pytest.mark.asyncio
async def test_search_keyword_empty_store_returns_empty(
    temp_db_path, mock_embed
):
    """search_keyword returns [] when no facts match."""
    store = KnowledgeStore(temp_db_path)
    store.set_embed_function(mock_embed)
    await store.initialize()

    await store.store_fact("pref", "coffee", "dark roast", 1.0)
    results = await store.search_keyword("nonexistent_term_xyz", limit=10)
    assert results == []
    await store.close()


@pytest.mark.asyncio
async def test_get_stale_facts_empty_when_all_recent(
    temp_db_path, mock_embed
):
    """get_stale_facts returns [] when all facts were mentioned recently."""
    store = KnowledgeStore(temp_db_path)
    store.set_embed_function(mock_embed)
    await store.initialize()

    await store.store_fact("pref", "recent1", "v1", 1.0)
    await store.store_fact("pref", "recent2", "v2", 1.0)

    stale = await store.get_stale_facts(days=90, limit=10)
    assert stale == []
    await store.close()


@pytest.mark.asyncio
async def test_initialize_idempotent(temp_db_path, mock_embed):
    """initialize() can be called multiple times without error."""
    store = KnowledgeStore(temp_db_path)
    store.set_embed_function(mock_embed)

    await store.initialize()
    await store.initialize()
    await store.store_fact("pref", "key", "value", 1.0)
    await store.initialize()

    facts = await store.get_all_facts()
    assert len(facts) == 1
    await store.close()


@pytest.mark.asyncio
async def test_close_idempotent(temp_db_path, mock_embed):
    """close() can be called multiple times without error."""
    store = KnowledgeStore(temp_db_path)
    store.set_embed_function(mock_embed)
    await store.initialize()

    await store.close()
    await store.close()


@pytest.mark.asyncio
async def test_cosine_similarity_zero_vectors(temp_db_path, mock_embed):
    """search_semantic handles edge case when query embedding has zero norm.

    When _embed_text returns a zero vector, search_semantic falls back to
    search_keyword. Verify behavior via a mock that returns zeros.
    """

    async def zero_embed(_text):
        return [0.0, 0.0, 0.0, 0.0]

    store = KnowledgeStore(temp_db_path)
    store.set_embed_function(zero_embed)
    await store.initialize()

    await store.store_fact("fact", "test_key", "test value", 1.0)
    results = await store.search_semantic("test", limit=5)

    assert len(results) >= 1
    assert "similarity" not in results[0]
    await store.close()


@pytest.mark.asyncio
async def test_store_fact_without_embed_stores_with_null_embedding(
    temp_db_path,
):
    """store_fact without embed_fn stores fact with NULL embedding."""
    store = KnowledgeStore(temp_db_path)
    await store.initialize()

    fact_id = await store.store_fact("pref", "no_embed", "value", 1.0)
    assert fact_id > 0

    async with store._shared.lock:
        cursor = await store._shared.connection.execute(
            "SELECT embedding FROM facts WHERE id = ?", (fact_id,)
        )
        row = await cursor.fetchone()
    assert row is not None
    assert row[0] is None
    await store.close()


@pytest.mark.asyncio
async def test_get_contradictory_facts_respects_similarity_threshold(
    temp_db_path, mock_embed
):
    """get_contradictory_facts only returns pairs above similarity_threshold."""
    store = KnowledgeStore(temp_db_path)
    store.set_embed_function(mock_embed)
    await store.initialize()

    await store.store_fact("pref", "a", "value one", 1.0)
    await store.store_fact("pref", "b", "value two", 1.0)

    contrad_high = await store.get_contradictory_facts(
        similarity_threshold=0.5, limit=200
    )
    contrad_strict = await store.get_contradictory_facts(
        similarity_threshold=0.999, limit=200
    )
    await store.close()

    assert len(contrad_high) >= len(contrad_strict)


@pytest.mark.asyncio
async def test_set_embed_function_fallback_then_semantic(
    temp_db_path, mock_embed
):
    """Without embed_fn, search_semantic falls back to keyword (no similarity key).
    After setting embed_fn and storing a NEW fact (with embedding), semantic search
    returns similarity scores."""
    store = KnowledgeStore(temp_db_path)
    await store.initialize()

    await store.store_fact("pref", "coffee", "dark roast", 1.0)

    results_no_embed = await store.search_semantic("coffee", limit=5)
    assert len(results_no_embed) == 1
    assert "similarity" not in results_no_embed[0]

    store.set_embed_function(mock_embed)
    # Store a new fact WITH embedding so semantic search can find it
    await store.store_fact("pref", "espresso", "double shot", 1.0)
    results_with_embed = await store.search_semantic("espresso", limit=5)
    assert len(results_with_embed) >= 1
    assert "similarity" in results_with_embed[0]
    await store.close()
