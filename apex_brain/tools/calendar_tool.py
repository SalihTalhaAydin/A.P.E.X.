"""
Calendar Tool - Google Calendar integration.
Uses a service account for headless auth (no interactive OAuth).

To enable:
1. Create a Google Cloud project
2. Enable Google Calendar API
3. Create a service account + download JSON key
4. Share your calendar with the service account email
5. Set GOOGLE_CALENDAR_CREDENTIALS_PATH in config
"""

import asyncio
import datetime as _dt

from brain.config import settings
from tools.base import tool

# Lazy-init: built once on first use
_calendar_service = None
_calendar_id = "primary"


def _get_calendar_service():
    """Build and cache the Google Calendar API client."""
    global _calendar_service, _calendar_id

    if _calendar_service is not None:
        return _calendar_service

    from brain.config import settings

    creds_path = settings.google_calendar_credentials_path
    if not creds_path:
        return None

    try:
        from google.oauth2.service_account import (
            Credentials,
        )
        from googleapiclient.discovery import build
    except ImportError:
        print(
            "[Calendar] google-api-python-client or "
            "google-auth not installed."
        )
        return None

    try:
        creds = Credentials.from_service_account_file(
            creds_path,
            scopes=[
                "https://www.googleapis.com/"
                "auth/calendar"
            ],
        )
        _calendar_service = build(
            "calendar", "v3", credentials=creds
        )
        _calendar_id = settings.google_calendar_id
        print("[Calendar] Service initialized.")
        return _calendar_service
    except Exception as e:
        print(f"[Calendar] Init error: {e}")
        return None


def _format_event(event: dict) -> str:
    """Format a single event into readable text."""
    summary = event.get("summary", "(no title)")
    start = event.get("start", {})
    location = event.get("location", "")

    # All-day vs timed events
    if "date" in start:
        time_str = start["date"]
    else:
        dt_str = start.get("dateTime", "")
        try:
            dt = _dt.datetime.fromisoformat(dt_str)
            time_str = dt.strftime("%I:%M %p")
        except (ValueError, TypeError):
            time_str = dt_str

    parts = [f"{time_str}: {summary}"]
    if location:
        parts.append(f"@ {location}")
    return " ".join(parts)


@tool(
    description=(
        "Get upcoming calendar events for the "
        "next N days. Returns event titles, times, "
        "and locations."
    ),
    parameters={
        "type": "object",
        "properties": {
            "days_ahead": {
                "type": "integer",
                "description": (
                    "Number of days to look ahead "
                    "(default: 7)."
                ),
            },
        },
        "required": [],
    },
)
async def get_events(days_ahead: int = 7) -> str:
    """Get upcoming calendar events."""
    svc = _get_calendar_service()
    if not svc:
        return "Calendar not configured yet."

    now = _dt.datetime.utcnow()
    end = now + _dt.timedelta(days=days_ahead)

    try:
        result = await asyncio.to_thread(
            lambda: svc.events()
            .list(
                calendarId=_calendar_id,
                timeMin=now.isoformat() + "Z",
                timeMax=end.isoformat() + "Z",
                maxResults=25,
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )
    except Exception as e:
        return f"Error fetching events: {e}"

    events = result.get("items", [])
    if not events:
        return (
            f"No events in the next "
            f"{days_ahead} day(s)."
        )

    lines = [_format_event(e) for e in events]
    return (
        f"{len(events)} event(s) in the "
        f"next {days_ahead} day(s):\n"
        + "\n".join(f"- {ln}" for ln in lines)
    )


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
                "description": (
                    "Optional event description."
                ),
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
    """Create a calendar event."""
    svc = _get_calendar_service()
    if not svc:
        return "Calendar not configured yet."

    tz = settings.timezone
    body = {
        "summary": title,
        "start": {
            "dateTime": start,
            "timeZone": tz,
        },
        "end": {
            "dateTime": end,
            "timeZone": tz,
        },
    }
    if description:
        body["description"] = description
    if location:
        body["location"] = location

    try:
        event = await asyncio.to_thread(
            lambda: svc.events()
            .insert(
                calendarId=_calendar_id, body=body
            )
            .execute()
        )
        link = event.get("htmlLink", "")
        return f"Done. Created '{title}'. {link}"
    except Exception as e:
        return f"Error creating event: {e}"


@tool(
    description=(
        "Get today's schedule as a concise summary."
    ),
    parameters={
        "type": "object",
        "properties": {},
        "required": [],
    },
)
async def get_today_schedule() -> str:
    """Get today's calendar events."""
    svc = _get_calendar_service()
    if not svc:
        return ""

    now = _dt.datetime.utcnow()
    start_of_day = now.replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    end_of_day = start_of_day + _dt.timedelta(days=1)

    try:
        result = await asyncio.to_thread(
            lambda: svc.events()
            .list(
                calendarId=_calendar_id,
                timeMin=(
                    start_of_day.isoformat() + "Z"
                ),
                timeMax=(
                    end_of_day.isoformat() + "Z"
                ),
                maxResults=20,
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )
    except Exception:
        return ""

    events = result.get("items", [])
    if not events:
        return "No events today."

    lines = [_format_event(e) for e in events]
    return "\n".join(f"- {ln}" for ln in lines)


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
                "description": (
                    "Google Calendar event ID."
                ),
            },
        },
        "required": ["event_id"],
    },
)
async def delete_event(event_id: str) -> str:
    """Delete a calendar event."""
    svc = _get_calendar_service()
    if not svc:
        return "Calendar not configured yet."

    try:
        await asyncio.to_thread(
            lambda: svc.events()
            .delete(
                calendarId=_calendar_id,
                eventId=event_id,
            )
            .execute()
        )
        return f"Done. Deleted event {event_id}."
    except Exception as e:
        return f"Error deleting event: {e}"
