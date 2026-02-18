"""
Calendar Tool - Home Assistant calendar integration.

Reads calendar entities from HA (Google Calendar, Local Calendar, etc.)
via the HA REST API.  No Google service account needed — HA handles auth.

To enable:
1. Add a calendar integration in HA (Google Calendar, Local Calendar, etc.)
2. Entities will appear as calendar.* in HA states.
"""

from __future__ import annotations

import datetime as _dt
import logging

from tools.base import tool
from tools.ha_helpers import ha_request

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ──────────────────────────────────────────────────────────────────────────────

_NO_CALENDAR_MSG = (
    "No calendar configured. "
    "Add a calendar integration in HA "
    "(Google Calendar, Local Calendar, etc.)"
)


async def _get_calendar_entity_ids() -> list[str]:
    """Return all calendar.* entity IDs from HA states."""
    states = await ha_request("GET", "/states")
    if not isinstance(states, list):
        return []
    return [
        s["entity_id"]
        for s in states
        if isinstance(s, dict)
        and s.get("entity_id", "").startswith("calendar.")
    ]


def _parse_event_dt(dt_str: str | None) -> _dt.datetime | None:
    """Parse an ISO datetime string into a naive local datetime.

    HA calendar API returns strings like '2026-02-17T09:00:00+00:00'
    or '2026-02-17T09:00:00'.  We strip tz info so callers can compare
    dates without worrying about tz-aware vs naive arithmetic.
    """
    if not dt_str:
        return None
    try:
        dt = _dt.datetime.fromisoformat(dt_str)
        # Convert to naive by stripping tzinfo (treat as local-ish)
        return dt.replace(tzinfo=None)
    except (ValueError, TypeError):
        return None


def _format_time(dt: _dt.datetime | None, all_day: bool = False) -> str:
    """Format a datetime as a human-readable time string."""
    if all_day or dt is None:
        return "All day"
    return dt.strftime("%I:%M %p").lstrip("0") or dt.strftime("%I:%M %p")


def _format_event_line(
    summary: str,
    start_dt: _dt.datetime | None,
    end_dt: _dt.datetime | None,
    all_day: bool,
    entity_id: str,
) -> str:
    """Format a single event as a human-readable line."""
    if all_day:
        return f"- All day: {summary} ({entity_id})"
    start_str = _format_time(start_dt)
    end_str = _format_time(end_dt)
    if end_dt and start_dt:
        return f"- {start_str} - {end_str}: {summary} ({entity_id})"
    return f"- {start_str}: {summary} ({entity_id})"


def _today_date() -> _dt.date:
    return _dt.datetime.now().date()


# ──────────────────────────────────────────────────────────────────────────────
# Public tools
# ──────────────────────────────────────────────────────────────────────────────


@tool(
    description=(
        "Get today's calendar events as a concise summary. "
        "Reads all calendar.* entities from Home Assistant."
    ),
    parameters={
        "type": "object",
        "properties": {},
        "required": [],
    },
)
async def get_today_schedule() -> str:
    """Get today's calendar events from HA calendars."""
    try:
        entity_ids = await _get_calendar_entity_ids()
    except Exception as exc:
        logger.warning("Failed to fetch HA states: %s", exc)
        return f"Unable to reach Home Assistant: {exc}"

    if not entity_ids:
        return _NO_CALENDAR_MSG

    today = _today_date()
    today_start = _dt.datetime.combine(today, _dt.time.min)
    today_end = _dt.datetime.combine(today, _dt.time.max)

    start_str = today_start.strftime("%Y-%m-%dT%H:%M:%S")
    end_str = today_end.strftime("%Y-%m-%dT%H:%M:%S")

    all_events: list[tuple[_dt.datetime | None, str]] = []  # (sort_key, line)

    for eid in entity_ids:
        try:
            path = (
                f"/calendars/{eid}"
                f"?start={start_str}&end={end_str}"
            )
            events = await ha_request("GET", path)
        except Exception as exc:
            logger.warning("Failed to fetch calendar %s: %s", eid, exc)
            continue

        if not isinstance(events, list):
            continue

        for evt in events:
            if not isinstance(evt, dict):
                continue

            summary = evt.get("summary", "(no title)")
            all_day = evt.get("all_day", False)

            # HA calendar API uses 'start'/'end' as dicts with 'dateTime'
            # or 'date' keys, similar to Google Calendar format.
            start_info = evt.get("start", {})
            end_info = evt.get("end", {})

            if isinstance(start_info, dict):
                start_dt = _parse_event_dt(
                    start_info.get("dateTime") or start_info.get("date")
                )
                all_day = all_day or ("dateTime" not in start_info)
            else:
                # Flat string
                start_dt = _parse_event_dt(str(start_info) if start_info else None)

            if isinstance(end_info, dict):
                end_dt = _parse_event_dt(
                    end_info.get("dateTime") or end_info.get("date")
                )
            else:
                end_dt = _parse_event_dt(str(end_info) if end_info else None)

            # Filter: must overlap today
            if start_dt is not None:
                if not (today_start <= start_dt <= today_end):
                    continue
            elif not all_day:
                continue

            line = _format_event_line(summary, start_dt, end_dt, all_day, eid)
            all_events.append((start_dt, line))

    if not all_events:
        return "No events scheduled for today."

    # Sort by start time (None → end of list)
    all_events.sort(key=lambda x: x[0] or _dt.datetime.max)
    return "\n".join(line for _, line in all_events)


@tool(
    description=(
        "Get upcoming calendar events for the next N days. "
        "Reads all calendar.* entities from Home Assistant. "
        "Results are grouped by day."
    ),
    parameters={
        "type": "object",
        "properties": {
            "days_ahead": {
                "type": "integer",
                "description": (
                    "Number of days to look ahead (default: 7)."
                ),
            },
        },
        "required": [],
    },
)
async def get_events(days_ahead: int = 7) -> str:
    """Get upcoming calendar events from HA calendars."""
    try:
        entity_ids = await _get_calendar_entity_ids()
    except Exception as exc:
        logger.warning("Failed to fetch HA states: %s", exc)
        return f"Unable to reach Home Assistant: {exc}"

    if not entity_ids:
        return _NO_CALENDAR_MSG

    today = _today_date()
    range_start = _dt.datetime.combine(today, _dt.time.min)
    range_end = _dt.datetime.combine(
        today + _dt.timedelta(days=days_ahead), _dt.time.max
    )

    start_str = range_start.strftime("%Y-%m-%dT%H:%M:%S")
    end_str = range_end.strftime("%Y-%m-%dT%H:%M:%S")

    # Collect (sort_key_dt, day_date, line_str) tuples
    collected: list[tuple[_dt.datetime, _dt.date, str]] = []

    for eid in entity_ids:
        try:
            path = (
                f"/calendars/{eid}"
                f"?start={start_str}&end={end_str}"
            )
            events = await ha_request("GET", path)
        except Exception as exc:
            logger.warning("Failed to fetch calendar %s: %s", eid, exc)
            continue

        if not isinstance(events, list):
            continue

        for evt in events:
            if not isinstance(evt, dict):
                continue

            summary = evt.get("summary", "(no title)")
            all_day = evt.get("all_day", False)

            start_info = evt.get("start", {})
            end_info = evt.get("end", {})

            if isinstance(start_info, dict):
                start_dt = _parse_event_dt(
                    start_info.get("dateTime") or start_info.get("date")
                )
                all_day = all_day or ("dateTime" not in start_info)
            else:
                start_dt = _parse_event_dt(str(start_info) if start_info else None)

            if isinstance(end_info, dict):
                end_dt = _parse_event_dt(
                    end_info.get("dateTime") or end_info.get("date")
                )
            else:
                end_dt = _parse_event_dt(str(end_info) if end_info else None)

            # Determine the day this event belongs to
            if start_dt is not None:
                event_day = start_dt.date()
                sort_key = start_dt
            elif all_day:
                event_day = today
                sort_key = range_start
            else:
                continue

            # Build line
            if all_day:
                line = f"  - All day: {summary}"
            else:
                time_str = _format_time(start_dt)
                line = f"  - {time_str}: {summary}"

            collected.append((sort_key, event_day, line))

    if not collected:
        return f"No events in the next {days_ahead} day(s)."

    # Sort by datetime
    collected.sort(key=lambda x: x[0])

    # Group by day
    day_groups: dict[_dt.date, list[str]] = {}
    for _, day, line in collected:
        day_groups.setdefault(day, []).append(line)

    output_lines: list[str] = []
    for day in sorted(day_groups):
        day_label = day.strftime("%A, %b %d")
        output_lines.append(f"{day_label}:")
        output_lines.extend(day_groups[day])

    return "\n".join(output_lines)


# ──────────────────────────────────────────────────────────────────────────────
# Legacy Google Calendar stubs (kept for tool-registry compatibility)
# These are no-ops — HA integration is the preferred path.
# ──────────────────────────────────────────────────────────────────────────────


@tool(
    description=(
        "Create a new calendar event. Provide "
        "title, start and end times in ISO format "
        "(e.g. '2026-02-18T10:00:00')."
    ),
    parameters={
        "type": "object",
        "properties": {
            "title": {
                "type": "string",
                "description": "Event title.",
            },
            "start": {
                "type": "string",
                "description": (
                    "Start time in ISO format, "
                    "e.g. '2026-02-18T10:00:00'."
                ),
            },
            "end": {
                "type": "string",
                "description": (
                    "End time in ISO format, "
                    "e.g. '2026-02-18T11:00:00'."
                ),
            },
            "description": {
                "type": "string",
                "description": "Optional event description.",
            },
            "location": {
                "type": "string",
                "description": "Optional location.",
            },
        },
        "required": ["title", "start", "end"],
    },
)
async def create_event(
    title: str,
    start: str,
    end: str,
    description: str = "",
    location: str = "",
) -> str:
    """Create a calendar event via HA calendar service."""
    entity_ids = await _get_calendar_entity_ids()
    if not entity_ids:
        return _NO_CALENDAR_MSG

    # Use the first available calendar entity
    eid = entity_ids[0]
    event_body: dict = {
        "entity_id": eid,
        "summary": title,
        "start_date_time": start,
        "end_date_time": end,
    }
    if description:
        event_body["description"] = description
    if location:
        event_body["location"] = location

    try:
        await ha_request(
            "POST",
            "/services/calendar/create_event",
            json_data=event_body,
        )
        return f"Done. Created '{title}' on {eid}."
    except Exception as exc:
        return f"Error creating event: {exc}"


@tool(
    description=(
        "Delete a calendar event by its event ID. "
        "Get event IDs from get_events."
    ),
    parameters={
        "type": "object",
        "properties": {
            "event_id": {
                "type": "string",
                "description": "Calendar event ID or summary to delete.",
            },
        },
        "required": ["event_id"],
    },
)
async def delete_event(event_id: str) -> str:
    """Delete a calendar event via HA."""
    return (
        "Event deletion via HA calendar integration is not yet supported. "
        "Please delete the event directly in your calendar app."
    )
