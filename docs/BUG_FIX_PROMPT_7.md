# Seventh-Pass Bug Fix Prompt — Remaining Bugs

> **Date:** 2026-02-22
> **Test baseline:** 660 passed, 1 pre-existing failure, 3 skipped
> **Previous bugs:** BUG-1 through BUG-103 from scans 1–6 (PROMPT_3/4/5/6)
> **Fixed this session:** BUG-104, BUG-105, BUG-106, BUG-107, BUG-108, BUG-109, BUG-110, BUG-111, BUG-113, BUG-115

---

## Instructions for Fixing Agent

**Rules:**
1. Fix each bug in the order listed (MEDIUM first, then LOW).
2. After each fix, run `PYTHONPATH=apex_brain python3 -m pytest apex_brain/tests/ -x -q` to ensure no regressions.
3. Write or update tests for every fix where applicable.
4. Do NOT modify `.env` or any credentials.
5. Keep fixes minimal — don't refactor surrounding code.

---

## MEDIUM SEVERITY BUGS

### BUG-112: `manage.py:383-385` — `as_text` error check never matches — errors displayed as log content

**File:** `apex_brain/tools/manage.py`, lines 383-385

**Problem:** After `_supervisor_request("GET", path, as_text=True)`, the code checks `isinstance(result, dict) and "error" in result`. But `as_text=True` returns a plain string on error (line 114: `return f"Error fetching text: HTTP {response.status_code}"`), never a dict. Errors are displayed as log content.

**Fix:**

```python
result = await _supervisor_request("GET", path, as_text=True)
if isinstance(result, str) and result.startswith("Error fetching text:"):
    return result
if isinstance(result, dict) and "error" in result:
    return result["error"]
```

**Test:** Mock 401 response with `as_text=True` → verify error returned, not treated as log.

---

### BUG-114: `event_handler.py:172-189` — `high_priority` computed but announcements never triggered

**File:** `apex_brain/brain/event_handler.py`, lines 172-189

**Problem:** `_is_high_priority()` determines priority but only populates `actions_taken` in the webhook response. No TTS/announcement is triggered despite `announce_on_events` and `announce_target` being configurable in `config.py`. The feature silently does nothing.

**Fix:** Trigger announcements:

```python
if is_high_priority and settings.announce_on_events:
    try:
        from tools.notify import announce
        await announce(target=settings.announce_target, message=f"Alert: {event_msg}")
    except Exception as e:
        logger.warning("High-priority announcement failed: %s", e)
```

**Test:** Trigger high-priority event → verify `announce()` is called.

---

### BUG-116: `vacuum.py:595-619` — `_match_rooms` returns mixed `int|str` list

**File:** `apex_brain/tools/vacuum.py`, lines 595-619

**Problem:** When `int(seg_id)` fails (line 611-613), the raw string is appended to `matched_ids: list[int]`. Type annotation promises `list[int]` but delivers `list[int | str]`. Downstream Roborock service may reject mixed-type segment lists.

**Fix:** Keep all as strings (Roborock handles both):

```python
matched_ids: list[str] = []
# ...
matched_ids.append(str(seg_id))
```

**Test:** Mock room list with non-numeric segment IDs → verify graceful handling.

---

### BUG-117: `notify.py:65` — `replace("notify.", "", 1)` doesn't anchor to start

**File:** `apex_brain/tools/notify.py`, line 65

**Problem:** `entity_id.replace("notify.", "", 1)` removes the first occurrence of `"notify."` ANYWHERE in the string, not just at the start. A malformed ID like `"bad.notify.something"` would produce `"bad.something"`.

**Fix:**

```python
if entity_id.startswith("notify."):
    service_name = entity_id[len("notify."):]
else:
    service_name = entity_id
```

**Test:** Pass `"bad.notify.foo"` → verify it's kept as-is, not mangled.

---

### BUG-118: `todo.py:120-146` — Name-based item matching may fail on newer HA todo integrations

**File:** `apex_brain/tools/todo.py`, lines 120-146

**Problem:** Uses `"item": item` (name-based matching) for update/remove. Newer HA versions and some todo integrations require UID-based identification. Complete and remove operations may silently fail.

**Fix:** For robustness, resolve name to UID before update/remove by reading the entity state:

```python
items_resp = await ha_request("GET", f"/states/{entity_id}")
if isinstance(items_resp, dict) and "attributes" in items_resp:
    for i in items_resp["attributes"].get("items", []):
        if i.get("summary", "").lower() == item.lower():
            item = i.get("uid", item)
            break
```

**Test:** Mock todo entity with UID-based items → verify complete uses UID.

---

### BUG-119: `smart_home.py:879-932` — `control_area` hidden but provides unique area-name resolution

**File:** `apex_brain/tools/smart_home.py`, lines 879-932

**Problem:** `control_area` provides area-name-to-area_id fuzzy matching ("basement" → area_id). `do()` requires the caller to already know the `area_id`. Hiding `control_area` means the LLM can't handle "turn off lights in the basement" without first calling `discover(what='areas')` — a UX regression.

**Fix:** Either un-hide `control_area` (remove from `DEPRECATED_TOOLS`) OR add area-name resolution to `do()` when `targets` contains a human-friendly `area_id` value.

**Test:** Verify "turn off lights in the office" resolves the area correctly.

---

## LOW SEVERITY BUGS

### BUG-120: `decision_engine.py:59` — `_event_counts` dict initialized but never used

**File:** `apex_brain/brain/decision_engine.py`, line 59

**Problem:** `self._event_counts: dict[str, int] = defaultdict(int)` is dead code. Never read or written.

**Fix:** Remove the line.

---

### BUG-121: `decision_engine.py:128-139` — Cooldown cleanup only runs on pass, not on fail

**File:** `apex_brain/brain/decision_engine.py`, lines 128-139

**Problem:** `_cleanup_cooldowns()` only called when a check passes. Under floods of events all failing cooldown, expired entries are never cleaned up.

**Fix:** Call cleanup unconditionally at the start of `_check_cooldown()`.

---

### BUG-122: `conversation.py:46` — `"all\s+set"` matches normal conversation

**File:** `apex_brain/brain/conversation.py`, line 46

**Problem:** `r"all\s+set"` matches "You're all set for tomorrow" — a common non-action phrase.

**Fix:** Require action context: `r"(?:it's|that's)\s+all\s+set"`.

---

### BUG-123: `ha_helpers.py:87-93` — Double error logging (log then raise)

**File:** `apex_brain/tools/ha_helpers.py`, lines 87-93

**Problem:** HTTP errors are `logger.error()`'d then `response.raise_for_status()` re-raises, causing callers to log the same error again. Every HA API error produces duplicate log entries.

**Fix:** Remove the `logger.error()` call — let the caller handle it.

---

### BUG-124: `generic.py:478` — Non-standard `__import__("re")` usage

**File:** `apex_brain/tools/generic.py`, line 478

**Problem:** `_ENTITY_RE = __import__("re").compile(...)` bypasses static analysis. Use normal `import re`.

**Fix:** Add `import re` at the top of the file; use `re.compile(...)`.

---

### BUG-125: `configure.py:139-144` — `disabled_by: None` in WebSocket payload

**File:** `apex_brain/tools/configure.py`, lines 139-144

**Problem:** Sends `"disabled_by": None` in WebSocket command. HA docs specify `"disabled_by": ""` (empty string) to clear the disabled state. JSON `null` vs `""` behavior may change.

**Fix:** Use `"disabled_by": ""`.

---

### BUG-126: `knowledge_store.py:164-178` — `_check_duplicate` only checks 200 most recent facts

**File:** `apex_brain/memory/knowledge_store.py`, lines 164-178

**Problem:** Duplicate check uses `LIMIT 200`. Categories with 200+ facts will slowly accumulate semantic duplicates.

**Fix:** Increase limit to 1000 or remove it (rely on the embedding index).

---

### BUG-127: `generic.py:84-86` — `filter` parameter shadows Python built-in

**File:** `apex_brain/tools/generic.py`, lines 84-86

**Problem:** `discover(what, filter="")` shadows Python's built-in `filter()`. Triggers linter warnings and may confuse developers.

**Fix:** Rename to `filter_str` or `name_filter`.

---

### BUG-128: `context_builder.py:74-84` — Core facts appended without relevance check

**File:** `apex_brain/memory/context_builder.py`, lines 74-84

**Problem:** High-confidence core facts are appended after semantically relevant facts, but if `relevant_facts` already reached `max_facts` from the semantic search, NO core facts are added. The loop at line 78 checks `len(relevant_facts) >= self.max_facts` and breaks immediately.

This means high-confidence facts (confidence >= 0.9) — the most important user knowledge — can be entirely excluded if the semantic search filled the quota with lower-confidence but higher-similarity results.

**Fix:** Reserve slots for core facts:

```python
core_reserve = min(5, self.max_facts // 4)
# Limit semantic results to leave room
semantic_limit = self.max_facts - core_reserve
relevant_facts = results[:semantic_limit]
# Then add core facts up to core_reserve
```

**Test:** Fill semantic results to max → verify core facts still appear.

---

## Summary

| Severity | Count | Bug IDs |
|----------|-------|---------|
| MEDIUM | 6 | BUG-112, BUG-114, BUG-116, BUG-117, BUG-118, BUG-119 |
| LOW | 9 | BUG-120 through BUG-128 |
| **Total** | **15 remaining bugs** | |

---

## Verification Checklist

After all fixes:
1. `PYTHONPATH=apex_brain python3 -m pytest apex_brain/tests/ -q` — all tests pass
2. `python3 -m ruff check apex_brain/` — no lint errors
3. `python3 -m ruff format --check apex_brain/` — formatting OK
4. No secrets or tokens in any modified files
5. Each fix is minimal and focused — no surrounding refactors
