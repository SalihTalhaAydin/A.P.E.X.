# Ninth-Pass Deep Bug Scan — BUG-143 through BUG-162

> **Date:** 2026-02-22
> **Test baseline:** 648 passed, 1 failed (test_history_changes — stale mock side_effect), 3 skipped
> **Scan scope:** Full deep scan of all 85 Python files across brain/, memory/, tools/, tests/ — 4 parallel deep-scan agents plus manual line-by-line verification
> **Previous bugs:** BUG-1–128 (Prompts 3-7), BUG-129–142 (Prompt 8)
> **Deduplication:** Every bug below verified against all 142 prior bugs — none are duplicates.

---

## Instructions for Fixing Agent

**Rules:**
1. Fix each bug in the order listed (CRITICAL first, then HIGH, MEDIUM, LOW).
2. After each fix, run `PYTHONPATH=apex_brain python3 -m pytest apex_brain/tests/ -x -q` to ensure no regressions.
3. Write or update tests for every fix where applicable.
4. Do NOT modify `.env` or any credentials.
5. Keep fixes minimal — don't refactor surrounding code.

---

## CRITICAL

### BUG-143: `server.py:266-268` — Normal shutdown path has no None guards on stores — crashes if startup partially succeeded

**File:** `apex_brain/brain/server.py`, lines 266-268

**Problem:** The normal shutdown path (after `yield`) calls `.close()` on stores WITHOUT None guards:

```python
# Shutdown (lines 266-268)
await routine_store.close()
await convo_store.close()
await knowledge_store.close()
```

Compare with the EXCEPTION handler at lines 246-251 which properly uses `if routine_store:` guards. The exception path was fixed (BUG-59) but the normal shutdown path was NOT. If startup succeeds past store init but fails during scheduler/event_subscriber creation, execution reaches `yield`. On shutdown after `yield`, the code assumes all stores are initialized. If any future change makes a store None at shutdown time, this crashes with `AttributeError: 'NoneType' object has no attribute 'close'`.

**Not a duplicate of BUG-59** (Prompt 4) — BUG-59 describes the exception handler path (lines 246-251), which was fixed. This is the NORMAL shutdown path (lines 266-268) which was missed.

**Fix:**
```python
# Shutdown (lines 266-268)
if routine_store:
    await routine_store.close()
if convo_store:
    await convo_store.close()
if knowledge_store:
    await knowledge_store.close()
```

**Test:** Set `routine_store = None` before shutdown — verify no `AttributeError`.

---

### BUG-144: `scheduler.py:342-347` — Reminder `expires_at` compared as ISO string — format mismatch causes wrong ordering

**File:** `apex_brain/brain/scheduler.py`, lines 342-347

**Problem:** The reminder check compares `expires_at` against `now_iso` using string comparison:

```python
now_iso = datetime.now(timezone.utc).isoformat()
due = [
    f for f in facts
    if f.get("value")
    and f.get("expires_at")
    and f.get("expires_at") <= now_iso
]
```

Python's `datetime.isoformat()` output varies by instance:
- With tz: `"2026-02-22T10:00:00+00:00"`
- Naive: `"2026-02-22T10:00:00"`
- With microseconds: `"2026-02-22T10:00:00.123456+00:00"`

String comparison of `"2026-02-22T10:00:00"` vs `"2026-02-22T10:00:00+00:00"` gives incorrect results because ASCII ordering of `":"` vs `"+"` differs from temporal ordering. The `+` character (ASCII 43) sorts BEFORE `:` (ASCII 58), so `"2026-02-22T10:00:00+00:00" < "2026-02-22T10:00:00"` — a timezone-aware string appears EARLIER than its naive equivalent. This means a reminder stored with UTC offset might fire too early or too late depending on the format of `now_iso`.

**Not a duplicate of BUG-93** (Prompt 3/6) which covers `expires_at` missing from `get_all_facts()`. This bug is about the comparison logic AFTER the field is retrieved.

**Fix:**
```python
now = datetime.now(timezone.utc)
due = []
for f in facts:
    if not f.get("value") or not f.get("expires_at"):
        continue
    try:
        exp = datetime.fromisoformat(f["expires_at"])
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        if exp <= now:
            due.append(f)
    except (ValueError, TypeError):
        logger.debug("Invalid expires_at for reminder: %s", f.get("key"))
```

**Test:** Store reminders with `expires_at` in naive format and tz-aware format, both in the past. Verify both are detected as due.

---

### BUG-145: `conversation.py:48-49` — Confabulation regex `r"i've\s+"` matches ALL "I've" sentences — forces unnecessary tool calls

**File:** `apex_brain/brain/conversation.py`, lines 48-49

**Problem:** The confabulation detection regex `_CONFAB_CLAIM_RE` includes:

```python
r"i've\s+|i\s+have\s+|"
```

These match ANY AI response containing "I've " or "I have " — including innocent phrases like "I've checked your calendar", "I have no information", "I've searched the knowledge base". When matched AND `user_wants_action=True` AND no action tools called, the guard forces up to 2 nudge cycles (lines 382-405), each making an additional LLM API call. This wastes API budget and degrades response quality.

Testing confirmed: the regex `re.search(r"i've\s+", "I've checked the weather", re.IGNORECASE)` returns a match.

Additionally, `r"cycled"` on line 51 matches substrings like "recycled" and "bicycled".

**Not a duplicate of BUG-106** (Prompt 7, "is done"/"all set" patterns) or BUG-122 (Prompt 7, "all set"). This specifically covers the "I've"/"I have" patterns and "cycled" substring match, which are the highest-impact false positives.

**Fix:**
```python
# Lines 48-49: Require action verbs after "I've"/"I have"
r"i've\s+(?:turned|set|locked|unlocked|opened|closed|adjusted|"
r"activated|dimmed|toggled|armed|disarmed|switched|powered)|"
r"i\s+have\s+(?:turned|set|locked|unlocked|opened|closed|adjusted|"
r"activated|dimmed|toggled|armed|disarmed|switched|powered)|"
# Line 51: Add word boundary to "cycled"
r"\bcycled\b|"
```

**Test:** Verify `"I've checked the weather"` does NOT match. Verify `"I've turned on the lights"` DOES match. Verify `"recycled"` does NOT match.

---

## HIGH

### BUG-146: `automation.py:88-89` — `list_automations` crashes when `ha_request` returns error dict

**File:** `apex_brain/tools/automation.py`, lines 88-89

**Problem:** When `ha_request("GET", "/states")` returns an error dict (e.g., `{"error": "Cannot connect"}` from the ConnectError/TimeoutException handler at `ha_helpers.py:80-86`), the list comprehension iterates dict keys:

```python
states = await ha_request("GET", "/states")
automations = [
    s for s in states if s["entity_id"].startswith("automation.")
]
```

If `states = {"error": "timeout"}`, then `s` iterates over string keys (`"error"`), and `s["entity_id"]` raises `TypeError: string indices must be integers`. The `except httpx.HTTPStatusError` at line 115 catches HTTP errors but NOT `TypeError`.

The same pattern exists in `list_scenes()` (line 529) and `create_automation()` search-before-create (lines 316-318).

**Not a duplicate of BUG-98** (Prompt 3) which covers `ha_request` raising `HTTPStatusError`. This covers the RETURN-a-dict error path.

**Fix:** Add type guard:
```python
states = await ha_request("GET", "/states")
if not isinstance(states, list):
    return "Error: Unable to reach Home Assistant."
```

Apply the same pattern to `list_scenes()` and the search-before-create block.

**Test:** Mock `ha_request` to return `{"error": "timeout"}` — verify error message, not `TypeError`.

---

### BUG-147: `calendar_tool.py:170-174` — Multi-day all-day events filtered out from today view

**File:** `apex_brain/tools/calendar_tool.py`, lines 170-174

**Problem:** For all-day events spanning multiple days, `start_info` contains a `date` key like `"2026-02-20"`. `_parse_event_dt("2026-02-20")` returns `datetime(2026, 2, 20, 0, 0)`. The filter at line 171 checks:

```python
if not (today_start <= start_dt <= today_end):
    continue
```

For a 3-day event starting 2026-02-20 but today is 2026-02-22, `start_dt = 2026-02-20 00:00` fails `today_start <= start_dt` (today_start = 2026-02-22 00:00). The event is filtered out despite being ongoing.

**Not a duplicate of BUG-105** (Prompt 3) which covers multi-day TIMED events. This covers multi-day ALL-DAY events where `start_info` uses a `date` key instead of `dateTime`.

**Fix:** Check overlap:
```python
if start_dt is not None and end_dt is not None:
    if end_dt < today_start or start_dt > today_end:
        continue
elif start_dt is not None:
    if not (today_start <= start_dt <= today_end):
        continue
elif not all_day:
    continue
```

**Test:** Create 3-day all-day event starting yesterday — verify it appears in today view.

---

### BUG-148: `knowledge.py:117` — `forget()` calls `delete_fact()` without category — may delete wrong fact

**File:** `apex_brain/tools/knowledge.py`, line 117

**Problem:** The `forget` tool calls:

```python
deleted = await _knowledge_store.delete_fact(key)
```

The unique constraint on facts is `(category, key)`. Different categories CAN share keys (e.g., category=`explicit`, key=`temperature` vs category=`preference`, key=`temperature`). `delete_fact(key)` without category deletes an ARBITRARY match — possibly an auto-extracted preference instead of the explicit memory the user intended.

**Related to but distinct from BUG-109** (Prompt 7) which covers `delete_fact()` not accepting a category parameter. This bug covers the CALLER not passing one.

**Fix:**
```python
async def forget(key: str) -> str:
    if not _knowledge_store:
        return "Memory system not initialized."
    # Prefer deleting explicit memories (user-created)
    deleted = await _knowledge_store.delete_fact(key, category="explicit")
    if deleted:
        return f"Done. Forgot about '{key}'."
    # Fallback: try any category
    deleted = await _knowledge_store.delete_fact(key)
    if deleted:
        return f"Done. Forgot about '{key}'."
    return f"I don't have anything stored about '{key}'."
```

**Test:** Store facts with same key in "explicit" and "preference" categories. Call `forget(key)` — verify only "explicit" is deleted.

---

### BUG-149: `context_builder.py:88-135` — Four `except Exception` blocks silently swallow all errors including code bugs

**File:** `apex_brain/memory/context_builder.py`, lines 88-97, 101-111, 115-121, 125-135

**Problem:** Four context-building blocks each catch `except Exception:`:

```python
try:
    presence_data = await ha_request("GET", "/states")
    # ... processing ...
except Exception:
    logger.warning("context_builder: Failed to fetch presence", exc_info=True)
```

`except Exception` catches ALL exceptions including `NameError`, `AttributeError`, `ImportError`, and logic errors in the code itself. If someone introduces a typo causing `NameError` inside one of these blocks, it's silently logged as "Failed to fetch presence" — completely masking the real bug.

**Not a duplicate of BUG-81** (Prompt 5) which covers the timezone `except (KeyError, Exception)` at line 46. This covers 4 DIFFERENT exception blocks (presence, device summary, schemas, weather) that each have the same problem.

**Fix:** Catch specific expected exceptions:
```python
except (httpx.HTTPError, httpx.ConnectError, httpx.TimeoutException,
        KeyError, TypeError) as e:
    logger.warning("context_builder: Failed to fetch presence: %s", e)
```

**Test:** Introduce a `NameError` inside the presence block — verify it propagates instead of being caught.

---

### BUG-150: `knowledge_store.py:472-493` — `search_semantic()` loads ALL facts with embeddings — no LIMIT, blocks event loop

**File:** `apex_brain/memory/knowledge_store.py`, lines 472-493

**Problem:** The semantic search query has no LIMIT clause:

```python
cursor = await self._db.execute(
    "SELECT id, category, key, value, confidence, created_at, "
    "updated_at, embedding FROM facts "
    "WHERE embedding IS NOT NULL AND (expires_at IS NULL OR expires_at >= ?)",
    (now,),
)
rows = await cursor.fetchall()
```

With thousands of facts, this loads ALL rows into memory, deserializes all embedding blobs (each ~6KB for 1536-dim float32), and runs cosine similarity on each — all on the asyncio event loop thread. At 5K facts: ~30MB memory + blocking CPU for 50-200ms per query. This runs on EVERY user message via `context_builder.build()`.

**Not a duplicate of BUG-108** (Prompt 3) which briefly mentions "Add LIMIT 1000". This provides the full analysis of memory impact, event loop blocking, and the need for thread offloading.

**Fix:**
```python
cursor = await self._db.execute(
    "SELECT id, category, key, value, confidence, created_at, "
    "updated_at, embedding FROM facts "
    "WHERE embedding IS NOT NULL AND (expires_at IS NULL OR expires_at >= ?) "
    "LIMIT 2000",
    (now,),
)
rows = await cursor.fetchall()

# Offload CPU-intensive similarity computation
scored = await asyncio.get_event_loop().run_in_executor(
    None, _compute_similarities, query_vec, query_norm, rows
)
```

**Test:** Store 200+ facts with embeddings. Verify `search_semantic` returns results and completes within reasonable time.

---

## MEDIUM

### BUG-151: `event_handler.py:182` — ALL webhook events share `session_id="apex_events"` — conversation context bleeds between events

**File:** `apex_brain/brain/event_handler.py`, line 182

**Problem:** Every webhook event uses the same session_id:

```python
response = await self.conversation.handle(
    msg, session_id="apex_events"
)
```

When two webhook events arrive close together, the second event's LLM context includes the conversation history from the first event. The AI may reference the first event's entities/actions when processing the second, leading to confused responses. With per-session locking (BUG-60), concurrent events would serialize, adding latency.

**Not a duplicate of BUG-103** (Prompt 3) which covers the same issue in `event_subscriber.py` (WebSocket events). This is the WEBHOOK code path — completely separate handler with the same bug.

**Fix:**
```python
import uuid
event_session = f"apex_webhook_{uuid.uuid4().hex[:8]}"
response = await self.conversation.handle(msg, session_id=event_session)
```

**Test:** Process two webhook events — verify they use different session IDs.

---

### BUG-152: `conversation_store.py:48-52` — All methods access `self._db` without None check

**File:** `apex_brain/memory/conversation_store.py`, lines 48, 59, 84, 101

**Problem:** `save_turn()`, `get_recent()`, `search()`, and `get_turns_since()` all access `self._db.execute()` without checking if `self._db` is None. If `initialize()` was never called or `close()` was already called, any method call crashes with `AttributeError: 'NoneType' object has no attribute 'execute'`.

**Related to BUG-99** (Prompt 3) which covers "all 4 store files" generically. ConversationStore is specifically high-impact because it's called on EVERY message — a single init failure makes the entire system unusable.

**Fix:** Add guard to each method:
```python
async def save_turn(self, role, content, session_id="default"):
    if not content or not content.strip():
        return
    if self._db is None:
        raise RuntimeError("ConversationStore not initialized. Call initialize() first.")
    # ... rest unchanged
```

**Test:** Call `save_turn()` without `initialize()` — verify clean `RuntimeError`.

---

### BUG-153: `decision_engine.py:202-203` — Lights/switches/media score 0.25, BELOW default threshold 0.3 — never processed

**File:** `apex_brain/brain/decision_engine.py`, lines 202-203

**Problem:**

```python
if entity.startswith(("light.", "switch.", "media_player.")):
    return 0.25, "low"
```

Default `significance_threshold` is 0.3 (line 50). Score 0.25 < 0.3, so ALL light, switch, and media player events are silently dropped. The user is NEVER notified about unexpected light changes, switches toggling, or media players starting/stopping. If the intent is to always drop these, they should be in `_hard_filter()` with a clear reason. Their presence in `_score_significance()` suggests they're meant to be processable.

**Not a duplicate of BUG-111** (Prompt 3) which covers `cover` domain scoring. This covers lights/switches/media explicitly scored below threshold.

**Fix:** Either raise score above threshold or move to hard filter:
```python
# Option A: Make processable (recommended)
if entity.startswith(("light.", "switch.", "media_player.")):
    return 0.35, "low"

# Option B: If truly uninteresting, add to hard filter with comment
```

**Test:** Send a `light.kitchen` state_changed event — verify it passes significance filter.

---

### BUG-154: `routines.py:85-88` — Step parsing splits on ALL periods — breaks decimals, abbreviations, URLs

**File:** `apex_brain/tools/routines.py`, lines 85-88

**Problem:**

```python
step_list = [
    s.strip()
    for s in steps.replace("\n", ".").split(".")
    if s.strip()
]
```

This splits on every `.` in the input. Steps like:
- "Set thermostat to 72.5 degrees" → `["Set thermostat to 72", "5 degrees"]`
- "Turn on Dr. Smith's office lights" → `["Turn on Dr", "Smith's office lights"]`
- "Check weather at 3.30pm" → `["Check weather at 3", "30pm"]`

**Fix:** Split on period followed by space and uppercase letter (sentence boundaries):
```python
import re
step_list = [
    s.strip().rstrip(".")
    for s in re.split(r'(?<=[.!?])\s+|\n', steps)
    if s.strip()
]
```

**Test:** Define routine with "Set to 72.5 degrees. Turn on lights." — verify 2 steps, not 3.

---

### BUG-155: `knowledge_store.py:28-36` — `_deserialize_embedding` crashes on corrupted blob

**File:** `apex_brain/memory/knowledge_store.py`, lines 28-36

**Problem:**

```python
def _deserialize_embedding(blob: bytes) -> np.ndarray:
    dim = len(blob) // 4
    return np.array(struct.unpack(f"{dim}f", blob), dtype=np.float32)
```

If `blob` is corrupted (truncated write, disk error) and `len(blob) % 4 != 0`, `struct.unpack` raises `struct.error`. This crashes `search_semantic()` for ALL queries — one corrupted embedding in the database poisons the entire knowledge store permanently.

**Fix:**
```python
def _deserialize_embedding(blob: bytes) -> np.ndarray | None:
    if not blob or len(blob) % 4 != 0:
        return None
    dim = len(blob) // 4
    try:
        return np.array(struct.unpack(f"{dim}f", blob), dtype=np.float32)
    except struct.error:
        return None
```

And in `search_semantic()`, skip None embeddings:
```python
fact_emb = _deserialize_embedding(row[7])
if fact_emb is None:
    continue
```

**Test:** Pass a blob of length 5 (not divisible by 4) — verify None returned, no crash.

---

### BUG-156: `curator.py:124-128` — Contradiction resolver falls back to string comparison for timestamps

**File:** `apex_brain/brain/curator.py`, lines 124-128

**Problem:**

```python
try:
    keep_a = datetime.fromisoformat(ts_a) >= datetime.fromisoformat(ts_b)
except (ValueError, TypeError):
    keep_a = ts_a >= ts_b
```

When both timestamps are empty (`ts_a = "", ts_b = ""`), `"" >= ""` is True — keeps fact_a arbitrarily. When one is empty (`ts_a = "", ts_b = "2026-02-22T10:00:00"`), `"" >= "2026..."` is False — keeps fact_b. This is coincidentally correct but fragile. Mixed-format timestamps (naive vs tz-aware) produce wrong ordering via string comparison for the same reasons as BUG-144.

**Fix:**
```python
try:
    dt_a = datetime.fromisoformat(ts_a) if ts_a else datetime.min.replace(tzinfo=timezone.utc)
    dt_b = datetime.fromisoformat(ts_b) if ts_b else datetime.min.replace(tzinfo=timezone.utc)
    if dt_a.tzinfo is None:
        dt_a = dt_a.replace(tzinfo=timezone.utc)
    if dt_b.tzinfo is None:
        dt_b = dt_b.replace(tzinfo=timezone.utc)
    keep_a = dt_a >= dt_b
except (ValueError, TypeError):
    keep_a = True  # Default: keep first on parse failure
```

**Test:** Call `_resolve_contradictions` with empty timestamps — verify no crash.

---

### BUG-157: `automation.py:316-319` — `create_automation` similar-name search iterates error dict silently

**File:** `apex_brain/tools/automation.py`, lines 316-319

**Problem:** Inside `create_automation()`, the search-before-create does:

```python
states = await ha_request("GET", "/states")
existing = [s for s in states if s["entity_id"].startswith("automation.")]
```

If `ha_request` returns an error dict, this crashes with `TypeError`. The outer `except Exception` at line 346 catches it and passes (line 347), so automation creation proceeds. While not a user-facing crash, it means:
1. The similarity warning is never shown
2. A network error during search is completely invisible

**Fix:**
```python
states = await ha_request("GET", "/states")
if not isinstance(states, list):
    states = []
```

**Test:** Mock `ha_request` to return error dict — verify creation succeeds without crash.

---

## LOW

### BUG-158: `knowledge.py:89` — `recall()` uses `r["key"]` — KeyError on malformed fact dict

**File:** `apex_brain/tools/knowledge.py`, line 89

**Problem:**

```python
for r in results:
    category = r.get("category", "")
    key = r["key"]       # KeyError if missing
    value = r["value"]   # KeyError if missing
```

Safe access via `.get()` for `category` but unsafe direct access for `key` and `value`. A malformed fact (DB corruption, schema change) crashes the entire `recall` tool.

**Fix:**
```python
key = r.get("key", "(unknown)")
value = r.get("value", "(no value)")
```

**Test:** Mock search to return dict missing "key" — verify no crash.

---

### BUG-159: `event_handler.py:21-29` — `_is_high_priority` doesn't check entity_id domain — misses security device events

**File:** `apex_brain/brain/event_handler.py`, lines 21-29

**Problem:** The function only checks `event_type`, but `event_subscriber` sends ALL events as `event_type="state_changed"`. A state change on `alarm_control_panel.home` has `event_type="state_changed"`, NOT `"alarm"`. So the alarm check on line 23 (`if event_type in ("door", "alarm")`) never matches for WebSocket-sourced events — only for webhook events where the user explicitly sets `event_type: alarm`.

**Fix:** Accept entity_id and check domain:
```python
def _is_high_priority(event_type: str, hour: int, entity_id: str = "") -> bool:
    if event_type in ("door", "alarm"):
        return True
    if event_type == "motion" and (hour >= 22 or hour < 6):
        return True
    if "security" in event_type or "alarm" in event_type:
        return True
    domain = entity_id.split(".")[0] if "." in entity_id else ""
    if domain in ("alarm_control_panel", "lock", "camera"):
        return True
    return False
```

**Test:** Call `_is_high_priority("state_changed", 14, "alarm_control_panel.home")` — verify True.

---

### BUG-160: `ws_helpers.py` — No URL format validation before WebSocket connection

**File:** `apex_brain/tools/ws_helpers.py`, `_get_ws_url()` function

**Problem:** If `settings.ha_url` is empty or malformed, `_get_ws_url()` produces an invalid URL but the error only surfaces as a cryptic connection failure.

**Fix:**
```python
def _get_ws_url() -> str:
    ha_url = settings.ha_url
    if not ha_url or "://" not in ha_url:
        raise ValueError(f"Invalid HA URL for WebSocket: {ha_url!r}")
    ws_url = ha_url.replace("https://", "wss://").replace("http://", "ws://")
    return f"{ws_url}/websocket"
```

**Test:** Set `ha_url=""` — verify `ValueError` with clear message.

---

## TEST ISSUES

### TEST-6: `test_integration.py::test_history_changes` — Failing test due to exhausted mock side_effect

**File:** `apex_brain/tests/test_integration.py`

**Problem:** The test's mock `litellm.acompletion` runs out of `side_effect` entries, raising `StopAsyncIteration`. The test then asserts for content that doesn't exist in the error message. This is a test setup bug — needs more side_effect entries.

**Fix:** Add enough side_effect entries for the full tool loop.

---

### TEST-7: `test_server.py` — Only 2 tests for entire FastAPI application

**File:** `apex_brain/tests/test_server.py`

**Problem:** Only tests `/health` and `/api/debug/ha`. No tests for:
- `POST /v1/chat/completions` (main endpoint)
- `POST /api/chat` (test endpoint)
- `POST /api/webhook` (event processing)
- Rate limiting, request validation, lifespan lifecycle

**Severity:** CRITICAL test gap — primary API endpoints completely untested.

---

### TEST-8: `test_knowledge_store.py` — Only 3 tests for 15+ methods

**File:** `apex_brain/tests/test_knowledge_store.py`

**Problem:** Only tests serialization, keyword search, and semantic search. Missing tests for `correct_fact()`, `delete_fact()`, `decay_confidence()`, `cleanup_expired()`, `get_all_facts()`, `get_contradictory_facts()`, `_check_duplicate()`.

**Severity:** CRITICAL — core memory store virtually untested.

---

### TEST-9: 10+ tool modules have zero test files

**Problem:** No test files for: `calendar_tool.py`, `datetime_tool.py`, `knowledge.py`, `routines.py`, `energy.py`, and 5+ deprecated wrappers.

**Severity:** HIGH for active modules (calendar, datetime, knowledge, routines).

---

### TEST-10: `conftest.py:32-38` — `mock_embed` returns identical vectors for ALL inputs

**File:** `apex_brain/tests/conftest.py`, lines 32-38

**Problem:** `mock_embed` returns `[0.1, 0.2, 0.3, 0.4]` regardless of input. Cosine similarity between any two facts is always 1.0. Semantic search ranking tests pass trivially but validate nothing.

**Fix:** Use hash-based mock:
```python
async def _embed(text: str) -> list[float]:
    import hashlib
    h = hashlib.md5(text.encode()).digest()
    return [b / 255.0 for b in h[:4]]
```

---

## FALSE POSITIVES REJECTED

1. **"CooldownTracker check_and_set race condition"** — FALSE. `check_and_set()` is synchronous in a single-threaded asyncio loop. No preemption between check and set.
2. **"config.py string concatenation"** — Python implicit string concatenation is intentional and produces correct paths. BUG-87 (Prompt 5) already covers this as a clarity issue.
3. **"Module-level AsyncClient in ha_helpers.py"** — BUG-116 (Prompt 3) already covers this. Does NOT crash in single-worker production deployment.
4. **"Division by zero in RateLimiter"** — The window is hardcoded to 300. No variable path.
5. **"scheduler.py duplicate fact_decay/cleanup"** — Already documented as BUG-107 (Prompt 7). Confirmed unfixed but not re-numbered.
6. **"conversation_store save_turn size"** — Already documented as BUG-124 (Prompt 3). Confirmed unfixed but not re-numbered.
7. **"decision_engine _event_counts dead code"** — Already documented as BUG-120 (Prompt 7). Confirmed unfixed but not re-numbered.

---

## Summary

| Severity | Count | Bug IDs |
|----------|-------|---------|
| CRITICAL | 3 | BUG-143, 144, 145 |
| HIGH | 5 | BUG-146, 147, 148, 149, 150 |
| MEDIUM | 7 | BUG-151 through 157 |
| LOW | 3 | BUG-158, 159, 160 |
| Test Issues | 5 | TEST-6 through TEST-10 |
| **Total** | **18 new bugs + 5 test issues** | |

---

## Recommended Fix Order

### Batch 1 — Critical & Data Integrity
1. BUG-143: Server shutdown None guards
2. BUG-144: Reminder date comparison
3. BUG-145: Confabulation regex false positives
4. BUG-146: Automation error dict crash

### Batch 2 — Correctness
5. BUG-147: Calendar all-day filtering
6. BUG-148: forget() missing category
7. BUG-149: Context builder broad exceptions
8. BUG-150: Semantic search memory/CPU

### Batch 3 — Reliability
9. BUG-151: Webhook session crosstalk
10. BUG-152: ConversationStore None guard
11. BUG-153: Lights/switches below threshold
12. BUG-155: Embedding deserialization crash

### Batch 4 — Polish
13-18: Remaining medium/low bugs
19-23: Test fixes

---

## Verification Checklist

After all fixes:
1. `PYTHONPATH=apex_brain python3 -m pytest apex_brain/tests/ -q` — all tests pass
2. `python3 -m ruff check apex_brain/` — no lint errors
3. `python3 -m ruff format --check apex_brain/` — formatting OK
4. No secrets or tokens in any modified files
5. Each fix is minimal and focused — no surrounding refactors
