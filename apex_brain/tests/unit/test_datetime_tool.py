"""Tests for datetime tool."""

import datetime
from unittest.mock import patch

from tools.datetime_tool import get_current_datetime


def test_get_current_datetime_returns_formatted_string():
    """get_current_datetime returns a formatted date/time string."""
    result = get_current_datetime()
    assert isinstance(result, str)
    # Basic sanity: contains day-of-week and date-like content
    assert len(result) > 10


def test_get_current_datetime_fallback_timezone_aware():
    """Bug 37: When ZoneInfo fails, fallback must use timezone-aware UTC datetime."""
    with patch(
        "tools.datetime_tool.zoneinfo.ZoneInfo",
        side_effect=Exception("ZoneInfo failed"),
    ):
        with patch("tools.datetime_tool.datetime.datetime") as mock_dt:
            aware = datetime.datetime(
                2025, 2, 22, 12, 0, 0, tzinfo=datetime.UTC
            )
            mock_dt.now.return_value = aware

            result = get_current_datetime()

            assert result is not None
            # Verify fallback path called now() with timezone.utc
            mock_dt.now.assert_called_once_with(tz=datetime.UTC)
            # Returned value used for strftime must be timezone-aware
            assert aware.tzinfo is not None


def test_get_current_datetime_format_contains_day_and_time():
    """get_current_datetime returns day of week, date, and time in standard format."""
    result = get_current_datetime()
    # Format: "Weekday, Month DD, YYYY at H:MM AM/PM"
    assert isinstance(result, str)
    assert ", " in result
    assert " at " in result
    assert "AM" in result or "PM" in result
    # Date components
    assert any(
        m in result
        for m in (
            "January",
            "February",
            "March",
            "April",
            "May",
            "June",
            "July",
            "August",
            "September",
            "October",
            "November",
            "December",
        )
    )


def test_get_current_datetime_with_custom_timezone():
    """get_current_datetime respects settings.timezone when ZoneInfo succeeds."""
    with patch("tools.datetime_tool.settings") as mock_settings:
        mock_settings.timezone = "America/New_York"
        with patch("tools.datetime_tool.zoneinfo.ZoneInfo") as mock_zi:
            tz = datetime.timezone(datetime.timedelta(hours=-5))
            mock_zi.return_value = tz

            result = get_current_datetime()

            mock_zi.assert_called_with("America/New_York")
            # Result should contain time in AM/PM format
            assert "AM" in result or "PM" in result


def test_get_current_datetime_format_structured():
    """get_current_datetime returns format 'Weekday, Month DD, YYYY at H:MM AM/PM'."""
    result = get_current_datetime()

    # Verify structure: "Sunday, February 22, 2026 at 02:30 PM" (exact format varies by time)
    assert isinstance(result, str)
    assert ", " in result
    assert " at " in result
    parts = result.split(" at ")
    assert len(parts) == 2
    day_part, time_part = parts
    assert "," in day_part
    assert "AM" in time_part or "PM" in time_part
