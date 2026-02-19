"""
History & Logbook tools for Home Assistant.
Query past state changes and event logs.

DEPRECATED: These tools are thin wrappers that delegate to the generic
history() tool in tools.generic. Use history() directly for new code.
"""
from __future__ import annotations

import logging

from tools.base import tool
from tools.generic import history

logger = logging.getLogger(__name__)


@tool(
    description=(
        "Get the state history of an entity over a "
        "time period. Shows how a device's state "
        "changed over time. Use for 'when did the "
        "light turn off?', 'temperature history', "
        "'was the door open last night?'."
    ),
    parameters={
        "type": "object",
        "properties": {
            "entity_id": {
                "type": "string",
                "description": (
                    "Entity to get history for, e.g. "
                    "'light.living_room', "
                    "'sensor.temperature'."
                ),
            },
            "hours_back": {
                "type": "integer",
                "description": (
                    "How many hours back to look "
                    "(default 24, max 168 = 1 week)."
                ),
            },
        },
        "required": ["entity_id"],
    },
)
async def get_history(entity_id: str, hours_back: int = 24) -> str:
    """Get state history for an entity."""
    logger.warning(
        "DEPRECATED: %s() called — use %s() instead",
        "get_history", "history",
    )
    try:
        hours = max(1, min(168, hours_back))
        return await history(entity_id, hours, "changes")
    except Exception as e:
        return f"Error getting history: {e}"


@tool(
    description=(
        "Get the logbook (event log) for the home. "
        "Shows human-readable events like 'Front door "
        "opened', 'Motion detected in hallway', "
        "'Automation triggered'. Optionally filter by "
        "entity."
    ),
    parameters={
        "type": "object",
        "properties": {
            "entity_id": {
                "type": "string",
                "description": ("Filter by entity ID. Optional."),
            },
            "hours_back": {
                "type": "integer",
                "description": (
                    "How many hours back (default 12, max 72)."
                ),
            },
        },
        "required": [],
    },
)
async def get_logbook(entity_id: str = "", hours_back: int = 12) -> str:
    """Get logbook events."""
    logger.warning(
        "DEPRECATED: %s() called — use %s() instead",
        "get_logbook", "history",
    )
    try:
        hours = max(1, min(72, hours_back))
        return await history(entity_id, hours, "logbook")
    except Exception as e:
        return f"Error getting logbook: {e}"
