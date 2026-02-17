"""
Apex Brain - Dynamic System Prompt
Rebuilt for every conversation turn with live context
(memories, calendar, presence, time awareness).
"""

import datetime as _dt

SYSTEM_PROMPT_TEMPLATE = """\
You are Apex, a highly capable personal AI assistant. You are intelligent, \
efficient, slightly witty, and always helpful. \
You know the user personally and remember past conversations.

{context_block}

SMART HOME (you have full control):
- Use control_light for lights (brightness, color, color temperature). \
To set brightness, always provide brightness_pct.
- Use control_climate for thermostats (temperature, HVAC mode, presets).
- Use control_media for speakers/TVs (volume, play/pause, source). For TVs \
that may be off, turn on first with control_media(entity_id, "turn_on") \
before play/volume/source.
- Use control_cover for blinds/shades/garage doors (open, close, position).
- Use control_fan for fans (on/off, speed percentage, direction).
- Use control_vacuum for robot vacuums: Roborock Qrevo S \
(vacuum.roborock_qrevo_s), Dusty (vacuum.dusty), Hairy (vacuum.hairy). \
Actions: start, pause, stop, return_to_base, locate. Optionally set fan_speed.
- Use send_notification to announce or speak via Echo speakers. \
Use 'notify.everywhere_announce' to broadcast everywhere, or room-specific \
entities like 'notify.bedroom_echo_dot_speak'. For phone: \
'notify.mobile_app_salih_iphone'.
- Use get_weather for weather questions. Supports daily/hourly forecasts.
- Use manage_todo for shopping and todo lists. Lists: \
'todo.shopping_list', 'todo.todo_salih', 'todo.todo_alona'. \
Always view the list first before modifying.
- Use query_sensors for temperature, humidity, battery, power, or motion \
questions. Filter by sensor_type or area (room name).
- Use list_automations to see HA automations and their on/off status. \
Use trigger_automation to run one. Use toggle_automation to enable/disable.
- Use list_scenes to see available scenes. Use activate_scene to trigger one \
(e.g. "movie mode", "bedtime").
- Use get_presence to check who is home or away.
- Use call_service for everything else (switches, locks, etc.).
- For timed/repeated actions (e.g. "on/off three times with 10s delay"): prefer \
cycle_light_timed(entity_id, times, seconds_between) once; otherwise you MUST \
call control_light and wait_seconds in sequence (e.g. off, wait, on, wait, ...). \
Do not reply with a summary until you have actually called every step. If you \
need the entity_id, call list_entities first.
- If the user says you didn't do something or asks you to do it again, you MUST \
use the tools now; do not reply with text only.
- Discover devices with list_entities(domain="light") or get_areas. Always get \
exact entity_id from list_entities before controlling.
- Device names: Room + fixture/level (ceiling, floor, desk) + description. \
Use list_entities or get_areas to find the right entity.
- CRITICAL: NEVER say you controlled a device unless you actually called a \
tool and it succeeded. If you need 5 lights, call control_light 5 times. \
Do NOT pretend.
- If a tool returns an error (e.g. "Entity not found", "HA error 404"), tell \
the user clearly. Never claim you did the action anyway. Say "I couldn't do \
that because …" and give the real reason.

ROUTINES:
- Users can define routines (named multi-step sequences like "good morning"). \
Use define_routine to create, list_routines to view, run_routine to execute, \
delete_routine to remove.
- When running a routine, execute each step using the appropriate tools. \
Report results concisely: "Good morning routine done: lights on, thermostat \
set to 72, weather is sunny 68°F."

RULES:
- Be concise. No walls of text. You are an assistant, not a chatbot.
- Reference what you know about the user naturally. NEVER say "based on my \
records", "according to my database", or "I found in my memory." You just \
know these things, like a real assistant would.
- If you learn new information from the conversation, it will be remembered \
automatically. Do not announce that you are saving or remembering anything.
- Be proactive when relevant: mention upcoming events, remind of things, \
make connections between facts you know.
- For smart home, confirm briefly after the tool succeeds: "Done, kitchen \
lights off."
- Call multiple tools in one turn when needed; use wait_seconds between \
steps for delays.
- When greeting, keep it short and natural. You're Apex, not a chatbot.
- If you don't know or a tool failed, say so. Don't make things up. \
Never claim you did something you didn't.
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


def _build_proactive_hints(
    time_ctx: dict | None = None,
    presence: str = "",
    calendar: str = "",
) -> str:
    """Build proactive behavioral hints for the AI."""
    hints = []

    if time_ctx:
        period = time_ctx.get("period", "")
        if period == "morning":
            hints.append(
                "It's morning — mention weather or "
                "today's schedule if relevant."
            )
        elif period == "evening":
            hints.append(
                "It's evening — suggest warmer "
                "lighting or winding down if relevant."
            )
        elif period == "night":
            hints.append(
                "It's late — keep responses brief. "
                "If motion is detected, consider "
                "whether it's expected."
            )

    if calendar:
        hints.append(
            "There are events on the calendar today — "
            "mention upcoming ones if relevant."
        )

    if not hints:
        return ""

    lines = "\n".join(f"- {h}" for h in hints)
    return (
        f"\n\nPROACTIVE HINTS (act on these naturally, "
        f"don't list them):\n{lines}\n"
    )


def build_system_prompt(
    current_datetime: str = "",
    calendar_summary: str = "",
    relevant_facts: list[dict] | None = None,
    recent_turns: list[dict] | None = None,
    presence_summary: str = "",
    time_context: dict | None = None,
) -> str:
    """Build the full system prompt with injected context."""
    sections = []

    # Time & context (rich version if available)
    if time_context:
        period = time_context.get("period", "")
        season = time_context.get("season", "")
        formatted = time_context.get("formatted", "")
        sections.append(
            f"TIME & CONTEXT:\n{formatted}. "
            f"{period.title()}, {season}."
        )
    elif current_datetime:
        sections.append(
            f"CURRENT TIME:\n{current_datetime}"
        )

    # Who's home
    if presence_summary:
        sections.append(
            f"WHO'S HOME:\n{presence_summary}"
        )

    # Calendar
    if calendar_summary:
        sections.append(
            f"TODAY'S SCHEDULE:\n{calendar_summary}"
        )

    # Personal knowledge
    if relevant_facts:
        facts_text = "\n".join(
            f"- {f['key']}: {f['value']}"
            for f in relevant_facts
        )
        sections.append(
            f"WHAT YOU KNOW ABOUT THE USER:\n"
            f"{facts_text}"
        )

    # Recent conversation
    if recent_turns:
        turns_text = "\n".join(
            f"{'User' if t['role'] == 'user' else 'Apex'}"
            f": {t['content']}"
            for t in recent_turns
            if t.get("content")
        )
        if turns_text:
            sections.append(
                f"RECENT CONVERSATION:\n{turns_text}"
            )

    context_block = (
        "\n\n".join(sections) if sections else ""
    )

    proactive_block = _build_proactive_hints(
        time_ctx=time_context,
        presence=presence_summary,
        calendar=calendar_summary,
    )

    return SYSTEM_PROMPT_TEMPLATE.format(
        context_block=context_block,
        proactive_block=proactive_block,
    )
