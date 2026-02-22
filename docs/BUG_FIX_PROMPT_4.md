# Fourth-Pass Bug Fix Prompt — BUG-59 through BUG-76

## Instructions for Fixing Agent

You are fixing 18 additional bugs found in a fourth deep scan of the Apex Brain project. These cover cross-component interactions, concurrency, data flow edge cases, smart_home logic gaps, and test quality issues. Separate from BUG-1–58 in earlier prompts.

**Rules:**
1. Fix each bug in the order listed (CRITICAL first, then HIGH, MEDIUM, LOW).
2. After each fix, run `python3 -m pytest apex_brain/tests/ -x -q` to ensure no regressions.
3. Write or update tests for every fix where applicable.
4. Do NOT modify `.env` or any credentials.
5. Keep fixes minimal — don't refactor surrounding code.

---

## CRITICAL

### BUG-59: `server.py:266-268` — Shutdown crashes if stores are None

**Problem:** The shutdown section calls `.close()` on `routine_store`, `convo_store`, and `knowledge_store` WITHOUT null-checks:
```python
await routine_store.close()     # No guard — can be None
await convo_store.close()       # No guard — can be None
await knowledge_store.close()   # No guard — can be None
```

Compare with the exception handler at lines 253-258 which properly uses `if routine_store:` guards. If startup partially fails (e.g., `knowledge_store.initialize()` raises after `convo_store` succeeds), the lifespan re-raises, then on shutdown these calls crash with `AttributeError: 'NoneType' object has no attribute 'close'`, masking the original error.

**File:** `apex_brain/brain/server.py`, lines 266-268

**Fix:** Add null-checks matching the exception handler pattern:
```python
if routine_store:
    await routine_store.close()
if convo_store:
    await convo_store.close()
if knowledge_store:
    await knowledge_store.close()
```

**Test:** Mock `knowledge_store.initialize()` to raise — verify shutdown doesn't crash with `AttributeError`.

---

### BUG-60: `conversation.py` — No per-session locking; concurrent requests corrupt conversation history

**Problem:** `conversation.handle()` has no synchronization. If two HTTP requests arrive simultaneously with the same `session_id`:
1. Both call `save_turn("user", ...)` — interleaved inserts
2. Both call `context_builder.build()` — each sees partial history
3. Both run `_ai_tool_loop()` — both build action traces for the same session_id key
4. Both call `save_turn("assistant", ...)` — interleaved responses

Result: Conversation history has duplicated user turns, AI sees garbled context, action traces overwrite each other.

**File:** `apex_brain/brain/conversation.py`, `handle()` method (lines 141-196)

**Fix:** Add per-session async locks:
```python
def __init__(self, ...):
    # ... existing code ...
    self._session_locks: dict[str, asyncio.Lock] = {}

async def handle(self, user_message: str, session_id: str = "default") -> str:
    # Get or create per-session lock
    if session_id not in self._session_locks:
        self._session_locks[session_id] = asyncio.Lock()
    async with self._session_locks[session_id]:
        # ... existing handle() body ...
```

Add eviction for session locks to prevent unbounded growth (same pattern as `_action_traces`).

**Test:** Send two concurrent `handle()` calls with the same session_id — verify they serialize (second waits for first).

---

## HIGH

### BUG-61: `event_subscriber.py:199` — Events processed sequentially; slow handler blocks all events

**Problem:** `_handle_event()` is called with `await` inside the WebSocket message loop (line 164). If `conversation.handle()` takes 10-30 seconds (LLM + tool calls), ALL subsequent events queue up. During a burst of 50 events, the WebSocket buffer fills, backpressure delays event delivery, and the system falls behind real-time.

**File:** `apex_brain/brain/event_subscriber.py`, line 164 (`await self._handle_event(data.get("event", {}))`)

**Fix:** Use `asyncio.create_task()` with a semaphore to process events concurrently with backpressure:
```python
def __init__(self, ...):
    # ... existing code ...
    self._event_semaphore = asyncio.Semaphore(5)  # max 5 concurrent events
    self._event_tasks: set = set()

async def _handle_event(self, event: dict) -> None:
    async with self._event_semaphore:
        # ... existing _handle_event body ...
```

And in the message loop, replace `await self._handle_event(...)` with:
```python
task = asyncio.create_task(self._handle_event(data.get("event", {})))
self._event_tasks.add(task)
task.add_done_callback(self._event_tasks.discard)
```

**Test:** Mock `conversation.handle` to sleep 5 seconds — send 10 events — verify they process concurrently (not sequentially).

---

### BUG-62: `ws_helpers.py:119-131` — Missing exception handlers for `ClientOSError` and generic `aiohttp.ClientError`

**Problem:** The `ws_command()` function catches `WSServerHandshakeError`, `ClientConnectorError`, and `asyncio.TimeoutError`, but misses:
- `aiohttp.ClientOSError` (broken pipe, connection reset during `send_json`)
- `aiohttp.ClientError` (generic aiohttp base exception)
- `OSError` / `ConnectionResetError` (socket-level failures)

These propagate as unexpected exceptions to `configure()`, which only catches `RuntimeError`, `ConnectionError`, `PermissionError`, `TimeoutError` (BUG-42).

**File:** `apex_brain/tools/ws_helpers.py`, lines 119-131

**Fix:** Add a catch-all for aiohttp errors:
```python
except aiohttp.ClientError as e:
    raise ConnectionError(
        f"WebSocket communication error: {e}"
    ) from e
except OSError as e:
    raise ConnectionError(
        f"Network error during WebSocket command: {e}"
    ) from e
```

**Test:** Mock `ws.send_json` to raise `aiohttp.ClientOSError` — verify it's wrapped as `ConnectionError`.

---

### BUG-63: `server.py:386` — ChatRequest has no message size limit

**Problem:** The `ChatRequest` Pydantic model has `message: str` with no `max_length` constraint:
```python
class ChatRequest(BaseModel):
    message: str
    session_id: str = "default"
```

A malicious client can POST a 100MB message, which gets passed to `context_builder.build()`, embedded in the system prompt, and sent to litellm — causing memory exhaustion and massive API costs.

**File:** `apex_brain/brain/server.py`, line 386

**Fix:** Add Pydantic validation:
```python
class ChatRequest(BaseModel):
    message: str = Field(..., max_length=50000)  # 50KB max
    session_id: str = Field("default", max_length=100, pattern=r'^[a-zA-Z0-9_\-]+$')
```

Also validate session_id in the `/v1/chat/completions` endpoint (line 587-592).

**Test:** Send a 60KB message — verify 422 validation error.

---

### BUG-64: `datetime_tool.py:23` — Naive datetime fallback breaks timezone-aware comparisons

**Problem:** When `ZoneInfo` fails, the fallback uses `datetime.datetime.now()` (no timezone), producing a naive datetime. If this value is ever compared with timezone-aware datetimes elsewhere in the system, Python raises `TypeError: can't compare offset-naive and offset-aware datetimes`.

**File:** `apex_brain/tools/datetime_tool.py`, line 23

**Current code:**
```python
except Exception:
    now = datetime.datetime.now()  # NAIVE — no timezone
```

**Fix:**
```python
except Exception:
    now = datetime.datetime.now(tz=datetime.timezone.utc)
```

**Test:** Mock `ZoneInfo` to raise — verify returned string is valid and datetime is UTC.

---

### BUG-65: `calendar_tool.py:88` — `_today_date()` uses naive `datetime.now()` — wrong date near midnight

**Problem:**
```python
def _today_date() -> _dt.date:
    return _dt.datetime.now().date()
```

Uses server-local time (UTC in containers) instead of user's timezone. Near midnight, the "today" date can be wrong by ±1 day, causing calendar queries to show yesterday's or tomorrow's events.

**File:** `apex_brain/tools/calendar_tool.py`, line 88

**Fix:**
```python
def _today_date() -> _dt.date:
    try:
        from zoneinfo import ZoneInfo
        from brain.config import settings
        tz = ZoneInfo(settings.timezone)
    except Exception:
        tz = _dt.timezone.utc
    return _dt.datetime.now(tz=tz).date()
```

**Test:** Mock timezone to "America/New_York" at 11 PM UTC — verify correct local date.

---

### BUG-66: `system_prompt.py:20` — `asyncio.Lock()` created at module import time

**Problem:** `_schema_lock = asyncio.Lock()` runs at import time, which on Python < 3.10 requires a running event loop. In some testing or import contexts, this raises `RuntimeError: no running event loop` or creates a lock bound to the wrong loop.

**File:** `apex_brain/brain/system_prompt.py`, line 20

**Fix:** Use lazy initialization:
```python
_schema_lock: asyncio.Lock | None = None

async def fetch_service_schemas() -> str:
    global _schema_lock
    if _schema_lock is None:
        _schema_lock = asyncio.Lock()
    # ... rest unchanged
```

**Test:** Import the module in a non-async context — verify no crash.

---

## MEDIUM

### BUG-67: `smart_home.py:972-989` — Empty `area_name` matches first area

**Problem:** If `area_name=""` (empty string), `search = "".lower()` → `""`, and `"" in human_lower` is **always True** in Python. So `substring_match` is set to the first area in the list, and the function controls that random area.

**File:** `apex_brain/tools/smart_home.py`, lines 972-989

**Fix:** Add early validation:
```python
if not area_name or not area_name.strip():
    return "Error: area_name is required."
search = area_name.strip().lower()
```

**Test:** Call `control_area(area_name="", action="off")` — should return error, not control a random area.

---

### BUG-68: `conversation.py:401-404` — Loop exhaustion returns generic error without storing action trace

**Problem:** When the tool loop hits `max_iterations` (15), it returns a generic message without building/storing the action trace. The user has no explainability for what happened during those 15 iterations.

**File:** `apex_brain/brain/conversation.py`, lines 401-404

**Current code:**
```python
return (
    "I ran into a loop processing your request. "
    "Could you rephrase?"
)
```

**Fix:** Build and store the action trace before returning:
```python
facts_used = self._extract_facts_from_system(messages)
self._action_traces[session_id] = self._build_action_trace(
    tools_called, facts_used
)
logger.warning(
    "Tool loop exhausted (%d iterations). Tools called: %s",
    max_iterations, ", ".join(tools_called) or "none",
)
return (
    "I ran into a loop processing your request. "
    "Could you rephrase?"
)
```

**Test:** Mock LLM to always return tool calls — verify action trace is stored after loop exhaustion.

---

### BUG-69: `conversation.py:130` — `_background_tasks` never cleaned up on shutdown

**Problem:** `Conversation` class spawns background fact extraction tasks (`asyncio.create_task`) into `_background_tasks` set, but has NO `shutdown()` method. Unlike `Scheduler.stop()` and `EventSubscriber.stop()`, Conversation's background tasks are never cancelled or awaited on shutdown.

**File:** `apex_brain/brain/conversation.py`, line 130

**Fix:** Add a shutdown method:
```python
async def shutdown(self) -> None:
    """Cancel outstanding background fact extraction tasks."""
    for task in self._background_tasks:
        task.cancel()
    if self._background_tasks:
        await asyncio.gather(*self._background_tasks, return_exceptions=True)
    self._background_tasks.clear()
```

Call it from `server.py` shutdown (before closing stores):
```python
if conversation:
    await conversation.shutdown()
```

**Test:** Start a background task, call `shutdown()` — verify task is cancelled.

---

### BUG-70: `server.py:587-592` — Session ID from untrusted sources without validation

**Problem:** The `/v1/chat/completions` endpoint extracts session_id from multiple untrusted sources:
```python
session_id = (
    body.get("user")
    or body.get("conversation_id")
    or request.headers.get("x-session-id")
    or request.headers.get("x-conversation-id")
    or "default"
)
```

No length limit, no character validation. Arbitrarily long or specially-crafted session_ids bloat the conversation store and action traces dict.

**File:** `apex_brain/brain/server.py`, lines 587-592

**Fix:** Sanitize session_id:
```python
import re
raw_session = (
    body.get("user")
    or body.get("conversation_id")
    or request.headers.get("x-session-id")
    or request.headers.get("x-conversation-id")
    or "default"
)
# Sanitize: alphanumeric, underscore, hyphen, max 100 chars
session_id = re.sub(r'[^a-zA-Z0-9_\-]', '_', str(raw_session))[:100]
```

**Test:** Send session_id with special characters — verify they're sanitized.

---

### BUG-71: `decision_engine.py:70-82` — Cooldown check-then-set is not atomic

**Problem:** `_check_cooldown()` and `_set_cooldown()` are separate operations. Two concurrent event evaluations can both pass the cooldown check before either sets it:
1. Event A: `_check_cooldown("light.kitchen")` → True (no cooldown)
2. Event B: `_check_cooldown("light.kitchen")` → True (cooldown not set yet)
3. Event A: `_set_cooldown("light.kitchen")`
4. Event B: `_set_cooldown("light.kitchen")` — both processed

This bypasses the cooldown mechanism under concurrent event load.

**File:** `apex_brain/brain/decision_engine.py`, lines 70-82

**Fix:** Make check-and-set atomic:
```python
def _check_and_set_cooldown(self, key: str) -> bool:
    """Check cooldown and set it atomically. Returns True if allowed."""
    now = time.time()
    self._cleanup_cooldowns(now)
    last = self._cooldowns.get(key, 0)
    if now - last < self._cooldown_seconds:
        return False
    self._cooldowns[key] = now  # Set immediately
    return True
```

Note: Since asyncio is single-threaded and this is synchronous code, the real risk is if `evaluate()` is called from multiple coroutines. The check-set gap exists across `await` points, but since there are no `await`s between check and set in the current code, this is low risk in practice. Still, making it atomic is cleaner.

**Test:** Call `evaluate()` twice in rapid succession — verify only one passes cooldown.

---

### BUG-72: Test `test_event_subscriber.py:test_msg_id_resets_on_connect` — Tests wrong code path

**Problem:** The test mocks `_get_token()` to return `None`, which causes `_connect_and_listen()` to return early (sleep + return) WITHOUT resetting `_msg_id`. The assertion `assert subscriber._msg_id == 0` checks the initial state, not the reset behavior. The test never exercises the actual msg_id reset code path.

**File:** `apex_brain/tests/test_event_subscriber.py`, test `test_msg_id_resets_on_connect`

**Fix:** Mock `_get_token()` to return a valid token, and mock the WebSocket connection to succeed through the auth handshake, so the test actually exercises the `self._msg_id = 0` reset at the start of `_connect_and_listen()`.

**Test:** Rewrite test to verify msg_id is reset to 0 when a real connection attempt starts.

---

### BUG-73: Test `test_configure.py:test_webhook_session_blocked` — Doesn't verify action was NOT executed

**Problem:** The test checks that the error message contains "restricted" and "Tier 0", but never asserts that `ws_command` was NOT called. If the code has a permission bypass bug where it returns the error string but still executes the action, this test passes.

**File:** `apex_brain/tests/test_configure.py`, test `test_webhook_session_blocked`

**Fix:** Add assertion:
```python
assert "restricted" in result
assert "Tier 0" in result
mock_ws_command.assert_not_called()  # ADD THIS
```

**Test:** Self-validating.

---

## LOW

### BUG-74: `smart_home.py:control_cover` — Potential `UnboundLocalError` if action is empty string

**Problem:** If `action=""` and `position=None`, the code hits the `else` branch (line 746) and returns early. But if `action=""` and `position=None` and `tilt_position` is set, the code returns at line 746 before `result` is assigned, so `result` at line 774 would be `UnboundLocalError`. In practice, the schema requires `action` to be one of `["open", "close", "stop"]`, so empty string shouldn't happen via normal tool calls, but Python doesn't enforce enum constraints at runtime.

**File:** `apex_brain/tools/smart_home.py`, lines 737-774

**Fix:** Add early validation:
```python
if not action and position is None:
    return "Error: provide 'action' or 'position'."
```

**Test:** Call `control_cover(entity_id="x", action="", tilt_position=50)` — verify no `UnboundLocalError`.

---

### BUG-75: `routine_store.py:46-48` — Index created WITHOUT `COLLATE NOCASE` despite column having it

**Problem:** (Carried from BUG-56, re-confirmed.) The column definition uses `COLLATE NOCASE` but the index doesn't. SQLite may not use the index for case-insensitive lookups.

**File:** `apex_brain/memory/routine_store.py`, lines 46-48

**Fix:**
```sql
CREATE INDEX IF NOT EXISTS idx_routines_name
ON routines(name COLLATE NOCASE)
```

**Test:** N/A — performance improvement.

---

### BUG-76: `knowledge_store.py:201-206` — Facts stored without embeddings are invisible to semantic search

**Problem:** When `_embed_text()` fails (API down), `embedding_blob = None` and the fact is stored with `embedding = NULL`. Later, `search_semantic()` queries `WHERE embedding IS NOT NULL`, so these facts are **permanently invisible** to semantic search. No warning is logged about the missing embedding.

**File:** `apex_brain/memory/knowledge_store.py`, lines 201-206

**Fix:** Log a warning when embedding fails:
```python
embedding_vec = await self._embed_text(f"{key}: {value}")
if embedding_vec is not None:
    embedding_blob = _serialize_embedding(embedding_vec.tolist())
else:
    logger.warning(
        "Embedding failed for fact '%s' — fact will not appear in semantic search",
        key,
    )
```

Consider adding a background job to backfill missing embeddings when the API recovers.

**Test:** Mock `_embed_text` to return `None` — verify fact is stored and warning is logged.

---

## Summary

| Severity | Count | Bug IDs |
|----------|-------|---------|
| CRITICAL | 2 | BUG-59, 60 |
| HIGH | 6 | BUG-61, 62, 63, 64, 65, 66 |
| MEDIUM | 7 | BUG-67, 68, 69, 70, 71, 72, 73 |
| LOW | 3 | BUG-74, 75, 76 |
| **Total** | **18** | |

## False Positives Rejected

1. **"RateLimiter not thread-safe"** — FALSE CONCERN. FastAPI with uvicorn runs a single asyncio event loop in one thread. The RateLimiter is only accessed from async middleware which is cooperative (no preemption between `is_allowed()` steps). No lock needed.

2. **"asyncio.Lock() at import time crashes"** — PARTIALLY TRUE. On Python 3.10+, `asyncio.Lock()` creates a lock without requiring a running loop (deprecated in 3.8, removed in 3.10). Since the project targets Python 3.11+ (uses `|` union syntax), this is NOT a crash risk in production. However, lazy init is still cleaner. Marked as HIGH for correctness, not crash severity.

3. **"Message list unbounded growth in tool loop"** — BY DESIGN. The loop is capped at 15 iterations, which accumulates ~60 messages max. At ~100 tokens per message, that's ~6K tokens — well within LLM context limits. This is expected behavior, not a bug.

4. **"EventSubscriber attribute access on malformed state"** — FALSE. Lines 181-185 explicitly check `if not isinstance(old_state, dict): old_state = {}`, guaranteeing dict type before `.get()` calls.

5. **"Schema cache never invalidated"** — ALREADY FILED as BUG-50.

## Verification Checklist

After all fixes:
1. `python3 -m pytest apex_brain/tests/ -q` — all tests pass
2. `python3 -m ruff check apex_brain/` — no lint errors
3. `python3 -m ruff format --check apex_brain/` — formatting OK
4. No secrets or tokens in any modified files
5. Each fix is minimal and focused — no surrounding refactors
