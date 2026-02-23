"""Tests for calendar tool."""

import datetime as dt
from unittest.mock import AsyncMock, patch

import pytest

from tools.base import TOOL_REGISTRY


@pytest.fixture(scope="module")
def _tools_loaded():
    from tools import discover_tools
    discover_tools()


@pytest.mark.usefixtures("_tools_loaded")
def test_get_events_registered():
    """get_events is in the registry."""
    info = TOOL_REGISTRY.get("get_events")
    assert info is not None
    props = info["parameters"]["properties"]
    assert "days_ahead" in props


@pytest.mark.usefixtures("_tools_loaded")
def test_create_event_registered():
    """create_event requires title, start, end."""
    info = TOOL_REGISTRY.get("create_event")
    assert info is not None
    req = info["parameters"]["required"]
    assert "title" in req
    assert "start" in req
    assert "end" in req


@pytest.mark.usefixtures("_tools_loaded")
def test_create_event_has_optional_fields():
    """create_event has description, location, and calendar_entity_id."""
    info = TOOL_REGISTRY["create_event"]
    props = info["parameters"]["properties"]
    assert "description" in props
    assert "location" in props
    assert "calendar_entity_id" in props
    req = info["parameters"]["required"]
    assert "description" not in req
    assert "location" not in req
    assert "calendar_entity_id" not in req


@pytest.mark.usefixtures("_tools_loaded")
def test_get_today_schedule_registered():
    """get_today_schedule is in the registry."""
    info = TOOL_REGISTRY.get("get_today_schedule")
    assert info is not None


@pytest.mark.usefixtures("_tools_loaded")
def test_delete_event_registered():
    """delete_event requires event_id."""
    info = TOOL_REGISTRY.get("delete_event")
    assert info is not None
    req = info["parameters"]["required"]
    assert "event_id" in req


# create_event calendar selection (bug 90)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_event_uses_first_calendar_when_no_entity_specified():
    """When calendar_entity_id is omitted, use first available calendar."""
    async def mock_ha_request(method, path, json_data=None, **_kwargs):
        if method == "GET" and path == "/states":
            return [
                {"entity_id": "calendar.personal"},
                {"entity_id": "calendar.work"},
                {"entity_id": "calendar.family"},
            ]
        if method == "POST" and path == "/services/calendar/create_event":
            assert json_data is not None
            assert json_data["entity_id"] == "calendar.personal"
            assert json_data["summary"] == "Team standup"
            return None
        return []

    with patch(
        "tools.calendar_tool.ha_request",
        new_callable=AsyncMock,
        side_effect=mock_ha_request,
    ):
        from tools.calendar_tool import create_event

        result = await create_event(
            title="Team standup",
            start="2026-02-23T09:00:00",
            end="2026-02-23T09:30:00",
        )

    assert "Done" in result
    assert "calendar.personal" in result


@pytest.mark.asyncio
async def test_create_event_uses_specified_calendar_when_valid():
    """When calendar_entity_id is provided and valid, use that calendar."""
    async def mock_ha_request(method, path, json_data=None, **_kwargs):
        if method == "GET" and path == "/states":
            return [
                {"entity_id": "calendar.personal"},
                {"entity_id": "calendar.work"},
                {"entity_id": "calendar.family"},
            ]
        if method == "POST" and path == "/services/calendar/create_event":
            assert json_data is not None
            assert json_data["entity_id"] == "calendar.work"
            assert json_data["summary"] == "Client call"
            return None
        return []

    with patch(
        "tools.calendar_tool.ha_request",
        new_callable=AsyncMock,
        side_effect=mock_ha_request,
    ):
        from tools.calendar_tool import create_event

        result = await create_event(
            title="Client call",
            start="2026-02-23T14:00:00",
            end="2026-02-23T15:00:00",
            calendar_entity_id="calendar.work",
        )

    assert "Done" in result
    assert "calendar.work" in result


@pytest.mark.asyncio
async def test_create_event_rejects_invalid_calendar_entity_id():
    """When calendar_entity_id is not in available calendars, return error."""
    async def mock_ha_request(method, path, **_kwargs):
        if method == "GET" and path == "/states":
            return [
                {"entity_id": "calendar.personal"},
                {"entity_id": "calendar.work"},
            ]
        return []

    with patch(
        "tools.calendar_tool.ha_request",
        new_callable=AsyncMock,
        side_effect=mock_ha_request,
    ):
        from tools.calendar_tool import create_event

        result = await create_event(
            title="Meeting",
            start="2026-02-23T10:00:00",
            end="2026-02-23T11:00:00",
            calendar_entity_id="calendar.family",
        )

    assert "not found" in result
    assert "calendar.family" in result
    assert "calendar.personal" in result
    assert "calendar.work" in result


# _format_time edge cases (bug 89 - lstrip vs removeprefix)
# ---------------------------------------------------------------------------


def test_format_time_strips_single_leading_zero_from_hour():
    """9am formats as '9:00 AM' (single leading 0 removed, not lstrip behavior)."""
    from tools.calendar_tool import _format_time

    dt_9am = dt.datetime(2026, 2, 20, 9, 0)
    assert _format_time(dt_9am) == "9:00 AM"


def test_format_time_preserves_double_digit_hours():
    """10am and 12pm keep both digits."""
    from tools.calendar_tool import _format_time

    assert _format_time(dt.datetime(2026, 2, 20, 10, 0)) == "10:00 AM"
    assert _format_time(dt.datetime(2026, 2, 20, 12, 0)) == "12:00 PM"


def test_format_time_midnight_and_noon():
    """Midnight (12 AM) and noon (12 PM) format correctly."""
    from tools.calendar_tool import _format_time

    assert _format_time(dt.datetime(2026, 2, 20, 0, 30)) == "12:30 AM"
    assert _format_time(dt.datetime(2026, 2, 20, 12, 30)) == "12:30 PM"


def test_format_time_single_digit_hour_with_minutes():
    """1:30 AM strips only leading 0, not minutes."""
    from tools.calendar_tool import _format_time

    assert _format_time(dt.datetime(2026, 2, 20, 1, 30)) == "1:30 AM"


def test_format_time_all_day_returns_all_day():
    """All-day events return 'All day'."""
    from tools.calendar_tool import _format_time

    assert _format_time(None, all_day=True) == "All day"
    assert _format_time(None, all_day=False) == "All day"


# Multi-day all-day event filter (bug 33)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_multi_day_all_day_event_included_when_today_in_range():
    """Ongoing multi-day all-day event is included when today is within [start, end]."""
    today = dt.date(2026, 2, 20)

    async def mock_ha_request(method, path, **_kwargs):
        if method == "GET" and path == "/states":
            return [{"entity_id": "calendar.test_cal"}]
        if method == "GET" and "/calendars/calendar.test_cal" in path:
            # Event spans Feb 18-22; today Feb 20 is in range
            return [
                {
                    "summary": "Conference",
                    "all_day": True,
                    "start": {"date": "2026-02-18"},
                    "end": {"date": "2026-02-23"},
                },
            ]
        return []

    with patch(
        "tools.calendar_tool.ha_request",
        new_callable=AsyncMock,
        side_effect=mock_ha_request,
    ), patch("tools.calendar_tool._today_date", return_value=today):
        from tools.calendar_tool import get_today_schedule

        result = await get_today_schedule()

    assert "Conference" in result
    assert "All day" in result


@pytest.mark.asyncio
async def test_multi_day_all_day_event_excluded_when_today_outside_range():
    """Multi-day all-day event is excluded when today is outside [start, end]."""
    today = dt.date(2026, 2, 25)

    async def mock_ha_request(method, path, **_kwargs):
        if method == "GET" and path == "/states":
            return [{"entity_id": "calendar.test_cal"}]
        if method == "GET" and "/calendars/calendar.test_cal" in path:
            # Event spans Feb 18-22; today Feb 25 is outside range
            return [
                {
                    "summary": "Past Conference",
                    "all_day": True,
                    "start": {"date": "2026-02-18"},
                    "end": {"date": "2026-02-23"},
                },
            ]
        return []

    with patch(
        "tools.calendar_tool.ha_request",
        new_callable=AsyncMock,
        side_effect=mock_ha_request,
    ), patch("tools.calendar_tool._today_date", return_value=today):
        from tools.calendar_tool import get_today_schedule

        result = await get_today_schedule()

    assert "Past Conference" not in result
    assert "No events scheduled for today" in result


@pytest.mark.asyncio
async def test_single_day_all_day_event_without_end_dt_still_included():
    """Single-day all-day event with end_dt=None is included when today matches start."""
    today = dt.date(2026, 2, 20)

    async def mock_ha_request(method, path, **_kwargs):
        if method == "GET" and path == "/states":
            return [{"entity_id": "calendar.test_cal"}]
        if method == "GET" and "/calendars/calendar.test_cal" in path:
            # Use dateTime at noon local to avoid timezone shifting the date
            return [
                {
                    "summary": "Day Off",
                    "all_day": True,
                    "start": {"dateTime": "2026-02-20T12:00:00"},
                    "end": {},
                },
            ]
        return []

    with patch(
        "tools.calendar_tool.ha_request",
        new_callable=AsyncMock,
        side_effect=mock_ha_request,
    ), patch("tools.calendar_tool._today_date", return_value=today):
        from tools.calendar_tool import get_today_schedule

        result = await get_today_schedule()

    assert "Day Off" in result


# get_events with error dict (when calendar API returns dict instead of list)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_events_skips_calendar_when_api_returns_error_dict():
    """When a calendar returns an error dict instead of events list, skip it and use others."""
    today = dt.date(2026, 2, 20)

    async def mock_ha_request(method, path, **_kwargs):
        if method == "GET" and path == "/states":
            return [
                {"entity_id": "calendar.good"},
                {"entity_id": "calendar.bad"},
            ]
        if method == "GET" and "/calendars/calendar.good" in path:
            return [
                {
                    "summary": "Meeting",
                    "all_day": False,
                    "start": {"dateTime": "2026-02-20T10:00:00"},
                    "end": {"dateTime": "2026-02-20T11:00:00"},
                },
            ]
        if method == "GET" and "/calendars/calendar.bad" in path:
            return {"message": "error", "code": 500}
        return []

    with patch(
        "tools.calendar_tool.ha_request",
        new_callable=AsyncMock,
        side_effect=mock_ha_request,
    ), patch("tools.calendar_tool._today_date", return_value=today):
        from tools.calendar_tool import get_events

        result = await get_events(days_ahead=3)

    assert "Meeting" in result
    assert "error" not in result.lower()
    # Time is in local timezone; check for AM/PM or colon in time
    assert "AM" in result or "PM" in result


@pytest.mark.asyncio
async def test_get_events_returns_no_events_when_all_calendars_return_error_dict():
    """When all calendars return error dict, return no-events message."""
    today = dt.date(2026, 2, 20)

    async def mock_ha_request(method, path, **_kwargs):
        if method == "GET" and path == "/states":
            return [{"entity_id": "calendar.one"}]
        if method == "GET" and "/calendars/" in path:
            return {"error": "forbidden"}
        return []

    with patch(
        "tools.calendar_tool.ha_request",
        new_callable=AsyncMock,
        side_effect=mock_ha_request,
    ), patch("tools.calendar_tool._today_date", return_value=today):
        from tools.calendar_tool import get_events

        result = await get_events(days_ahead=7)

    assert "No events" in result


@pytest.mark.asyncio
async def test_get_today_schedule_skips_calendar_when_api_returns_error_dict():
    """get_today_schedule skips calendars that return error dict (isinstance check)."""
    today = dt.date(2026, 2, 20)

    async def mock_ha_request(method, path, **_kwargs):
        if method == "GET" and path == "/states":
            return [
                {"entity_id": "calendar.good"},
                {"entity_id": "calendar.bad"},
            ]
        if method == "GET" and "/calendars/calendar.good" in path:
            return [
                {
                    "summary": "Morning standup",
                    "all_day": False,
                    "start": {"dateTime": "2026-02-20T09:00:00"},
                    "end": {"dateTime": "2026-02-20T09:30:00"},
                },
            ]
        if method == "GET" and "/calendars/calendar.bad" in path:
            return {"message": "API error", "code": 500}
        return []

    with patch(
        "tools.calendar_tool.ha_request",
        new_callable=AsyncMock,
        side_effect=mock_ha_request,
    ), patch("tools.calendar_tool._today_date", return_value=today):
        from tools.calendar_tool import get_today_schedule

        result = await get_today_schedule()

    assert "Morning standup" in result
    assert "calendar.good" in result
    assert "API error" not in result
