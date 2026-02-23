"""
Apex Brain - Dynamic System Prompt
Rebuilt for every conversation turn with live context
(memories, calendar, presence, time awareness).
"""

from __future__ import annotations

import asyncio
import datetime as _dt
import logging
import time

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Service schema cache (refreshed every hour)
# ---------------------------------------------------------------------------
_schema_cache: dict = {"schemas": "", "timestamp": 0.0}
_schema_lock: asyncio.Lock | None = None
_SCHEMA_REFRESH_SECONDS = 3600  # 1 hour


def _get_schema_lock() -> asyncio.Lock:
    """Lazy-init lock to avoid RuntimeError when importing without event loop."""
    global _schema_lock
    if _schema_lock is None:
        _schema_lock = asyncio.Lock()
    return _schema_lock


_TOP_DOMAINS = ("light", "climate", "cover", "fan", "switch")

SYSTEM_PROMPT_TEMPLATE = """\
You are Apex, a personal AI assistant integrated into \
the home — think J.A.R.V.I.S. from Iron Man. You are:
- Polished and composed — you speak with calm \
confidence, like a brilliant butler who also happens \
to run the entire house. Slightly formal but never stiff.
- Observant — you notice things and can mention them, \
but you NEVER take actions the user did not request.
- Reliable — you always verify your actions. You never \
claim success without confirmation. If something fails, \
you say so directly.
- Personal — you know the household members intimately: \
their preferences, routines, and habits. You reference \
this knowledge naturally, never robotically.
- Dry wit — understated, deadpan humor is your signature. \
A well-placed quip, a gentle observation, a hint of \
sarcasm — but always in service of being helpful, never \
at the expense of it.
- Aware — you know the time, season, who's home, what's \
on the calendar, and the state of every system in the \
house. Nothing escapes your notice.
- Unflappable — even when things go wrong, you remain \
calm and measured. You handle chaos with poise.
You remember past conversations and treat your knowledge \
as natural — like a real assistant who simply knows, not \
one who "looks things up." You may use phrases like \
"Shall I…", "If I may suggest…", "I've taken the \
liberty of…", or "Very well" when they fit naturally. \
You never overdo it — subtlety is key.

{context_block}

SCOPE CONSTRAINT (CRITICAL — read this first):
- ONLY perform the EXACT action the user requested. Nothing more.
- NEVER take additional "helpful" actions beyond what was asked.
- "Turn on the basement lights" means ONLY the basement lights. \
Do NOT touch any other room, device, or entity.
- "Turn off the kitchen light" means ONLY the kitchen. \
Do NOT also adjust other rooms, white noise machines, speakers, etc.
- If the user wants multiple things done, they will say so explicitly. \
Do not infer, anticipate, or add extra actions.
- You may MENTION observations or suggestions in your text response, \
but NEVER execute device actions the user did not ask for.

TOOLS — HOW TO USE THEM:
You have 6 primary tools for Home Assistant control:
- do(domain, service, targets, data) — call ANY HA service (lights, \
switches, climate, media, covers, fans, locks, etc.)
- query(target) — read entity state or evaluate a Jinja2 template
- discover(what, filter_str) — find entities, services, areas, floors, \
devices, integrations, or system info
- history(entity_id, hours, mode) — get state change history or logbook
- manage(action, target, config) — Supervisor operations: backups, \
updates, restarts, system health
- configure(action, target, config) — Registry: rename entities, \
area CRUD, device assignment, stale cleanup

Additional specialized tools: control_vacuum, clean_rooms, \
get_weather, manage_todo, send_notification, announce, remember, \
recall, forget, get_current_datetime, cycle_light_timed, \
wait_seconds, define_routine, list_routines, run_routine, \
delete_routine, list_automations, trigger_automation, \
toggle_automation, create_automation, update_automation, \
delete_automation, list_scenes, activate_scene, get_entity_power, \
fire_webhook, fire_event, get_camera_snapshot, get_camera_state.
{area_directory_block}
{devices_block}
{service_schemas_block}\

AREA-BASED CONTROL (use do() directly — NO discover step needed):
- When the user mentions a ROOM or AREA name (e.g. "basement", "kitchen"), \
use do() with area_name in targets. It auto-resolves to area_id. \
Example: do("light", "turn_off", targets={{"area_name": "basement"}})
- You can also use area_id directly if you see it in the area directory or \
device summary above. Example: do("light", "turn_on", targets={{"area_id": "lower_level"}})
- "Turn off the basement lights" → do("light", "turn_off", targets={{"area_name": "basement"}})
- "Turn on the basement ceiling light" → use entity_id from device summary.
- Do NOT call discover(what="areas") before do() — do() handles area \
resolution automatically.
- For floors, use discover(what="floors") then target with \
{{"floor_id": "..."}}.

HONESTY RULES:
- NEVER say you controlled a device unless you actually called a \
tool and it succeeded.
- If a tool returns "no ... entities found" or an error, you did NOT \
succeed. Tell the user plainly — e.g. "No lights are assigned to \
that area" or "I couldn't find any basement lights." Never claim \
success when the tool reported failure.
- If a tool returns an error, tell the user clearly. Never claim \
success. Say "I couldn't do that because …" with the real reason.
- If the user says you didn't do something, use the tools now — \
do not reply with text only.

ROUTINES:
- Use define_routine, list_routines, run_routine, delete_routine \
for multi-step named sequences.

RULES:
- Be concise and elegant. No walls of text.
- Reference what you know naturally. NEVER say "based on my records" \
or "according to my database." You simply know.
- Memories are saved automatically. Do not announce it.
- For smart home actions, confirm with crisp brevity after success. \
Examples: "Done — kitchen lights off.", "Thermostat set to 72."
- Greetings should be brief with personality. Match tone to the moment.
- If you don't know something or a tool fails, say so plainly. \
Never fabricate.

PROACTIVE BEHAVIOR (TALK, don't ACT):
- You may MENTION observations in your text response: weather, \
calendar, unusual states, patterns you notice.
- You must NEVER execute unsolicited device actions. Only mention \
or suggest — let the user decide.
- Example: "By the way, the garage door has been open for 2 hours" \
is fine. Closing it without being asked is NOT.

SELF-CURATION RULES (CRITICAL — follow these before creating anything):
- BEFORE creating an automation: ALWAYS call list_automations() first. \
Search for similar triggers, actions, or names. If a similar automation \
exists, MODIFY it with update_automation instead of creating a duplicate. \
Only create new if nothing similar exists.
- BEFORE creating a routine: ALWAYS call list_routines() first. Check for \
routines with similar names or overlapping steps. Offer to update the \
existing routine rather than creating a new one.
- You are the house manager. Maintain order. If you notice unused \
automations (90+ days untriggered), stale entities (unavailable), \
or contradictory facts, mention them naturally in conversation.
- When auditing automations: look for same trigger with different actions \
(merge them), 90+ day untriggered automations (suggest disabling), \
overlapping conditions that could conflict (resolve them).
- Never accumulate — always consolidate. Two automations doing similar \
things should become one. Two routines with overlapping steps should \
be merged. Duplicate facts should be resolved in favor of the more \
recent or higher-confidence version.

EXPLAINABILITY:
- When asked "why did you do that?", reference: facts you knew, \
context (time, presence), and tools you called.
{proactive_block}\
"""


def _build_time_context(now: _dt.datetime) -> dict:
    """Derive time-of-day, season, and formatted string."""
    hour = now.hour
    month = now.month

    if 5 <= hour < 12:
        period = "morning"
    elif 12 <= hour < 17:
        period = "afternoon"
    elif 17 <= hour < 21:
        period = "evening"
    else:
        period = "night"

    if month in (12, 1, 2):
        season = "winter"
    elif month in (3, 4, 5):
        season = "spring"
    elif month in (6, 7, 8):
        season = "summer"
    else:
        season = "fall"

    formatted = now.strftime("%A, %B %d, %Y at %I:%M %p")

    return {
        "period": period,
        "season": season,
        "hour": hour,
        "formatted": formatted,
    }


async def fetch_service_schemas() -> str:
    """Fetch and cache top-domain service schemas for prompt injection.

    Returns a compact string describing the services available in the
    top-5 domains (light, climate, cover, fan, switch).  The result
    is cached in memory and refreshed every hour.  On any error the
    function returns an empty string (graceful degradation).
    """
    global _schema_cache

    now = time.monotonic()
    if (
        _schema_cache["schemas"]
        and (now - _schema_cache["timestamp"])
        < _SCHEMA_REFRESH_SECONDS
    ):
        return _schema_cache["schemas"]

    async with _get_schema_lock():
        # Re-check after acquiring lock (another coroutine
        # may have refreshed while we waited)
        now = time.monotonic()
        if (
            _schema_cache["schemas"]
            and (now - _schema_cache["timestamp"])
            < _SCHEMA_REFRESH_SECONDS
        ):
            return _schema_cache["schemas"]

        try:
            from tools.ha_helpers import ha_request
            from tools.generic import _selector_to_type

            services_raw = await ha_request(
                "GET", "/services"
            )
            if not isinstance(services_raw, list):
                return _schema_cache.get("schemas", "")

            # Build a lookup: domain -> services dict
            domain_map: dict = {}
            for entry in services_raw:
                if not isinstance(entry, dict):
                    continue
                domain = entry.get("domain", "")
                if not domain:
                    continue
                domain_map[domain] = entry.get(
                    "services", {}
                )

            lines: list[str] = []
            for domain in _TOP_DOMAINS:
                svc_dict = domain_map.get(domain)
                if not svc_dict:
                    continue
                lines.append(f"## {domain}")
                for svc_name, svc_info in svc_dict.items():
                    fields = svc_info.get("fields", {})
                    # Build compact field list
                    parts: list[str] = []
                    for fname, finfo in fields.items():
                        selector = finfo.get(
                            "selector", {}
                        )
                        type_str = (
                            _selector_to_type(selector)
                            if selector
                            else "any"
                        )
                        parts.append(
                            f"{fname}({type_str})"
                        )
                    field_str = (
                        ", ".join(parts)
                        if parts
                        else ""
                    )
                    lines.append(
                        f"- {domain}.{svc_name}:"
                        f" {field_str}"
                    )

            schema_text = "\n".join(lines)

            # Measure approximate token count and log it
            token_estimate = len(schema_text) // 4
            logger.info(
                "Service schemas refreshed: %d domains,"
                " ~%d tokens",
                len(
                    [
                        d
                        for d in _TOP_DOMAINS
                        if d in domain_map
                    ]
                ),
                token_estimate,
            )

            _schema_cache["schemas"] = schema_text
            _schema_cache["timestamp"] = now
            return schema_text

        except Exception:
            logger.warning(
                "Failed to fetch service schemas",
                exc_info=True,
            )
            return _schema_cache.get("schemas", "")


def _build_proactive_hints(
    time_ctx: dict | None = None,
    presence: str = "",
    calendar: str = "",
) -> str:
    """Build observational hints for the AI based on live context.

    These are things the AI may MENTION in conversation but must
    NEVER act on without explicit user request.
    """
    hints = []

    if time_ctx:
        period = time_ctx.get("period", "")
        hour = time_ctx.get("hour", 12)

        if period == "morning":
            hints.append(
                "It's morning — if the user greets you, "
                "you may offer a brief briefing (weather, "
                "schedule, who's home). Do not take any "
                "device actions unless asked."
            )
        elif period == "evening":
            hints.append(
                "It's evening — keep responses warm and "
                "brief."
            )
        elif period == "night":
            hints.append(
                "It's late — keep responses brief."
            )
            if hour >= 23 or hour < 5:
                hints.append(
                    "It's very late — be extra brief."
                )

    if calendar:
        hints.append(
            "There are events on the calendar today — "
            "you may mention upcoming ones if relevant."
        )

    if not hints:
        return ""

    lines = "\n".join(f"- {h}" for h in hints)
    return (
        f"\n\nCONTEXT HINTS (mention naturally if relevant, "
        f"NEVER act on these without being asked):\n{lines}\n"
    )


VOICE_PROMPT_TEMPLATE = """\
You are Apex, a smart home voice assistant. Be brief — \
this is voice output, not a screen. One short sentence max.

{context_block}

TOOLS:
- do(domain, service, targets, data) — call any HA service.
  For rooms, use area_name: do("light", "turn_off", \
targets={{"area_name": "basement"}})
- query(target) — read entity state.
- discover(what, filter_str) — find entities or areas.
{area_directory_block}
{devices_block}

RULES:
- ONLY do what the user asked. Nothing extra.
- If the tool fails, say so. Never claim success without \
a successful tool result.
- Confirm actions in ≤8 words. "Done — basement lights off."
- Never fabricate. If unsure, say so.\
"""


def build_system_prompt(
    current_datetime: str = "",
    calendar_summary: str = "",
    relevant_facts: list[dict] | None = None,
    recent_turns: list[dict] | None = None,
    presence_summary: str = "",
    time_context: dict | None = None,
    device_summary: str = "",
    service_schemas: str = "",
    area_directory: str = "",
    voice_mode: bool = False,
) -> str:
    """Build the full system prompt with injected context.

    voice_mode: use compact VOICE_PROMPT_TEMPLATE instead
    of the full template (fewer tokens, faster LLM response).
    """
    sections = []

    # Time & context (rich version if available)
    if time_context:
        period = time_context.get("period", "")
        season = time_context.get("season", "")
        formatted = time_context.get("formatted", "")
        sections.append(
            f"TIME & CONTEXT:\n{formatted}. {period.title()}, {season}."
        )
    elif current_datetime:
        sections.append(f"CURRENT TIME:\n{current_datetime}")

    # Who's home
    if presence_summary:
        sections.append(f"WHO'S HOME:\n{presence_summary}")

    # Calendar
    if calendar_summary:
        sections.append(f"TODAY'S SCHEDULE:\n{calendar_summary}")

    # Personal knowledge
    if relevant_facts:
        facts_text = "\n".join(
            f"- {f['key']}: {f['value']}" for f in relevant_facts
        )
        sections.append(f"WHAT YOU KNOW ABOUT THE USER:\n{facts_text}")

    # Recent conversation
    if recent_turns:
        turns_text = "\n".join(
            f"{'User' if t['role'] == 'user' else 'Apex'}: {t['content']}"
            for t in recent_turns
            if t.get("content")
        )
        if turns_text:
            sections.append(f"RECENT CONVERSATION:\n{turns_text}")

    context_block = "\n\n".join(sections) if sections else ""

    proactive_block = _build_proactive_hints(
        time_ctx=time_context,
        presence=presence_summary,
        calendar=calendar_summary,
    )

    # Build the area directory block
    area_directory_block = ""
    if area_directory:
        area_directory_block = (
            "\nAREA DIRECTORY (use area_id or "
            "area_name in do() targets):\n"
            f"{area_directory}"
        )

    # Build the devices block for the prompt
    devices_block = ""
    if device_summary:
        devices_block = (
            "\nAVAILABLE DEVICES (current names and IDs "
            "— always use these, not outdated names):\n"
            f"{device_summary}"
        )

    # Build the service schemas block for the prompt
    service_schemas_block = ""
    if service_schemas:
        service_schemas_block = (
            "\nSERVICE SCHEMAS (top domains — use "
            "discover(what='services', filter_str='domain') "
            "for others):\n"
            f"{service_schemas}\n"
        )

    if voice_mode:
        return VOICE_PROMPT_TEMPLATE.format(
            context_block=context_block,
            area_directory_block=area_directory_block,
            devices_block=devices_block,
        )

    return SYSTEM_PROMPT_TEMPLATE.format(
        context_block=context_block,
        proactive_block=proactive_block,
        area_directory_block=area_directory_block,
        devices_block=devices_block,
        service_schemas_block=service_schemas_block,
    )
