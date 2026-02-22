# Sixth-Pass Bug Fix Prompt — BUG-92 through BUG-103

> **Date:** 2026-02-22
> **Test baseline:** 642 passed, 1 failed (test_settings_defaults — stale assertion, user-fixed), 3 skipped
> **Scan scope:** All Python files across brain/, memory/, tools/, tests/
> **Previous bugs:** BUG-1 through BUG-91 from scans 1–5 are documented in BUG_FIX_PROMPT_3/4/5.

---

## Instructions for Fixing Agent

**Rules:**
1. Fix each bug in the order listed (HIGH first, then MEDIUM, LOW).
2. After each fix, run `PYTHONPATH=apex_brain python3 -m pytest apex_brain/tests/ -x -q` to ensure no regressions.
3. Write or update tests for every fix where applicable.
4. Do NOT modify `.env` or any credentials.
5. Keep fixes minimal — don't refactor surrounding code.

---

## HIGH SEVERITY BUGS

### BUG-92: `conversation.py:224-227` — MCP bridge `get_openai_tool_definitions()` unguarded — crashes entire pipeline

**File:** `apex_brain/brain/conversation.py`, lines 224-227

**Problem:** When building tool definitions for the LLM call, the MCP bridge method is called without any error handling:

```python
if self.mcp_bridge and self.mcp_bridge.connected:
    tool_defs = (
        tool_defs + self.mcp_bridge.get_openai_tool_definitions()
    )
```

If the MCP bridge reports `.connected = True` but the underlying session has gone stale (network blip, MCP server restart), `get_openai_tool_definitions()` can raise any exception. Since this is inside `handle()` with no try/except, the **entire conversation pipeline crashes** and the user gets an unhandled error. Additionally, if the method returns a non-list type (e.g., `None`), the `+` operator raises `TypeError`.

**Fix:**
```python
if self.mcp_bridge and self.mcp_bridge.connected:
    try:
        mcp_tools = self.mcp_bridge.get_openai_tool_definitions()
        if isinstance(mcp_tools, list):
            tool_defs = tool_defs + mcp_tools
    except Exception as e:
        logger.warning("Failed to get MCP tool definitions: %s", e)
```

**Test:** Mock `mcp_bridge.get_openai_tool_definitions` to raise `RuntimeError` — verify `handle()` still returns a response.

---

### BUG-93: `knowledge_store.py:308-365` — `correct_fact()` has no transaction — race condition on concurrent corrections

**File:** `apex_brain/memory/knowledge_store.py`, lines 308-365

**Problem:** `correct_fact()` performs a SELECT (line 321) then an UPDATE (line 338) with no transaction protection. Between the SELECT and UPDATE, a concurrent async task could:
1. Delete the fact → UPDATE silently matches 0 rows, but the function returns "Updated" (false claim)
2. Insert a duplicate → the SELECT misses the new row, leading to a second INSERT via `store_fact()` at line 358

Compare with `store_fact()` at line 213 which correctly uses `BEGIN IMMEDIATE`. The "force-update" contract of `correct_fact()` is broken without a transaction.

**Fix:** Wrap in explicit transaction:
```python
async def correct_fact(self, category, key, new_value, confidence=1.0):
    now = datetime.now(timezone.utc).isoformat()
    await self._db.execute("BEGIN IMMEDIATE")
    try:
        cursor = await self._db.execute(
            "SELECT id FROM facts WHERE category = ? AND key = ?",
            (category, key),
        )
        existing = await cursor.fetchone()
        if existing:
            fact_id = existing[0]
            embedding_blob = None
            embedding_vec = await self._embed_text(f"{key}: {new_value}")
            if embedding_vec is not None:
                embedding_blob = _serialize_embedding(embedding_vec.tolist())
            await self._db.execute(
                "UPDATE facts SET value = ?, confidence = ?, "
                "embedding = ?, updated_at = ?, last_mentioned_at = ? "
                "WHERE id = ?",
                (new_value, confidence, embedding_blob, now, now, fact_id),
            )
            await self._db.commit()
            return f"Updated: {key} → {new_value}"
        await self._db.commit()
    except Exception:
        await self._db.execute("ROLLBACK")
        raise
    # No existing fact → store as new (store_fact has its own transaction)
    await self.store_fact(
        category=category, key=key, value=new_value,
        confidence=confidence, source="user",
    )
    return f"Updated: {key} → {new_value}"
```

**Test:** Call `correct_fact` on a key that exists, then verify the update succeeded atomically.

---

### BUG-94: `server.py:89` — `_embed_text()` crashes with IndexError if embedding API returns empty data

**File:** `apex_brain/brain/server.py`, line 89

**Problem:** The server-level embed function accesses `response.data[0]["embedding"]` without checking if `response.data` is non-empty:

```python
async def _embed_text(text: str) -> list[float] | None:
    try:
        response = await litellm.aembedding(
            model=settings.embedding_model,
            input=[text],
        )
        return response.data[0]["embedding"]  # IndexError if data is empty
    except Exception as e:
        logger.error("Embedding error: %s", e)
        return None
```

If the embedding API returns an empty `data` list (rate limit, malformed input, model error), `response.data[0]` raises `IndexError`. While the broad `except Exception` catches it and returns `None`, the error message is misleading ("Embedding error: list index out of range") and doesn't indicate the real cause.

Additionally, `response.data[0]` may be a Pydantic object (LiteLLM's `Embedding` class), not a dict. In that case, `["embedding"]` raises `TypeError`. The correct accessor is `response.data[0]["embedding"]` for dicts OR `response.data[0].embedding` for objects.

**Fix:**
```python
async def _embed_text(text: str) -> list[float] | None:
    try:
        response = await litellm.aembedding(
            model=settings.embedding_model,
            input=[text],
        )
        if not response.data:
            logger.warning("Embedding API returned empty data for text: %s", text[:50])
            return None
        item = response.data[0]
        if isinstance(item, dict):
            return item.get("embedding")
        return getattr(item, "embedding", None)
    except Exception as e:
        logger.error("Embedding error: %s", e)
        return None
```

**Test:** Mock `litellm.aembedding` to return response with empty `data` list — verify `None` returned, no crash.

---

## MEDIUM SEVERITY BUGS

### BUG-95: `routine_store.py:52-86` — TOCTOU race in `save_routine()` — SELECT then UPDATE/INSERT without transaction

**File:** `apex_brain/memory/routine_store.py`, lines 52-86

**Problem:** `save_routine()` checks if a routine exists with SELECT (line 64), then either UPDATEs (line 71) or INSERTs (line 79). No transaction protects this sequence. Two concurrent calls with the same name can both pass the SELECT, both attempt INSERT, and one hits a UNIQUE constraint violation.

The table has `UNIQUE COLLATE NOCASE` on `name`, so the second INSERT will raise `IntegrityError` rather than creating a duplicate — but this exception propagates unhandled and crashes the caller.

**Fix:** Use INSERT OR REPLACE (SQLite upsert) or wrap in `BEGIN IMMEDIATE`:
```python
async def save_routine(self, name, steps, trigger="", source="user"):
    now = datetime.now(timezone.utc).isoformat()
    steps_json = json.dumps(steps)
    clean_name = name.lower().strip()

    await self._db.execute("BEGIN IMMEDIATE")
    try:
        cursor = await self._db.execute(
            "SELECT id FROM routines WHERE name = ?", (clean_name,)
        )
        existing = await cursor.fetchone()
        if existing:
            await self._db.execute(
                "UPDATE routines SET steps = ?, trigger_hint = ?, "
                "updated_at = ?, source = ? WHERE id = ?",
                (steps_json, trigger, now, source, existing[0]),
            )
            await self._db.commit()
            return existing[0]
        cursor = await self._db.execute(
            "INSERT INTO routines "
            "(name, steps, trigger_hint, created_at, updated_at, source) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (clean_name, steps_json, trigger, now, now, source),
        )
        await self._db.commit()
        return cursor.lastrowid
    except Exception:
        try:
            await self._db.execute("ROLLBACK")
        except Exception:
            pass
        raise
```

**Test:** Call `save_routine()` twice concurrently with the same name — verify no crash, one upsert succeeds.

---

### BUG-96: `event_subscriber.py:176-194` — Events with empty `entity_id` still processed — wastes LLM calls

**File:** `apex_brain/brain/event_subscriber.py`, lines 176-194

**Problem:** When a `state_changed` event arrives with missing or empty `entity_id`, the code defaults to `""`:

```python
entity_id = event_data.get("entity_id", "")
```

This empty entity_id passes through to `WebhookEvent` construction, the decision engine, and potentially triggers an LLM conversation call. The decision engine's `_hard_filter()` does `entity.split(".")[0]` on empty string, getting `""`, which is NOT in `_IGNORED_DOMAINS`, so the event passes the filter. The resulting message to the AI is nonsensical: `"[EVENT] (..) changed from '' to ''."` — wasting an LLM API call.

**Fix:** Add early validation:
```python
async def _handle_event(self, event: dict) -> None:
    event_data = event.get("data", {})
    entity_id = event_data.get("entity_id", "")
    if not entity_id:
        return  # Skip events with missing entity_id
```

**Test:** Send event with `entity_id: ""` — verify `_handle_event` returns immediately without calling decision engine.

---

### BUG-97: `weather.py:105-111` — Forecast `templow=None` from HA displays "/None" in output

**File:** `apex_brain/tools/weather.py`, lines 105-111

**Problem:** When HA returns a forecast item with `templow: null` (common for hourly forecasts), `f.get("templow", "")` returns `None` (because the key exists with value `null`), not `""`. The guard on line 110 checks `if lo != "":` — since `None != ""` is True, it enters the branch and produces:

```
  2026-02-22 14:00: Partly Cloudy, 72/None°F
```

This is a display bug visible to users.

**Fix:**
```python
lo = f.get("templow")
# ...
if lo is not None and lo != "":
    entry += f"/{lo}"
```

**Test:** Mock HA forecast response with `templow: null` — verify output doesn't contain "None".

---

### BUG-98: `scheduler.py:132` — Task list iteration crashes if callback calls `register()`

**File:** `apex_brain/brain/scheduler.py`, lines 132-137

**Problem:** The main loop iterates `self._tasks` directly:

```python
for task in self._tasks:
    if task.enabled and now >= task.next_run:
        task.next_run = now + task.interval_seconds
        t = asyncio.create_task(self._safe_run(task))
```

If a scheduled task's callback calls `scheduler.register()` (which appends to `self._tasks`), the iteration will raise `RuntimeError: list changed size during iteration`. While current built-in tasks don't call `register()`, the public API allows custom tasks that could.

Since asyncio is single-threaded, the mutation can only happen if `register()` is called from synchronous code within the iteration (before the `await asyncio.sleep`). The risk is LOW in practice but the crash is catastrophic — the scheduler loop dies permanently.

**Fix:** Iterate a copy:
```python
for task in list(self._tasks):
    if task.enabled and now >= task.next_run:
        ...
```

**Test:** Register a callback that itself calls `scheduler.register()` — verify no `RuntimeError`.

---

### BUG-99: `knowledge_store.py:629-644` — `delete_fact()` has TOCTOU race — can return True when nothing was deleted

**File:** `apex_brain/memory/knowledge_store.py`, lines 629-644

**Problem:** `delete_fact()` SELECTs the fact ID first, then DELETEs by ID. Between the SELECT and DELETE, another async task could delete the same fact. The DELETE then matches 0 rows, but the function still returns `True`, falsely claiming success.

**Fix:** Use a single DELETE and check `rowcount`:
```python
async def delete_fact(self, key: str) -> bool:
    cursor = await self._db.execute(
        "DELETE FROM facts WHERE key = ?", (key,)
    )
    await self._db.commit()
    return cursor.rowcount > 0
```

**Test:** Delete a fact, then delete it again — verify second call returns `False`.

---

### BUG-100: `fact_extractor.py:127-133` — Non-numeric `confidence` from LLM causes `TypeError` in `min()`/`max()`

**File:** `apex_brain/memory/fact_extractor.py`, lines 127-133

**Problem:** The LLM is asked to return a JSON confidence value as a float, but there's no validation:

```python
confidence = max(
    0.0,
    min(
        1.0,
        fact.get("confidence", 0.7),
    ),
)
```

If the LLM returns `"confidence": "high"` or `"confidence": [0.8]` or `"confidence": null`, `min(1.0, "high")` raises `TypeError: '<' not supported between instances of 'str' and 'float'`. This crashes the entire fact extraction, losing ALL extracted facts from that conversation turn — not just the malformed one.

**Fix:**
```python
confidence_raw = fact.get("confidence", 0.7)
try:
    confidence = float(confidence_raw)
except (TypeError, ValueError):
    confidence = 0.7
confidence = max(0.0, min(1.0, confidence))
```

**Test:** Feed a fact dict with `"confidence": "high"` — verify no crash, defaults to 0.7.

---

### BUG-101: `knowledge_store.py:410-417` — `decay_confidence()` applies wrong timezone conversion for non-UTC timestamps

**File:** `apex_brain/memory/knowledge_store.py`, lines 410-417

**Problem:** When `last_mentioned_at` has a non-UTC timezone (e.g., `2026-02-20T10:00:00+05:00`), the code uses `replace(tzinfo=timezone.utc)` which only applies to naive timestamps. For timezone-aware non-UTC timestamps, no conversion is performed. The subtraction `now - last_mentioned` then works correctly (Python handles timezone-aware arithmetic), BUT the `replace` branch for naive timestamps **overwrites** the timezone marker instead of converting:

```python
if last_mentioned.tzinfo is None:
    last_mentioned = last_mentioned.replace(tzinfo=timezone.utc)
```

If timestamps were originally stored in local time without tzinfo (which happens when `context_builder` or `calendar_tool` strip timezones), `replace(tzinfo=UTC)` treats a local-time value as UTC, causing age calculation to be off by the UTC offset (e.g., ±5-8 hours). For the 30-day decay threshold this is negligible, but it's still logically incorrect.

**Fix:**
```python
if last_mentioned.tzinfo is None:
    last_mentioned = last_mentioned.replace(tzinfo=timezone.utc)
else:
    last_mentioned = last_mentioned.astimezone(timezone.utc)
```

**Test:** Store a fact with a non-UTC timezone string, call `decay_confidence()` — verify correct age calculation.

---

## LOW SEVERITY BUGS

### BUG-102: `conversation.py:240-245` — Background fact extraction task spawned on every message, even with empty history

**File:** `apex_brain/brain/conversation.py`, lines 240-245

**Problem:** After every `handle()` call, a background task is spawned for fact extraction regardless of whether there's anything to extract:

```python
recent = await self.conversation_store.get_recent(n=4, session_id=session_id)
task = asyncio.create_task(self._safe_extract_facts(recent))
self._background_tasks.add(task)
task.add_done_callback(self._background_tasks.discard)
```

When `recent` is an empty list (e.g., first message in a new session, or conversation store failure), the fact extractor is still invoked, makes an LLM call with empty context, and returns nothing useful. Under rapid message bursts, this spawns many pointless asyncio tasks.

**Fix:**
```python
recent = await self.conversation_store.get_recent(n=4, session_id=session_id)
if recent:
    task = asyncio.create_task(self._safe_extract_facts(recent))
    self._background_tasks.add(task)
    task.add_done_callback(self._background_tasks.discard)
```

**Test:** Call `handle()` with empty conversation history — verify no background task spawned.

---

### BUG-103: `server.py:346` — Rate limiter uses "unknown" for all proxy-less clients — shared rate limit

**File:** `apex_brain/brain/server.py`, line 346

**Problem:** When `request.client` is `None` (happens behind certain reverse proxies or in test scenarios), all requests share the key `"chat:unknown"`:

```python
client_ip = request.client.host if request.client else "unknown"
key = f"chat:{client_ip}"
```

If multiple users are behind a load balancer that doesn't set `request.client`, they all share one rate limit bucket. 30 requests from ANY user exhausts the limit for ALL users.

**Fix:** Fall back to a request header if available:
```python
if request.client:
    client_ip = request.client.host
else:
    client_ip = (
        request.headers.get("x-real-ip")
        or request.headers.get("x-forwarded-for", "").split(",")[0].strip()
        or "unknown"
    )
```

**Test:** Send request with `client=None` but `X-Real-IP` header — verify rate limit uses the header IP.

---

## TEST ISSUES

### TEST-1: `conftest.py:32-38` — `mock_embed` returns identical vectors for all inputs — semantic search tests meaningless

**File:** `apex_brain/tests/conftest.py`, lines 32-38

**Problem:** The shared `mock_embed` fixture returns `[0.1, 0.2, 0.3, 0.4]` regardless of input text. Cosine similarity between any two facts is always 1.0. Semantic search ranking tests pass but validate nothing — every fact appears equally relevant.

**Fix:** Use a hash-based mock that produces distinct vectors:
```python
@pytest.fixture
def mock_embed():
    async def _embed(text: str) -> list[float]:
        import hashlib
        h = hashlib.md5(text.encode()).digest()
        return [b / 255.0 for b in h[:4]]
    return _embed
```

**Impact:** May cause some existing tests to need updated assertions if they depend on identical embeddings.

---

### TEST-2: `test_scheduler.py` — No test for `register()` called during `_run_loop()` iteration

**Problem:** No test verifies what happens when a task callback calls `scheduler.register()`. This is the scenario for BUG-98 and is completely untested.

**Fix:** Add test: register a task whose callback itself calls `scheduler.register("dynamic_task", ...)`, then verify no `RuntimeError` and the new task is registered.

---

### TEST-3: `test_fact_extractor.py:88-99` — Missing boundary test for minimum conversation length

**Problem:** The test checks that a 2-character conversation ("Hi") skips extraction, but doesn't test the exact boundary (19 chars → skip, 20 chars → extract). Off-by-one errors in the threshold are undetected.

**Fix:** Add boundary tests at exactly the threshold length.

---

### TEST-4: Multiple tool modules test only happy paths — no error response handling

**Problem:** Tests for `list_automations`, `list_scenes`, `get_energy_summary`, `get_presence`, and 8+ other tools never test the case where `ha_request()` returns an error dict (`{"error": "..."}`) instead of a list. The code does `[s for s in states if s["entity_id"]...]` on the error dict, iterating dict keys and crashing with `TypeError`.

This is related to BUG-77 from PROMPT_3 (`ha_request` error returns dict, callers iterate as list), but the test gap is distinct.

**Fix:** Add tests: mock `ha_request` to return `{"error": "timeout"}` — verify graceful error message, not crash.

---

## Summary

| Severity | Count | Bug IDs |
|----------|-------|---------|
| HIGH | 3 | BUG-92, BUG-93, BUG-94 |
| MEDIUM | 7 | BUG-95 through BUG-101 |
| LOW | 2 | BUG-102, BUG-103 |
| Test Issues | 4 | TEST-1 through TEST-4 |
| **Total** | **12 bugs + 4 test issues** | |

---

## Deduplicated Against Earlier Prompts

The following were found in the scan but are already documented:
- Server shutdown None guards on stores → BUG-63 (PROMPT_3), BUG-59 (PROMPT_4)
- Global declaration missing scheduler/event_subscriber → BUG-60 (PROMPT_3)
- ChatRequest no max_length → BUG-63 (PROMPT_4)
- Session ID validation on /v1/chat/completions → BUG-70 (PROMPT_4)
- `_today_date()` naive datetime → BUG-65 (PROMPT_4)
- Calendar timezone stripping → BUG-70 (PROMPT_3)
- `model_dump()` provider fields → BUG-76 (PROMPT_3)
- `ha_request` error dict iterated as list → BUG-77 (PROMPT_3)
- Action trace eviction KeyError → BUG-84 (PROMPT_3)
- Unreachable LLM retry code → BUG-82 (PROMPT_5)
- `item.get()` on non-dict in `_embed_text` → BUG-78 (PROMPT_5)
- `decay_confidence` individual UPDATEs without transaction → BUG-88 (PROMPT_3)
- Config string concatenation → BUG-87 (PROMPT_5)
- MCP disconnect doesn't clear tools → BUG-82 (PROMPT_3)
- Store `_db` None checks → BUG-67 (PROMPT_3)
- `search_semantic` unbounded query → BUG-74 (PROMPT_3)
- Event subscriber session leak on double start → BUG-79 (PROMPT_5)

## False Positives Rejected

1. **"wait_tool `float('inf')` hangs"** — FALSE. `min(float('inf'), 300)` = 300. The clamp works correctly.
2. **"calendar_tool None start_dt comparison crashes"** — FALSE. Line 170 checks `if start_dt is not None:` before the comparison. The guard is correct.
3. **"automation.py `_normalize_keys(None)` crashes"** — FALSE in practice. All call sites use `conditions or []` to protect against None input.
4. **"decision_engine `_hard_filter` crashes on dict input"** — FALSE. All callers pass `WebhookEvent` (Pydantic model) which always has the required attributes.

---

## Recommended Fix Order

### Batch 1 — Data Integrity & Pipeline Stability
1. BUG-92: MCP bridge unguarded tool definitions
2. BUG-93: correct_fact missing transaction
3. BUG-94: _embed_text empty data crash
4. BUG-100: Non-numeric confidence crash

### Batch 2 — Correctness
5. BUG-95: routine_store TOCTOU race
6. BUG-96: Empty entity_id events processed
7. BUG-97: Weather forecast "/None" display
8. BUG-99: delete_fact TOCTOU
9. BUG-101: Timezone conversion in decay

### Batch 3 — Efficiency & Hardening
10. BUG-98: Scheduler list mutation crash
11. BUG-102: Empty background task spawning
12. BUG-103: Rate limiter shared key

### Batch 4 — Test Quality
13. TEST-1: mock_embed identical vectors
14. TEST-2: Scheduler register-during-iteration test
15. TEST-3: Fact extractor boundary test
16. TEST-4: Error response handling tests

---

## Verification Checklist

After all fixes:
1. `PYTHONPATH=apex_brain python3 -m pytest apex_brain/tests/ -q` — all tests pass
2. `python3 -m ruff check apex_brain/` — no lint errors
3. `python3 -m ruff format --check apex_brain/` — formatting OK
4. No secrets or tokens in any modified files
5. Each fix is minimal and focused — no surrounding refactors
