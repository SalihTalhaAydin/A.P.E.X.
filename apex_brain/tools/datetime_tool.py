"""
DateTime Tool - Current date and time.
Simple but always useful. Also used by the context builder.
"""

import datetime
import zoneinfo

from brain.config import settings
from tools.base import tool


@tool(
    description="Get the current date, time, and day of the week.",
    parameters={"type": "object", "properties": {}, "required": []},
)
def get_current_datetime() -> str:
    """Return the current date and time."""
    try:
        tz = zoneinfo.ZoneInfo(settings.timezone)
        now = datetime.datetime.now(tz=tz)
    except Exception:
        now = datetime.datetime.now(tz=datetime.timezone.utc)
    return now.strftime("%A, %B %d, %Y at %I:%M %p")
