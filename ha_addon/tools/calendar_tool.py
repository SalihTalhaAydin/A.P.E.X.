"""
Calendar Tool - Google Calendar integration (stub).
Requires Google Cloud project + OAuth setup. Enable when ready.

To enable:
1. Create a Google Cloud project
2. Enable Google Calendar API
3. Create OAuth credentials (or service account)
4. Set GOOGLE_CALENDAR_CREDENTIALS_PATH in config
5. Uncomment the @tool decorators below

For now, this is a placeholder that shows the interface.
The tools are NOT registered until you uncomment the decorators.
"""

# from tools.base import tool

# Uncomment these when you've set up Google Calendar API:

# @tool(
#     description="Get upcoming calendar events for the next N days.",
#     parameters={
#         "type": "object",
#         "properties": {
#             "days_ahead": {
#                 "type": "integer",
#                 "description": "Number of days to look ahead (default: 7)",
#             },
#         },
#         "required": [],
#     },
# )
# async def get_events(days_ahead: int = 7) -> str:
#     """Get upcoming calendar events."""
#     # TODO: Implement with Google Calendar API
#     return "Calendar not configured yet."


# @tool(
#     description="Create a new calendar event.",
#     parameters={
#         "type": "object",
#         "properties": {
#             "title": {"type": "string", "description": "Event title"},
#             "start": {"type": "string", "description": "Start time (ISO format or natural language)"},
#             "end": {"type": "string", "description": "End time (ISO format or natural language)"},
#             "description": {"type": "string", "description": "Optional event description"},
#         },
#         "required": ["title", "start", "end"],
#     },
# )
# async def create_event(title: str, start: str, end: str, description: str = "") -> str:
#     """Create a calendar event."""
#     # TODO: Implement with Google Calendar API
#     return "Calendar not configured yet."


# @tool(
#     description="Get today's schedule as a summary.",
#     parameters={"type": "object", "properties": {}, "required": []},
# )
# async def get_today_schedule() -> str:
#     """Get today's calendar events."""
#     # TODO: Implement with Google Calendar API
#     return "Calendar not configured yet."
