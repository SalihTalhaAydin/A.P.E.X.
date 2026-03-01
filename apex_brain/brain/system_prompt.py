"""
Apex Brain - Dynamic System Prompt
Rebuilt for every conversation turn with live context.
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
_SCHEMA_REFRESH_SECONDS = 3600


def _get_schema_lock() -> asyncio.Lock:
    """Lazy-init lock to avoid RuntimeError without event loop."""
    global _schema_lock
    if _schema_lock is None:
        _schema_lock = asyncio.Lock()
    return _schema_lock


_TOP_DOMAINS = ("light", "climate", "cover", "fan", "switch")

SYSTEM_PROMPT_TEMPLATE = """\
You are Apex, a personal AI home assistant — think J.A.R.V.I.S. \
You have full control of the Home Assistant instance and can do \
anything the user asks: control devices, create automations, \
edit configuration files, install packages, manage backups, \
rename entities, and more.

Personality: Composed, reliable, dry wit. Brief confirmations \
after actions. Never fabricate — if something fails, say so.

{context_block}

TOOLS:
- do(domain, service, targets, data) — call ANY HA service. \
For rooms, use area_name: do("light", "turn_off", \
targets={{"area_name": "kitchen"}}). \
For entire floors (multiple rooms), use area_name with the \
floor name — it auto-resolves: do("light", "turn_off", \
targets={{"area_name": "basement"}})
- query(target) — read entity state or Jinja2 template
- discover(what, filter_str) — find entities, services, areas, \
devices, integrations
- history(entity_id, hours, mode) — state change history
- manage(action, target, config) — Supervisor: backups, updates, \
add-on management
- configure(action, target, config) — Registry: rename, area CRUD, \
device assignment
- shell(command) — run any shell command (edit files, install \
packages, read logs, anything)
- see(camera_entity_id, question) — look through a camera
- remember(fact) / recall(query) / forget(fact) — long-term memory
- create_automation / update_automation — HA automations
- define_routine / run_routine — multi-step routines
- manage_todo — shopping/todo lists
- get_weather — weather forecasts
{area_directory_block}
{devices_block}
{service_schemas_block}\

RULES:
- ONLY do what was asked. No extra actions.
- Use do() with area_id for room-level commands. Use \
discover(what="areas") to find area IDs first.
- Never claim success without a tool call confirming it.
- If a tool returns an error, tell the user what happened.
- Be concise. No walls of text.
- Reference what you know naturally — never say "based on my records."
- Memories are saved automatically. Do not announce it.
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
    """Fetch and cache top-domain service schemas for prompt injection."""
    global _schema_cache

    now = time.monotonic()
    if (
        _schema_cache["schemas"]
        and (now - _schema_cache["timestamp"]) < _SCHEMA_REFRESH_SECONDS
    ):
        return _schema_cache["schemas"]

    async with _get_schema_lock():
        now = time.monotonic()
        if (
            _schema_cache["schemas"]
            and (now - _schema_cache["timestamp"])
            < _SCHEMA_REFRESH_SECONDS
        ):
            return _schema_cache["schemas"]

        try:
            from tools.generic import _selector_to_type
            from tools.ha_helpers import ha_request

            services_raw = await ha_request("GET", "/services")
            if not isinstance(services_raw, list):
                return _schema_cache.get("schemas", "")

            domain_map: dict = {}
            for entry in services_raw:
                if not isinstance(entry, dict):
                    continue
                domain = entry.get("domain", "")
                if not domain:
                    continue
                domain_map[domain] = entry.get("services", {})

            lines: list[str] = []
            for domain in _TOP_DOMAINS:
                svc_dict = domain_map.get(domain)
                if not svc_dict:
                    continue
                lines.append(f"## {domain}")
                for svc_name, svc_info in svc_dict.items():
                    fields = svc_info.get("fields", {})
                    parts: list[str] = []
                    for fname, finfo in fields.items():
                        selector = finfo.get("selector", {})
                        type_str = (
                            _selector_to_type(selector)
                            if selector
                            else "any"
                        )
                        parts.append(f"{fname}({type_str})")
                    field_str = ", ".join(parts) if parts else ""
                    lines.append(f"- {domain}.{svc_name}: {field_str}")

            schema_text = "\n".join(lines)
            token_estimate = len(schema_text) // 4
            logger.info(
                "Service schemas refreshed: %d domains, ~%d tokens",
                len([d for d in _TOP_DOMAINS if d in domain_map]),
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
    calendar: str = "",
) -> str:
    """Build observational hints based on live context."""
    hints = []

    if time_ctx:
        period = time_ctx.get("period", "")
        hour = time_ctx.get("hour", 12)

        if period == "morning":
            hints.append(
                "It's morning — if greeted, you may offer "
                "a brief briefing."
            )
        elif period == "night" and (hour >= 23 or hour < 5):
            hints.append("It's very late — be extra brief.")

    if calendar:
        hints.append("There are events on the calendar today.")

    if not hints:
        return ""

    lines = "\n".join(f"- {h}" for h in hints)
    return (
        f"\n\nCONTEXT HINTS (mention if relevant, "
        f"never act without being asked):\n{lines}\n"
    )


VOICE_PROMPT_TEMPLATE = """\
You are Apex, a smart home voice assistant. Be brief — \
this is voice output, not a screen. One short sentence max.

{context_block}

TOOLS:
- do(domain, service, targets, data) — call any HA service.
  For rooms, use area_name: do("light", "turn_off", \
targets={{"area_name": "kitchen"}}). \
For entire floors, use the floor name as area_name — it \
auto-resolves: do("light", "turn_off", \
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
    calendar_summary: str = "",
    relevant_facts: list[dict] | None = None,
    recent_turns: list[dict] | None = None,
    presence_summary: str = "",
    time_context: dict | None = None,
    device_summary: str = "",
    service_schemas: str = "",
    area_directory: str = "",
    voice_mode: bool = False,
    cross_session: bool = False,
) -> str:
    """Build the full system prompt with injected context.

    voice_mode: use compact VOICE_PROMPT_TEMPLATE instead
    of the full template (fewer tokens, faster LLM response).
    """
    sections = []

    if time_context:
        period = time_context.get("period", "")
        season = time_context.get("season", "")
        formatted = time_context.get("formatted", "")
        sections.append(f"TIME: {formatted}. {period.title()}, {season}.")

    if presence_summary:
        sections.append(f"WHO'S HOME: {presence_summary}")

    if calendar_summary:
        sections.append(f"TODAY'S SCHEDULE:\n{calendar_summary}")

    if relevant_facts:
        facts_text = "\n".join(
            f"- {f['key']}: {f['value']}" for f in relevant_facts
        )
        sections.append(f"WHAT YOU KNOW:\n{facts_text}")

    if recent_turns:
        turns_text = "\n".join(
            f"{'User' if t['role'] == 'user' else 'Apex'}: {t['content']}"
            for t in recent_turns
            if t.get("content")
        )
        if turns_text:
            label = (
                "RECENT CONVERSATION (from earlier chat — "
                "treat as ongoing context):"
                if cross_session
                else "RECENT CONVERSATION:"
            )
            sections.append(f"{label}\n{turns_text}")

    context_block = "\n\n".join(sections) if sections else ""

    proactive_block = _build_proactive_hints(
        time_ctx=time_context,
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
        devices_block = f"\nAVAILABLE DEVICES:\n{device_summary}"

    service_schemas_block = ""
    if service_schemas:
        service_schemas_block = f"\nSERVICE SCHEMAS:\n{service_schemas}\n"

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
