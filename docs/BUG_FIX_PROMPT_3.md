# Sixth-Pass Deep Bug Scan — BUG-92 through BUG-125

> **Date:** 2026-02-22
> **Test baseline:** 643 passed, 3 skipped, 1 warning
> **Scan scope:** All 85 Python files across brain/, memory/, tools/, tests/
> **Previous bugs:** BUG-1–58 (Prompts 1-3, fixed), BUG-59–76 (Prompt 4, unfixed), BUG-77–91 (Prompt 5, unfixed)
> **This report:** Deduplicated against all prior prompts. No number collisions.

---

## Instructions for Fixing Agent

**Rules:**
1. Fix each bug in the order listed (CRITICAL first, then HIGH, MEDIUM, LOW).
2. After each fix, run `PYTHONPATH=apex_brain python3 -m pytest apex_brain/tests/ -x -q` to ensure no regressions.
3. Write or update tests for every fix where applicable.
4. Do NOT modify `.env` or any credentials.
5. Keep fixes minimal — don't refactor surrounding code.

**Important:** BUG-59–91 from Prompts 4 and 5 are ALSO unfixed. Fix those first if not already done, then proceed to BUG-92+ below.

---

## CRITICAL

### BUG-92: `do()` security gate bypassable — LLM can skip confirmation for locks/alarms

**File:** `apex_brain/tools/generic.py:637`

**Problem:** An LLM (or malicious API caller) can unlock doors, disarm alarms, open garage covers, and control cameras WITHOUT confirmation by simply passing `"confirmed": true` in the `data` dict on the very first call. There is no server-side verification that a confirmation prompt was ever shown.

```python
confirmed = bool(data and data.get("confirmed"))
if domain in PROTECTED_DOMAINS and not confirmed:
    # Security gate — bypassed by passing confirmed=true on first call
```

**Not a duplicate of any prior BUG.** No prior prompt addresses the security gate bypass mechanism.

**Fix:** Implement server-side confirmation tracking. On first call to a protected domain, store a pending confirmation key. The second call must match that key to prove the user saw the prompt.

**Test:** Call `do("lock", "unlock", targets={"entity_id": "lock.front"}, data={"confirmed": True})` without a prior prompt — should NOT execute.

---

### BUG-93: Reminders never fire — `expires_at` missing from `get_all_facts()` result

**File:** `apex_brain/brain/scheduler.py:346` + `apex_brain/memory/knowledge_store.py:596-627`

**Problem:** The scheduler's reminder check filters facts by `f.get("expires_at")`, but `get_all_facts()` returns dicts with only 7 keys: `id, category, key, value, confidence, created_at, updated_at`. The `expires_at` column is NOT in the SELECT query and NOT in the dict mapping. `f.get("expires_at")` always returns `None`, the `due` list is always empty, and **no reminder ever fires**.

**Not a duplicate.** BUG-44 (Prompt 3) covers failed reminder *deletion* causing infinite repeats. This bug is about reminders never being *detected* as due.

**Fix:** Add `expires_at` to the SELECT and dict mapping in `get_all_facts()`:
```python
"SELECT id, category, key, value, confidence, created_at, updated_at, expires_at ..."
# Dict: "expires_at": r[7]
```

**Test:** Store a fact with `category="reminder"` and `expires_at` in the past. Call `_task_reminder_check()` — verify the reminder fires.

---

### BUG-94: `BEGIN IMMEDIATE` inside aiosqlite auto-transaction may crash + ROLLBACK swallows original error

**File:** `apex_brain/memory/knowledge_store.py:209, 304-306`

**Problem:** Two issues in one:
1. `store_fact()` executes `BEGIN IMMEDIATE` but aiosqlite uses `isolation_level=""` by default. Calling `BEGIN IMMEDIATE` when an implicit transaction is active raises `OperationalError: cannot start a transaction within a transaction`.
2. The ROLLBACK at line 304 has no try/except wrapper. If ROLLBACK itself fails (disk full, connection error), the original exception is replaced by the ROLLBACK error, making debugging impossible.

**Not a duplicate.** BUG-62 (Prompt 4) covers ws_helpers exception handlers, not knowledge_store transactions.

**Fix:**
```python
# In initialize():
self._db = await aiosqlite.connect(self.db_path)
self._db._conn.isolation_level = None  # manual transaction control

# In store_fact() except block:
except Exception:
    try:
        await self._db.execute("ROLLBACK")
    except Exception:
        logger.warning("ROLLBACK failed", exc_info=True)
    raise
```

**Test:** Verify `store_fact()` succeeds when called multiple times in sequence.

---

## HIGH

### BUG-95: `scheduler`/`event_subscriber` module globals never assigned — `/health` never reports status

**File:** `apex_brain/brain/server.py:98`

**Problem:** `lifespan` declares `global conversation, event_handler, startup_time` but does NOT include `scheduler` or `event_subscriber`. Lines 210 and 228 assign to local variables that shadow the module globals. Module-level globals remain `None`.

**Impact:** The `/health` endpoint (lines 419-423) checks `if scheduler:` and `if event_subscriber:` against module globals — always `None`. Health output never includes scheduler or event subscriber status. (Note: the shutdown path after `yield` uses local variables from the same scope, so shutdown itself works correctly.)

**Not a duplicate of BUG-59** (Prompt 4) which covers store None guards on shutdown.

**Fix:** Change line 98 to:
```python
global conversation, event_handler, scheduler, event_subscriber, startup_time
```

**Test:** Verify `/health` returns `scheduler_running` and `event_subscriber_connected` after startup.

---

### BUG-96: `entity_id` in `do()` targets can be a list, breaking verification

**File:** `apex_brain/tools/generic.py:680-685`

**Problem:** HA accepts `entity_id` as string OR list. When the LLM passes `{"entity_id": ["light.a", "light.b"]}`, `verify_generic(entity_id)` builds URL `/states/['light.a', 'light.b']` → 404. The service call succeeds but the user gets misleading error from verification.

**Fix:**
```python
if targets:
    entity_id = targets.get("entity_id", "")
    if isinstance(entity_id, list):
        entity_id = entity_id[0] if entity_id else ""
```

---

### BUG-97: Addon slug in `manage()` not sanitized — potential path traversal

**File:** `apex_brain/tools/manage.py:289-296` (and 315, 331, 377)

**Problem:** Slug from `target.split(":", 1)[1]` interpolated directly into Supervisor URL `/addons/{slug}/update`. Crafted slug like `../../core/restart` could traverse paths.

**Not a duplicate of BUG-47** (Prompt 3) which covers notify target validation.

**Fix:** `if not re.match(r'^[a-zA-Z0-9_.-]+$', slug): return "Invalid addon slug"`

---

### BUG-98: `ha_request` raises uncaught `HTTPStatusError` for non-2xx responses

**File:** `apex_brain/tools/ha_helpers.py:93`

**Problem:** `response.raise_for_status()` is called UNCONDITIONALLY on line 93, even after logging the error. For non-2xx responses, this raises `httpx.HTTPStatusError` which propagates to ALL callers. Most callers (`_discover_entities`, `_discover_areas`, `_discover_devices`, `query()`, `history()`, etc.) do NOT catch `HTTPStatusError`.

This is **distinct from** the `ConnectError`/`TimeoutException` paths (lines 80-86) which return error dicts. The `raise_for_status()` path throws an exception, not a dict.

**Note:** The prior BUG-77 diagnosis in Prompt 3 was partially wrong — it described callers iterating error dicts. That only happens for connection errors. For HTTP 4xx/5xx, the real issue is this uncaught exception.

**Fix:** Either catch `HTTPStatusError` inside `ha_request` and return a structured error dict, OR add `HTTPStatusError` handling to all callers. The cleanest fix:
```python
if not response.is_success:
    logger.error("HA API error: %s %s", response.status_code, response.text[:300])
    return {"error": f"HA API returned {response.status_code}: {response.text[:200]}"}
# Remove the unconditional raise_for_status() call
```

---

### BUG-99: All stores access `self._db` without None checks — crashes if not initialized

**File:** All 4 store files

**Problem:** If `initialize()` was never called or `close()` was already called, every method crashes with `AttributeError: 'NoneType' object has no attribute 'execute'`.

**Fix:** Add guard: `if self._db is None: raise RuntimeError("Store not initialized")`

---

### BUG-100: `get_contradictory_facts()` always returns empty — dead code due to unique index

**File:** `apex_brain/memory/knowledge_store.py:700-733`

**Problem:** Self-JOIN looks for `a.category = b.category AND a.key = b.key`, but `UNIQUE INDEX ON (category, key)` means this can never match. The Curator's contradiction resolution silently does nothing.

**Fix:** Remove dead method or redesign for semantic contradiction detection.

---

### BUG-101: `configure()` missing catch-all exception — `result` undefined

**File:** `apex_brain/tools/configure.py:407-416`

**Problem:** try/except catches 4 specific types but not generic `Exception`. Unexpected errors propagate uncaught and leave `result` undefined for audit log.

**Related to but distinct from BUG-62** (Prompt 4) which covers `ws_helpers.py` exception types.

**Fix:** Add `except Exception as e: result = f"Error: {e}"`

---

### BUG-102: `correct_fact()` non-atomic read-then-write — race with concurrent `store_fact()`

**File:** `apex_brain/memory/knowledge_store.py:308-365`

**Problem:** `correct_fact()` SELECTs to check if the fact exists, then does UPDATE or calls `store_fact()`. Between these operations, concurrent `store_fact()` can modify the same row. The correction can be silently lost.

**Fix:** Use a single `INSERT ... ON CONFLICT UPDATE` or wrap in `BEGIN IMMEDIATE`.

---

## MEDIUM

### BUG-103: Shared `session_id="apex_events"` causes context crosstalk

**File:** `apex_brain/brain/event_handler.py:182` + `event_subscriber.py:203`

**Problem:** Both webhook and WebSocket event paths use same session_id. Concurrent events' conversation histories bleed together.

**Fix:** `session_id=f"apex_event_{uuid4().hex[:8]}"`

---

### BUG-104: Calendar timezone stripping causes wrong dates/times

**File:** `apex_brain/tools/calendar_tool.py:52-58`

**Problem:** `dt.replace(tzinfo=None)` strips timezone. UTC timestamps treated as local time. Wrong day for users west of UTC.

**Related to BUG-65** (Prompt 4, calendar `_today_date()` using naive datetime) but covers a different function (`_parse_event_dt`).

**Fix:** Convert to local timezone: `dt.astimezone(local_tz).replace(tzinfo=None)`

---

### BUG-105: Calendar multi-day events filtered out from today view

**File:** `apex_brain/tools/calendar_tool.py:170-172`

**Problem:** Filter checks `today_start <= start_dt <= today_end`, excluding ongoing multi-day events.

**Fix:** Check overlap: `if end_dt < today_start or start_dt > today_end: continue`

---

### BUG-106: `_check_duplicate()` holds write lock during O(N) cosine scan

**File:** `apex_brain/memory/knowledge_store.py:266-277`

**Problem:** `BEGIN IMMEDIATE` blocks all writers while `_check_duplicate()` scans up to 200 facts.

**Fix:** Move `_check_duplicate()` outside the `BEGIN IMMEDIATE` block.

---

### BUG-107: Four stores share one SQLite file with separate connections — write contention

**File:** All store files

**Problem:** Four independent connections to same DB. WAL allows only ONE writer. Under load: `database is locked`.

**Fix:** Increase `busy_timeout` to 30000ms.

---

### BUG-108: `search_semantic()` loads ALL facts into memory for linear scan

**File:** `apex_brain/memory/knowledge_store.py:471-508`

**Problem:** No LIMIT. O(N) numpy cosine similarity blocks event loop.

**Fix:** Add `LIMIT 1000`. Use `asyncio.to_thread()` for numpy computation.

---

### BUG-109: Supervisor HTTP client never closed — connection leak

**File:** `apex_brain/tools/manage.py:25-31`

**Problem:** Module-level `httpx.AsyncClient` with no shutdown hook.

**Fix:** Add `close_supervisor_client()` and call from server shutdown.

---

### BUG-110: `model_dump()` includes provider-incompatible fields

**File:** `apex_brain/brain/conversation.py:316, 355`

**Problem:** `tool_calls: null` or provider-specific fields may break cross-provider LLM calls.

**Fix:** `msg.model_dump(exclude_none=True)`

---

### BUG-111: `cover` domain not scored in `_score_significance()` despite being in `_CRITICAL_DOMAINS`

**File:** `apex_brain/brain/decision_engine.py`

**Problem:** Cover (garage doors) passes hard filter but gets base score 0.3 — possibly below threshold.

**Fix:** Add `cover` scoring in `_score_significance()`.

---

### BUG-112: MCP `disconnect()` doesn't clear stale tool definitions

**File:** `apex_brain/tools/mcp_bridge.py:102-113`

**Problem:** After disconnect, `_tools` and `_tool_names` still hold old data. LLM keeps calling failed tools.

**Fix:** Add `self._tools = []` and `self._tool_names = set()` in `disconnect()`.

---

### BUG-113: `search_semantic()` and `search_keyword()` write during reads — unnecessary contention

**File:** `apex_brain/memory/knowledge_store.py:512-521, 575-584`

**Problem:** Both methods UPDATE `last_mentioned_at` after every search. This adds write pressure to every context build — conceptually a read operation.

**Distinct from BUG-91** (Prompt 5) which covers the missing transaction. This bug is about the unnecessary write operation itself.

**Fix:** Defer touch-update to a background task, or wrap in try/except so search returns results even if touch fails.

---

### BUG-114: `EventSubscriber._session` not None-checked before `ws_connect`

**File:** `apex_brain/brain/event_subscriber.py:114`

**Problem:** During shutdown race, `self._session` could be closed before `ws_connect`. Produces confusing error logs.

**Fix:** Guard: `if not self._session or self._session.closed: return`

---

### BUG-115: `_event_counts` dict in DecisionEngine is dead code — never used

**File:** `apex_brain/brain/decision_engine.py:59`

**Problem:** `defaultdict(int)` initialized but never incremented or read. Dead code, but unbounded growth if ever used without cleanup.

**Fix:** Remove dead field, or implement with cleanup.

---

### BUG-116: Module-level `AsyncClient` created outside async context

**File:** `apex_brain/tools/ha_helpers.py:18-24`

**Problem:** `httpx.AsyncClient()` at import time. Connection pool issues if process forks (uvicorn workers).

**Fix:** Use lazy singleton: create on first use inside async context.

---

### BUG-117: Notify entity-based path fragile for Alexa integrations

**File:** `apex_brain/tools/notify.py:65`

**Problem:** `service_name = entity_id.replace("notify.", "", 1)` doesn't validate prefix. Alexa Media notify may not support entity-based `send_message`.

**Fix:** Add fallback: if entity-based fails with 404/400, retry legacy `/services/notify/{service_name}`.

---

### BUG-118: MCP transport stream unpacking assumes tuple shape

**File:** `apex_brain/tools/mcp_bridge.py:74-78`

**Problem:** `len(streams) >= 2` assumes `__aenter__` returns indexable tuple. SDK changes could break.

**Fix:** Use `read_stream, write_stream = streams[:2]` with type guard.

---

### BUG-119: `curator.audit_facts` reports inflated prune count

**File:** `apex_brain/brain/curator.py:58-69`

**Problem:** Reports `len(low_conf)` as pruned but doesn't track actual successful deletions.

**Fix:** Track actual count.

---

## LOW

### BUG-120: Action trace eviction can delete just-inserted key → KeyError

**File:** `apex_brain/brain/conversation.py:337-340`

**Fix:** Use `.get()` on line 340.

---

### BUG-121: `get_device_summary` crashes if state dict lacks `entity_id`

**File:** `apex_brain/tools/ha_helpers.py:182`

**Fix:** Use `s.get("entity_id", "")`.

---

### BUG-122: `context_builder.py` `{f["id"]}` set comprehension — KeyError if fact lacks `id`

**File:** `apex_brain/memory/context_builder.py:76`

**Fix:** Use `f.get("id")` and filter None.

---

### BUG-123: `delete_fact()` TOCTOU between SELECT and DELETE

**File:** `apex_brain/memory/knowledge_store.py:629-644`

**Fix:** Single `DELETE FROM facts WHERE key = ?` and check `cursor.rowcount`.

---

### BUG-124: `save_turn()` stores arbitrarily large content — no size limit

**File:** `apex_brain/memory/conversation_store.py:41-52`

**Fix:** Truncate to 10,000 chars before storage.

---

### BUG-125: `fire_webhook` sends auth token unnecessarily to webhook endpoint

**File:** `apex_brain/tools/webhook.py:49-54`

**Problem:** `ha_request` adds `Authorization: Bearer` header. Webhooks don't need auth. Unnecessary credential exposure.

**Fix:** Add a `skip_auth=True` parameter to `ha_request` for webhook calls.

---

## FALSE POSITIVES REJECTED FROM EARLIER DRAFT

These were in the previous version of this file but are NOT bugs:

1. **"Shutdown leaks scheduler/event_subscriber"** — The shutdown code after `yield` uses local variables from the same scope (not module globals). Shutdown works correctly. Only `/health` is affected (BUG-95).
2. **"do() flat payload merge"** — HA REST API is designed for flat payloads. `entity_id` collision is an LLM error, not a code bug.
3. **"Tool name collisions silently overwrite"** — Deterministic behavior (last wins). Enhancement, not a bug.
4. **"Webhook secret in body vs header"** — Design choice. Functional. HA automations commonly pass data in body.

---

## TEST COVERAGE GAPS

| # | Gap | Severity |
|---|-----|----------|
| GAP-1 | `ConversationStore` — ZERO tests (SQL injection in `_escape_like` untested) | HIGH |
| GAP-2 | `KnowledgeStore` — only 2-3 tests for 15+ methods | HIGH |
| GAP-3 | `Scheduler._task_reminder_check()` — entirely untested | HIGH |
| GAP-4 | `CooldownTracker` — no dedicated tests | HIGH |
| GAP-5 | Server endpoints (`/api/chat`, `/api/webhook`, `/v1/chat/completions`) — zero tests | HIGH |
| GAP-6 | `EventSubscriber` reconnection, auth failure, URL derivation — untested | MEDIUM |
| GAP-7 | `mock_embed` returns identical vectors for ALL text — semantic search ranking untested | MEDIUM |
| GAP-8 | 14 tool modules have no test files | MEDIUM |
| GAP-9 | DecisionEngine night-time scoring tests depend on wall clock — flaky | MEDIUM |

---

## Summary

| Severity | Count | Bug IDs |
|----------|-------|---------|
| CRITICAL | 3 | BUG-92, 93, 94 |
| HIGH | 8 | BUG-95 through 102 |
| MEDIUM | 17 | BUG-103 through 119 |
| LOW | 6 | BUG-120 through 125 |
| Test Gaps | 9 | GAP-1 through GAP-9 |
| **Total** | **34 bugs + 9 test gaps** | |

---

## Recommended Fix Order

### Batch 0 — Fix Prompts 4 & 5 first (BUG-59 through BUG-91)
These 33 bugs from earlier scans are still unfixed. Fix them before proceeding.

### Batch 1 — Security & Data Integrity
1. BUG-92: Security gate bypass on protected domains
2. BUG-93: Reminders never fire
3. BUG-94: SQLite transaction management + ROLLBACK safety
4. BUG-98: ha_request raises uncaught HTTPStatusError

### Batch 2 — Crash Prevention
5. BUG-95: Health endpoint missing scheduler/subscriber
6. BUG-96: List entity_id in do() verification
7. BUG-97: Addon slug path traversal
8. BUG-99: Store uninitialized guards
9. BUG-101: configure() catch-all exception
10. BUG-102: correct_fact() race condition

### Batch 3 — Correctness
11. BUG-103: Event session crosstalk
12. BUG-104: Calendar timezone
13. BUG-105: Calendar multi-day events
14. BUG-110: model_dump provider compat
15. BUG-111: Cover domain scoring

### Batch 4 — Performance & Reliability
16. BUG-106: Write lock during cosine scan
17. BUG-107: SQLite write contention
18. BUG-108: Unbounded semantic search
19. BUG-109: Supervisor client leak
20. BUG-113: Search writes during reads

---

## Verification Checklist

After all fixes:
1. `PYTHONPATH=apex_brain python3 -m pytest apex_brain/tests/ -q` — all tests pass
2. `python3 -m ruff check apex_brain/` — no lint errors
3. `python3 -m ruff format --check apex_brain/` — formatting OK
4. No secrets or tokens in any modified files
5. Each fix is minimal and focused — no surrounding refactors
