# Apex Brain — Deep Bug Scan Report (4th Pass)

> **Date:** 2026-02-21
> **Test baseline:** 643 passed, 3 skipped, 1 warning
> **Scan scope:** All 85 Python files across brain/, memory/, tools/, tests/
> **Previous bugs:** BUG-1 through BUG-58 from scans 1-3 are already fixed.

---

## Instructions for Fixing Agent

**Rules:**
1. Fix each bug in the order listed (CRITICAL first, then HIGH, MEDIUM, LOW).
2. After each fix, run `PYTHONPATH=apex_brain python3 -m pytest apex_brain/tests/ -x -q` to ensure no regressions.
3. Write or update tests for every fix where applicable.
4. Do NOT modify `.env` or any credentials.
5. Keep fixes minimal — don't refactor surrounding code.

---

## CRITICAL BUGS (Fix Immediately)

### BUG-59: `do()` security gate bypassable — LLM can skip confirmation for locks/alarms

**File:** `apex_brain/tools/generic.py:637`

**Problem:** An LLM (or malicious API caller) can unlock doors, disarm alarms, open garage covers, and control cameras WITHOUT confirmation by simply passing `"confirmed": true` in the `data` dict on the very first call. There is no server-side verification that a confirmation prompt was ever shown.

```python
confirmed = bool(data and data.get("confirmed"))
if domain in PROTECTED_DOMAINS and not confirmed:
    # Security gate — but bypassed by passing confirmed=true on first call
```

**Fix:** Implement server-side confirmation tracking. On first call to a protected domain, store a pending confirmation key in `Conversation._pending_confirmations`. The second call must match. Example:

```python
# In do():
if domain in PROTECTED_DOMAINS:
    confirm_key = f"{domain}.{service}:{targets}"
    if not _pending_confirmations.pop(confirm_key, False):
        _pending_confirmations[confirm_key] = True
        return "CONFIRMATION REQUIRED: ..."
```

Alternatively, strip `confirmed` from data completely and only honor it when `conversation._last_tool_result` for this session contained "CONFIRMATION REQUIRED" for the same domain/service.

**Test:** Call `do("lock", "unlock", targets={"entity_id": "lock.front"}, data={"confirmed": True})` without a prior prompt — should NOT execute.

---

### BUG-60: `scheduler`/`event_subscriber` globals never assigned — shutdown leaks resources

**File:** `apex_brain/brain/server.py:98`

**Problem:** `lifespan` declares `global conversation, event_handler, startup_time` but does NOT include `scheduler` or `event_subscriber`. Lines 210 and 228 assign to local variables that shadow the module globals. Module-level globals remain `None`.

Consequences:
- Shutdown (lines 257-258) checks `if event_subscriber:` / `if scheduler:` — always `None`, so **scheduler and event_subscriber are NEVER stopped on shutdown**, leaking asyncio tasks, WebSocket connections, and background loops
- `/health` endpoint never reports scheduler/subscriber status

**Fix:** Change line 98 to:
```python
global conversation, event_handler, scheduler, event_subscriber, startup_time
```

**Test:** Verify that after lifespan shutdown, the module-level `scheduler` and `event_subscriber` have `.stop()` called.

---

### BUG-61: Reminders never fire — `expires_at` missing from `get_all_facts()` result

**File:** `apex_brain/brain/scheduler.py:346` + `apex_brain/memory/knowledge_store.py:596-627`

**Problem:** The scheduler's reminder check filters facts by `f.get("expires_at")`, but `get_all_facts()` returns dicts with only 7 keys: `id, category, key, value, confidence, created_at, updated_at`. The `expires_at` column is NOT in the SELECT query and NOT in the dict mapping. `f.get("expires_at")` always returns `None`, the `due` list is always empty, and **no reminder ever fires**.

**Fix:** Update `get_all_facts()` to include `expires_at`:

```python
# In the SELECT query, add expires_at:
"SELECT id, category, key, value, confidence, created_at, updated_at, expires_at ..."

# In the dict mapping, add:
"expires_at": r[7],
```

**Test:** Store a fact with `category="reminder"` and `expires_at` in the past. Call `_task_reminder_check()` — verify the reminder fires.

---

### BUG-62: `BEGIN IMMEDIATE` inside aiosqlite auto-transaction may crash

**File:** `apex_brain/memory/knowledge_store.py:209`

**Problem:** `store_fact()` executes `BEGIN IMMEDIATE` but aiosqlite uses `isolation_level=""` by default, auto-managing transactions. Calling `BEGIN IMMEDIATE` when an implicit transaction is active raises `OperationalError: cannot start a transaction within a transaction`. Additionally, the ROLLBACK on line 304 can fail and swallow the original error.

**Fix:** After `aiosqlite.connect()` in `initialize()`, disable auto-transactions:
```python
self._db = await aiosqlite.connect(self.db_path)
self._db._conn.isolation_level = None  # manual transaction control
```

Also wrap ROLLBACK in try/except:
```python
except Exception:
    try:
        await self._db.execute("ROLLBACK")
    except Exception:
        logger.warning("ROLLBACK failed", exc_info=True)
    raise
```

**Test:** Verify `store_fact()` succeeds when called multiple times in sequence.

---

## HIGH SEVERITY BUGS

### BUG-63: Shutdown crashes if stores are None — no guards on `.close()` calls

**File:** `apex_brain/brain/server.py:266-268`

**Problem:** The normal shutdown path calls `await routine_store.close()`, `await convo_store.close()`, `await knowledge_store.close()` without None guards. The exception handler (lines 246-251) correctly checks `if routine_store:` etc, but the normal shutdown at lines 266-268 does not.

**Fix:**
```python
if routine_store:
    await routine_store.close()
if convo_store:
    await convo_store.close()
if knowledge_store:
    await knowledge_store.close()
```

---

### BUG-64: `configure()` missing catch-all exception — `result` undefined for unexpected errors

**File:** `apex_brain/tools/configure.py:407-416`

**Problem:** The try/except catches `RuntimeError`, `ConnectionError`, `PermissionError`, `TimeoutError` but NOT generic `Exception`. Any other exception type (e.g., `KeyError`, `TypeError`, `ValueError` from a handler) propagates uncaught, crashing the tool call and leaving `result` undefined for the audit log.

**Fix:** Add:
```python
except Exception as e:
    logger.error("Unexpected error in configure handler '%s': %s", action, e)
    result = f"Error: {e}"
```

**Test:** Mock a handler that raises `ValueError` — verify audit log is still written and graceful error returned.

---

### BUG-65: `entity_id` in `do()` targets can be a list, breaking verification

**File:** `apex_brain/tools/generic.py:680-685`

**Problem:** HA accepts `entity_id` as a string OR a list. When the LLM passes `{"entity_id": ["light.a", "light.b"]}`, the verification call `verify_generic(entity_id)` builds URL `/states/['light.a', 'light.b']` which 404s. The service call itself succeeds but the user gets a misleading error.

**Fix:**
```python
if targets:
    entity_id = targets.get("entity_id", "")
    if isinstance(entity_id, list):
        entity_id = entity_id[0] if entity_id else ""
```

**Test:** Call `do("light", "turn_on", targets={"entity_id": ["light.a", "light.b"]})` — verify no crash.

---

### BUG-66: Addon slug in `manage()` not sanitized — potential path traversal

**File:** `apex_brain/tools/manage.py:289-296` (and similar at 315, 331, 377)

**Problem:** When `target` starts with `"addon:"`, the slug is extracted via `target.split(":", 1)[1]` and interpolated into the Supervisor URL: `/addons/{slug}/update`. A crafted slug like `../../core/restart` could traverse paths.

**Fix:** Validate the slug:
```python
slug = target.split(":", 1)[1]
if not re.match(r'^[a-zA-Z0-9_.-]+$', slug):
    return f"Invalid addon slug: {slug}"
```

**Test:** Pass `target="addon:../../core/restart"` — should return error.

---

### BUG-67: All stores access `self._db` without None checks

**File:** `audit_store.py:62`, `conversation_store.py:48`, `knowledge_store.py`, `routine_store.py`

**Problem:** If `initialize()` was never called or `close()` was already called, every method crashes with `AttributeError: 'NoneType' object has no attribute 'execute'`.

**Fix:** Add at top of each public method:
```python
if self._db is None:
    raise RuntimeError("Store not initialized. Call initialize() first.")
```

---

### BUG-68: `get_contradictory_facts()` always returns empty — dead code

**File:** `apex_brain/memory/knowledge_store.py:700-733`

**Problem:** Self-JOIN looks for `a.category = b.category AND a.key = b.key AND a.id < b.id`, but the `UNIQUE INDEX ON (category, key)` means two rows can never share the same (category, key). The query always returns empty. The Curator's contradiction resolution is silently disabled.

**Fix:** Either remove the method (it's dead code due to the unique index) or redesign to detect semantic contradictions using embedding similarity.

---

## MEDIUM SEVERITY BUGS

### BUG-69: Shared `session_id="apex_events"` causes context crosstalk between concurrent events

**File:** `apex_brain/brain/event_handler.py:182` + `apex_brain/brain/event_subscriber.py:203`

**Problem:** Both webhook and WebSocket event paths use `session_id="apex_events"`. When multiple events arrive concurrently, their conversation histories bleed into each other. The AI can confuse which event it's responding to.

**Fix:** Use per-event session IDs:
```python
from uuid import uuid4
session_id = f"apex_event_{uuid4().hex[:8]}"
```

---

### BUG-70: Calendar timezone stripping causes wrong dates/times

**File:** `apex_brain/tools/calendar_tool.py:52-58`

**Problem:** `_parse_event_dt` strips timezone with `dt.replace(tzinfo=None)` and compares against naive `datetime.now()`. UTC timestamps are treated as local time. For users west of UTC, evening events appear on the wrong day.

**Fix:** Convert to local timezone using `settings.timezone`:
```python
from zoneinfo import ZoneInfo
local_tz = ZoneInfo(settings.timezone)
return dt.astimezone(local_tz).replace(tzinfo=None)
```

---

### BUG-71: Calendar multi-day events filtered out from today view

**File:** `apex_brain/tools/calendar_tool.py:170-172`

**Problem:** Filter checks `today_start <= start_dt <= today_end`, excluding events that started before today but are still ongoing (vacations, conferences).

**Fix:** Check overlap:
```python
if start_dt is not None and end_dt is not None:
    if end_dt < today_start or start_dt > today_end:
        continue
elif start_dt is not None:
    if not (today_start <= start_dt <= today_end):
        continue
```

---

### BUG-72: `_check_duplicate()` holds write lock during O(N) cosine scan

**File:** `apex_brain/memory/knowledge_store.py:266-277`

**Problem:** `BEGIN IMMEDIATE` acquires a RESERVED lock, then `_check_duplicate()` scans up to 200 facts doing cosine similarity while holding it. All other writers are blocked.

**Fix:** Move `_check_duplicate()` call outside the `BEGIN IMMEDIATE` block. Accept the small TOCTOU window.

---

### BUG-73: Four stores share one SQLite file with separate connections — write contention

**File:** All store files

**Problem:** Four independent `aiosqlite.connect()` calls to the same DB file. WAL allows only ONE writer at a time. Under load, concurrent writes cause `database is locked` with 5s timeout.

**Fix:** Increase `busy_timeout` to 30000ms, or add an `asyncio.Lock` for write serialization.

---

### BUG-74: `search_semantic()` loads ALL facts into memory for linear scan

**File:** `apex_brain/memory/knowledge_store.py:471-508`

**Problem:** No LIMIT on SELECT — fetches every fact with embedding. O(N) numpy cosine similarity blocks the event loop.

**Fix:** Add `LIMIT 1000` to the query. For CPU-bound computation, use `asyncio.to_thread()`.

---

### BUG-75: Supervisor HTTP client never closed

**File:** `apex_brain/tools/manage.py:25-31`

**Problem:** Module-level `httpx.AsyncClient` with no shutdown hook. TCP connections leak on restart.

**Fix:** Add `close_supervisor_client()` and call from server shutdown.

---

### BUG-76: `model_dump()` includes provider-incompatible fields in conversation loop

**File:** `apex_brain/brain/conversation.py:316, 355`

**Problem:** `msg.model_dump()` may include `tool_calls: null` or provider-specific fields. Switching LLM providers (OpenAI/Anthropic/Gemini) via litellm can fail.

**Fix:**
```python
msg_dict = msg.model_dump(exclude_none=True)
```

---

### BUG-77: `ha_request` error returns dict, but callers iterate it as list

**File:** `automation.py:88`, `energy.py:126`, `presence.py:29`, and 10+ other locations

**Problem:** When HA is unreachable, `ha_request("GET", "/states")` returns `{"error": "..."}`. Callers do list comprehension on it, iterating dict keys → `TypeError`.

**Fix:** Add `if not isinstance(states, list): return "Cannot reach HA..."` after every `/states` call. Or refactor `ha_request` to raise exceptions on error.

---

### BUG-78: `do()` flat payload merge — targets and data key collisions

**File:** `apex_brain/tools/generic.py:659-664`

**Problem:** `payload.update(targets)` then `payload.update(data)` — if both contain `entity_id`, data overwrites targets silently.

**Fix:** Log a warning when keys collide.

---

### BUG-79: Tool name collisions silently overwrite in TOOL_REGISTRY

**File:** `apex_brain/tools/base.py:42`

**Problem:** If two tool functions have the same name, the second silently replaces the first.

**Fix:** Add:
```python
if func.__name__ in TOOL_REGISTRY:
    logger.warning("Tool '%s' redefined! Was from %s", func.__name__, TOOL_REGISTRY[func.__name__]["function"].__module__)
```

---

### BUG-80: `cover` domain not scored in `_score_significance()` despite being in `_CRITICAL_DOMAINS`

**File:** `apex_brain/brain/decision_engine.py`

**Problem:** `cover` (garage doors) is in `_CRITICAL_DOMAINS` for hard filter but NOT in `_score_significance()`. A cover going unavailable passes the filter but gets base score 0.3, possibly below threshold. Garage door offline events may be silently ignored.

**Fix:** Add `cover` scoring in `_score_significance()`, similar to `lock`/`camera`.

---

### BUG-81: Webhook secret in request body instead of header

**File:** `apex_brain/brain/server.py:484-491`

**Problem:** Secret extracted from `event.attributes.get("secret")` — in the JSON body, visible in logs if body is logged.

**Fix:** Move to header-based: `request.headers.get("X-Webhook-Secret")`.

---

### BUG-82: MCP `disconnect()` doesn't clear stale tool definitions

**File:** `apex_brain/tools/mcp_bridge.py:102-113`

**Problem:** After disconnect, `self._tools` and `self._tool_names` still contain old data. LLM keeps calling tools that always fail.

**Fix:** Add `self._tools = []` and `self._tool_names = set()` in `disconnect()`.

---

### BUG-83: `curator.audit_facts` reports inflated prune count

**File:** `apex_brain/brain/curator.py:58-69`

**Problem:** Reports `len(low_conf)` as pruned but doesn't track actual successful deletions.

**Fix:** Track actual count:
```python
pruned = sum(1 for f in low_conf if f.get("id") and await self._knowledge_store.delete_fact_by_id(f["id"]))
```

---

## LOW SEVERITY BUGS

### BUG-84: Action trace eviction can delete just-inserted key → KeyError

**File:** `apex_brain/brain/conversation.py:337-340`

**Problem:** If session_id is the oldest key, it gets evicted then accessed → `KeyError`.

**Fix:** Use `.get()` on line 340.

---

### BUG-85: `_embed_text` fallback may create garbage numpy array

**File:** `apex_brain/memory/knowledge_store.py:139`

**Problem:** If embed function returns unexpected type, `np.array(response, dtype=np.float32)` creates bogus vector.

**Fix:** Add `isinstance(response, (list, tuple))` check.

---

### BUG-86: `get_device_summary` crashes if state dict lacks `entity_id`

**File:** `apex_brain/tools/ha_helpers.py:182`

**Problem:** `s["entity_id"]` KeyError on malformed state data.

**Fix:** Use `s.get("entity_id", "")`.

---

### BUG-87: RoutineStore lowercases names + COLLATE NOCASE = inconsistency

**File:** `apex_brain/memory/routine_store.py:64-67`

**Problem:** `.lower().strip()` + `COLLATE NOCASE` creates mismatch for migrated data.

**Fix:** Standardize: always store lowercase or drop `.lower()` and let COLLATE NOCASE handle it.

---

### BUG-88: `decay_confidence()` individual UPDATEs without explicit transaction

**File:** `apex_brain/memory/knowledge_store.py:396-440`

**Problem:** If crash mid-loop, some facts decayed, some not. Holds implicit lock during iteration.

**Fix:** Use single SQL `UPDATE` with computed expression, or wrap in explicit transaction.

---

## TEST COVERAGE GAPS

| # | Gap | Severity |
|---|-----|----------|
| GAP-1 | `ConversationStore` — ZERO tests (SQL injection surface in `_escape_like` untested) | HIGH |
| GAP-2 | `KnowledgeStore` — only 2-3 tests for 15+ methods (conflict resolution, dedup, decay, transactions untested) | HIGH |
| GAP-3 | `Scheduler._task_reminder_check()` — entirely untested | HIGH |
| GAP-4 | `CooldownTracker` — no dedicated tests (cleanup logic untested) | HIGH |
| GAP-5 | Server endpoints (`/api/chat`, `/api/webhook`, `/v1/chat/completions`) — zero tests | HIGH |
| GAP-6 | `EventSubscriber` reconnection backoff, auth failure — untested | MEDIUM |
| GAP-7 | `mock_embed` returns identical vectors for ALL text — semantic search tests don't validate ranking | MEDIUM |
| GAP-8 | 14 tool modules have no test files (mostly deprecated but still callable) | MEDIUM |

---

## Summary

| Severity | Count | Bug IDs |
|----------|-------|---------|
| CRITICAL | 4 | BUG-59, BUG-60, BUG-61, BUG-62 |
| HIGH | 6 | BUG-63 through BUG-68 |
| MEDIUM | 15 | BUG-69 through BUG-83 |
| LOW | 5 | BUG-84 through BUG-88 |
| Test Gaps | 8 | GAP-1 through GAP-8 |
| **Total** | **30 bugs + 8 test gaps** | |

---

## Recommended Fix Order

### Batch 1 — Security & Data Loss (do first)
1. BUG-59: Security gate bypass on protected domains
2. BUG-60: Scheduler/subscriber never stop on shutdown
3. BUG-61: Reminders never fire
4. BUG-62: SQLite transaction management

### Batch 2 — Crash Prevention
5. BUG-63: Shutdown crash on None stores
6. BUG-64: configure() catch-all exception
7. BUG-65: List entity_id in do() verification
8. BUG-66: Addon slug path traversal
9. BUG-67: Store uninitialized guards

### Batch 3 — Correctness
10. BUG-69: Event session crosstalk
11. BUG-70: Calendar timezone
12. BUG-71: Calendar multi-day events
13. BUG-76: model_dump provider compat
14. BUG-77: ha_request error returns as dict
15. BUG-80: Cover domain scoring

### Batch 4 — Performance & Maintenance
16. BUG-72: Write lock during cosine scan
17. BUG-73: SQLite write contention
18. BUG-74: Unbounded semantic search
19. BUG-75: Supervisor client leak
20. BUG-78: Payload merge collisions

### Batch 5 — Test Coverage
21. GAP-1: ConversationStore tests
22. GAP-2: KnowledgeStore tests
23. GAP-3: Reminder tests
24. GAP-4: CooldownTracker tests
25. GAP-5: Server endpoint tests

---

## Verification Checklist

After all fixes:
1. `PYTHONPATH=apex_brain python3 -m pytest apex_brain/tests/ -q` — all tests pass
2. `python3 -m ruff check apex_brain/` — no lint errors
3. `python3 -m ruff format --check apex_brain/` — formatting OK
4. No secrets or tokens in any modified files
5. Each fix is minimal and focused — no surrounding refactors
