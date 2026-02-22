# Fifth-Pass Bug Fix Prompt — BUG-77 through BUG-91

## Instructions for Fixing Agent

You are fixing 15 new bugs found in a fifth deep scan. These are **deduplicated** against BUG-1 through BUG-76 from earlier prompts — none of these are duplicates.

**Rules:**
1. Fix each bug in the order listed (CRITICAL first, then HIGH, MEDIUM, LOW).
2. After each fix, run `python3 -m pytest apex_brain/tests/ -x -q` to ensure no regressions.
3. Write or update tests for every fix where applicable.
4. Do NOT modify `.env` or any credentials.
5. Keep fixes minimal — don't refactor surrounding code.

---

## CRITICAL

### BUG-77: `fact_extractor.py:196` — Undefined variable `raw` in JSONDecodeError handler causes NameError

**Problem:** The `raw` variable is first assigned at line 103 (`raw = content.strip()`), inside the `try` block. If a `json.JSONDecodeError` is raised during `json.loads(raw)` at line 114, `raw` IS defined and the handler works. However, `json.JSONDecodeError` can also be raised by other code, and more critically: if the code structure is ever changed so that the exception is raised before line 103, `raw` will be undefined. Currently the only path that hits the `json.JSONDecodeError` catch IS after line 103, so this is a **latent bug** that will become CRITICAL on any refactor. It also prevents adding any JSON parsing before line 103.

**File:** `apex_brain/memory/fact_extractor.py`, lines 83-196

**Fix:** Initialize `raw` before the `try` block:
```python
raw = ""
try:
    response = await litellm_completion(...)
    # ...
    raw = content.strip()
```

**Test:** Mock `litellm_completion` to return content that is not valid JSON — verify no `NameError`, only a logged warning.

---

### BUG-78: `knowledge_store.py:141-142` — `item.get()` called on non-dict object causes AttributeError

**Problem:** In `_embed_text()`, the embedding response is parsed with a chain: `getattr(item, "embedding", None) or item.get("embedding")`. If `item` (from `data[0]`) is a Pydantic model or named tuple (common with LiteLLM `EmbeddingResponse`), and it lacks an `embedding` attribute, `getattr()` returns `None`. Then `item.get("embedding")` is called — but non-dict objects don't have `.get()`, causing `AttributeError`.

**File:** `apex_brain/memory/knowledge_store.py`, lines 140-143

**Current code:**
```python
item = data[0]
emb = getattr(item, "embedding", None) or item.get(
    "embedding"
)
```

**Fix:**
```python
item = data[0]
if isinstance(item, dict):
    emb = item.get("embedding")
else:
    emb = getattr(item, "embedding", None)
```

**Test:** Mock `_embed_fn` to return a Pydantic-style response object (not dict) — verify no `AttributeError`.

---

## HIGH

### BUG-79: `event_subscriber.py:59-63` — Session leak on double `start()` call

**Problem:** If `start()` is called twice (e.g., due to retry logic, duplicate event subscriber creation, or a race during startup), the first `aiohttp.ClientSession` is silently overwritten without being closed. The old session's TCP connections leak permanently.

**File:** `apex_brain/brain/event_subscriber.py`, lines 59-63

**Current code:**
```python
async def start(self) -> None:
    self._running = True
    self._session = aiohttp.ClientSession()  # Overwrites existing session
    self._loop_task = asyncio.create_task(self._connection_loop())
```

**Fix:** Guard against double-start:
```python
async def start(self) -> None:
    if self._session is not None:
        logger.warning("EventSubscriber already started, ignoring duplicate start()")
        return
    self._running = True
    self._session = aiohttp.ClientSession()
    self._loop_task = asyncio.create_task(self._connection_loop())
    logger.info("EventSubscriber starting")
```

**Test:** Call `start()` twice — verify only one session is created and a warning is logged.

---

### BUG-80: `configure.py` — Multiple handlers use `ws_command()` result without type-checking

**Problem:** Handlers `_handle_rename` (line 84), `_handle_create_area` (line 161), `_handle_assign_area` (lines 99, 109), `_handle_disable` (line 124), `_handle_enable` (line 139) all call `await ws_command({...})` and then either call `.get()` on the result or ignore it entirely. If `ws_command()` raises an unexpected exception type not caught by `configure()`'s try/except (which only catches `RuntimeError`, `ConnectionError`, `PermissionError`, `TimeoutError` per BUG-42), or if it returns `None`, the `.get()` call crashes with `AttributeError`.

Note: This is **distinct from BUG-42** which covers adding a catch-all exception handler in `configure()`. This bug is about the individual handlers not validating their own return values.

**File:** `apex_brain/tools/configure.py`, lines 69-176

**Fix:** Add type validation after each `ws_command()` call:
```python
result = await ws_command({...})
if not isinstance(result, dict):
    return f"Unexpected response from HA for {action}."
```

**Test:** Mock `ws_command` to return `None` — verify no `AttributeError`, returns error message.

---

### BUG-81: `context_builder.py:46` — Overly broad `except (KeyError, Exception)` masks import/runtime errors

**Problem:** `except (KeyError, Exception)` is equivalent to `except Exception` since `KeyError` is a subclass. This catches ALL exceptions during timezone creation — including `ImportError` (if `zoneinfo` is not installed), `RuntimeError`, and other unexpected errors. The code silently falls back to UTC when the real issue may be a broken Python installation or missing dependency.

**File:** `apex_brain/memory/context_builder.py`, line 46

**Current code:**
```python
try:
    tz = ZoneInfo(settings.timezone)
except (KeyError, Exception):
    tz = datetime.timezone.utc
```

**Fix:** Catch only expected exceptions:
```python
try:
    tz = ZoneInfo(settings.timezone)
except (KeyError, ValueError):
    logger.warning(
        "Invalid timezone '%s', falling back to UTC",
        settings.timezone,
    )
    tz = datetime.timezone.utc
```

**Test:** Mock `ZoneInfo` to raise `RuntimeError` — verify it propagates instead of silently falling back.

---

## MEDIUM

### BUG-82: `conversation.py:222` — Unreachable code makes redundant LLM API call

**Problem:** In `_llm_call_with_retry()`, the for-loop either `return`s on success (line 209) or `raise`s on the final attempt (line 212). The code after the loop (line 222) is unreachable but contains `return await litellm.acompletion(**kwargs)` — if somehow reached, it would make a **duplicate billable API call**.

**File:** `apex_brain/brain/conversation.py`, line 222

**Current code:**
```python
for attempt in range(_max_retries):
    try:
        return await litellm.acompletion(**kwargs)
    except RateLimitError:
        if attempt == _max_retries - 1:
            raise
        # ... sleep and retry
# Should never reach here, but satisfy type checker
return await litellm.acompletion(**kwargs)  # UNREACHABLE + DUPLICATE CALL
```

**Fix:** Replace with a safe assertion:
```python
raise RuntimeError("LLM retry loop exhausted without return or raise")
```

**Test:** N/A — unreachable code. But verify existing retry tests still pass.

---

### BUG-83: `scheduler.py:132-137` — Custom registered tasks have no overlap protection

**Problem:** The scheduler fires tasks via `asyncio.create_task()` and sets `next_run` before the task completes. Built-in briefing tasks are protected by `_last_fired_date` checks inside `_timed_briefing()`. But custom tasks registered via `scheduler.register()` have no such guard. If a task runs longer than its interval, it will overlap with itself.

**File:** `apex_brain/brain/scheduler.py`, lines 132-137

**Current code:**
```python
if task.enabled and now >= task.next_run:
    task.next_run = now + task.interval_seconds
    t = asyncio.create_task(self._safe_run(task))
```

**Fix:** Add a `_running` flag to `ScheduledTask`:
```python
@dataclass
class ScheduledTask:
    # ... existing fields ...
    _is_running: bool = field(default=False, repr=False)
```

Then in `_run_loop`:
```python
if task.enabled and now >= task.next_run and not task._is_running:
    task.next_run = now + task.interval_seconds
    task._is_running = True
    t = asyncio.create_task(self._safe_run(task))
```

And in `_safe_run`:
```python
async def _safe_run(self, task: ScheduledTask) -> None:
    try:
        await asyncio.wait_for(task.callback(), timeout=_TASK_TIMEOUT)
    except TimeoutError:
        logger.error("Task '%s' timed out after %ds", task.name, _TASK_TIMEOUT)
    except Exception as e:
        logger.error("Task '%s' failed: %s", task.name, e, exc_info=True)
    finally:
        task._is_running = False
```

**Test:** Register a task with 1s interval that sleeps for 5s — verify it doesn't overlap.

---

### BUG-84: `calendar_tool.py` — `lstrip("0")` in `_format_time` strips too aggressively

**Problem:** `dt.strftime("%I:%M %p").lstrip("0")` uses `lstrip` which strips ALL leading characters that are in the given set, not just the first one. For `"09:00 AM"`, it strips both the `0` and the `9` would remain since it's not `0`. Actually `lstrip("0")` strips consecutive `0`s from the left — so `"09:00 AM"` → `"9:00 AM"` (correct) and `"12:30 PM"` → `"12:30 PM"` (correct). However, if the format ever produced `"00:30 AM"` (which `%I` doesn't — it produces `"12:30 AM"` instead), `lstrip("0")` would produce `":30 AM"`.

The real issue is the `or` fallback: `.lstrip("0") or dt.strftime(...)` only triggers if the result is empty string, which can't happen with `%I` format. The `or` is dead code.

**File:** `apex_brain/tools/calendar_tool.py`, `_format_time` function

**Fix:** Use explicit slicing for clarity and safety:
```python
formatted = dt.strftime("%I:%M %p")
if formatted.startswith("0"):
    formatted = formatted[1:]
return formatted
```

**Test:** Verify `_format_time` with various hours (9 AM, 12 PM, 1 PM).

---

### BUG-85: `knowledge_store.py:138-139` — Fragile embedding fallback treats response object as float array

**Problem:** When `data` is empty/None in `_embed_text()`, the code falls back to `np.array(response, dtype=np.float32)`, assuming the embed function returned a raw list of floats. If the embed function returns a complex object (LiteLLM response, dict, etc.), `np.array()` will create a 0-dimensional object array or raise `ValueError`, breaking downstream cosine similarity.

**File:** `apex_brain/memory/knowledge_store.py`, lines 137-139

**Current code:**
```python
if not data:
    # _embed_fn may return the embedding list directly
    return np.array(response, dtype=np.float32)
```

**Fix:**
```python
if not data:
    if isinstance(response, (list, tuple)):
        return np.array(response, dtype=np.float32)
    logger.warning("[KnowledgeStore] Unexpected embedding response type: %s", type(response))
    return None
```

**Test:** Mock `_embed_fn` to return a dict without `data` key — verify returns `None` instead of crashing.

---

### BUG-86: `context_builder.py:63-72` — Double keyword search on semantic fallback

**Problem:** `search_semantic()` already falls back to `search_keyword()` internally when embeddings are unavailable (line 459: `return await self.search_keyword(query, limit)`). But `context_builder.build()` does its own explicit fallback:

```python
results = await self.knowledge_store.search_semantic(query=user_message, limit=self.max_facts)
if not results:
    results = await self.knowledge_store.search_keyword(query=user_message, limit=self.max_facts)
```

If semantic search fails and internally falls back to keyword search (returning results), the outer fallback won't trigger. But if semantic search's internal keyword fallback returns empty results, the outer fallback calls `search_keyword` AGAIN — redundant DB query.

**File:** `apex_brain/memory/context_builder.py`, lines 63-72

**Fix:** Remove the outer fallback since `search_semantic` already handles it:
```python
relevant_facts = []
if user_message:
    relevant_facts = await self.knowledge_store.search_semantic(
        query=user_message, limit=self.max_facts,
    )
```

**Test:** Mock `search_semantic` to return `[]` — verify `search_keyword` is NOT called a second time.

---

## LOW

### BUG-87: `config.py:114-118` — Implicit string concatenation for file paths is fragile

**Problem:** Two pairs of adjacent string literals use Python's implicit concatenation. While this produces correct paths, it's confusing and will break silently if a comma is accidentally added or removed during editing.

**File:** `apex_brain/brain/config.py`, lines 114-118

**Current code:**
```python
for path in [
    "/run/s6/container_environment"
    "/SUPERVISOR_TOKEN",
    "/var/run/s6/container_environment"
    "/SUPERVISOR_TOKEN",
]:
```

**Fix:** Use explicit single strings:
```python
for path in [
    "/run/s6/container_environment/SUPERVISOR_TOKEN",
    "/var/run/s6/container_environment/SUPERVISOR_TOKEN",
]:
```

**Test:** N/A — no behavior change, just clarity.

---

### BUG-88: `event_handler.py:127-128` — Device recovery from `unavailable` is silently filtered

**Problem:** When a device transitions from `unavailable` to any state, the event is dropped with reason `"recovery from unavailable to {new}"`. While this reduces noise from connectivity bounces, it means users are NEVER notified when a previously-offline device comes back online. For important devices (e.g., a security camera, NAS, or server), this could mask outages.

**File:** `apex_brain/brain/event_handler.py`, lines 127-128

**Fix:** Only filter recovery for non-critical domains. Import the critical domains list:
```python
from brain.decision_engine import _CRITICAL_DOMAINS

# In _is_redundant:
if old == "unavailable" and new:
    domain = event.entity_id.split(".")[0] if "." in event.entity_id else ""
    if domain not in _CRITICAL_DOMAINS:
        return f"recovery from unavailable to {new}"
```

**Test:** Send recovery event for `lock.front_door` — verify it's NOT filtered. Send recovery for `light.kitchen` — verify it IS filtered.

---

### BUG-89: `configure.py` — Several handlers ignore `ws_command()` result, always returning success

**Problem:** `_handle_assign_area` (lines 99, 109), `_handle_disable` (line 124), `_handle_enable` (line 139), and `_handle_delete_area` (line 170) store the `ws_command()` result in `result` but never check it. They always return a success message like `"Disabled entity {target}."` even if the WebSocket command failed silently (returned an error dict).

**File:** `apex_brain/tools/configure.py`, lines 88-176

**Fix:** Check result for success before returning success messages:
```python
result = await ws_command({...})
if isinstance(result, dict) and result.get("error"):
    return f"Error: {result.get('error', 'Unknown error')}"
return f"Disabled entity {target}."
```

**Test:** Mock `ws_command` to return `{"error": "not found"}` — verify error is surfaced, not success.

---

### BUG-90: `generic.py:285` — Floor discovery swallows all exceptions with misleading version message

**Problem:** In `_discover_floors()`, any exception (timeout, auth failure, JSON parse error) returns `"Floors not available (requires Home Assistant 2024.2+)."` This is misleading when the actual issue is a network timeout or authentication failure.

**File:** `apex_brain/tools/generic.py`, `_discover_floors` function

**Fix:**
```python
except Exception as e:
    logger.debug("Floors discovery error: %s", e)
    return f"Floors not available: {e}"
```

**Test:** Mock `ha_request` to raise `TimeoutError` — verify error message mentions timeout, not version.

---

### BUG-91: `knowledge_store.py:512-521, 575-584` — Batch `last_mentioned_at` update not in transaction

**Problem:** Both `search_semantic()` and `search_keyword()` perform a batch UPDATE on `last_mentioned_at` for returned results, followed by `commit()`. This UPDATE+commit is outside any explicit transaction. If the app crashes between the UPDATE and commit (unlikely but possible), the WAL journal handles recovery. More practically, this means each search does TWO database round-trips (SELECT + UPDATE), adding latency to every context build.

**File:** `apex_brain/memory/knowledge_store.py`, lines 512-521 and 575-584

**Fix:** Wrap in a single transaction or defer the touch to a background task:
```python
# Option A: background task (preferred — don't slow down search)
asyncio.get_event_loop().call_soon(
    asyncio.create_task,
    self._batch_touch_facts(ids)
)
```

**Test:** Verify search returns results even if the touch-update fails.

---

## Summary

| Severity | Count | Bug IDs |
|----------|-------|---------|
| CRITICAL | 2 | BUG-77, 78 |
| HIGH | 3 | BUG-79, 80, 81 |
| MEDIUM | 5 | BUG-82, 83, 84, 85, 86 |
| LOW | 5 | BUG-87, 88, 89, 90, 91 |
| **Total** | **15** | |

## Deduplicated Against Earlier Prompts

The following bugs from my scan were already documented and are NOT included:
- Server shutdown None stores → BUG-59
- Curator timestamp string comparison → BUG-46
- manage.py missing general exception handler → BUG-42
- Rate limiter race condition → Rejected as false positive in Prompt 4
- Lights score below threshold → Related to BUG-53
- conversation_store local import → Related to BUG-58

## Verification Checklist

After all fixes:
1. `python3 -m pytest apex_brain/tests/ -q` — all tests pass
2. `python3 -m ruff check apex_brain/` — no lint errors
3. `python3 -m ruff format --check apex_brain/` — formatting OK
4. No secrets or tokens in any modified files
5. Each fix is minimal and focused — no surrounding refactors
