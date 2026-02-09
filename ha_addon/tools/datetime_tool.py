"""
DateTime Tool - Current date and time.
Simple but always useful. Also used by the context builder.
"""

import datetime
from tools.base import tool


@tool(
    description="Get the current date, time, and day of the week.",
    parameters={"type": "object", "properties": {}, "required": []},
)
def get_current_datetime() -> str:
    """Return the current date and time."""
    now = datetime.datetime.now()
    return now.strftime("%A, %B %d, %Y at %I:%M %p")
