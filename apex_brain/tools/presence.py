"""
Presence tool for Home Assistant.
Queries person entities to determine who is home or away.
Also exposes a helper for the context builder to inject
presence into the system prompt automatically.

DEPRECATED: get_presence is a thin wrapper that delegates to the generic
discover() tool in tools.generic. Use discover() directly for new code.
The get_presence_summary() helper is kept as-is (used by context builder).
"""

import logging

from tools.base import tool
from tools.generic import discover
from tools.ha_helpers import ha_request

logger = logging.getLogger(__name__)


async def get_presence_summary() -> str:
    """Fetch all person entities and return a summary.

    Used by the context builder to inject presence
    into the system prompt every turn.
    Returns '' if no person entities or on error.
    """
    try:
        states = await ha_request("GET", "/states")
        if not isinstance(states, list):
            return ""
        persons = [
            s
            for s in states
            if s.get("entity_id", "").startswith("person.")
        ]
        if not persons:
            return ""

        lines = []
        for p in persons:
            name = p.get("attributes", {}).get(
                "friendly_name",
                p["entity_id"].split(".")[-1].title(),
            )
            state = p.get("state", "unknown")
            lines.append(f"{name}: {state}")

        return ", ".join(lines)
    except Exception:
        return ""


@tool(
    description=(
        "Check who is home or away. Queries Home "
        "Assistant person entities for presence status. "
        "Optionally filter by a specific person's name."
    ),
    parameters={
        "type": "object",
        "properties": {
            "person": {
                "type": "string",
                "description": (
                    "Person name to filter by "
                    "(e.g. 'Salih'). Optional."
                ),
            },
        },
        "required": [],
    },
)
async def get_presence(person: str = "") -> str:
    """Check who is home or away."""
    logger.warning(
        "DEPRECATED: %s() called — use %s() instead",
        "get_presence", "discover",
    )
    try:
        filter_str = person if person else "person"
        return await discover("entities", filter_str)
    except Exception as e:
        return f"Error checking presence: {e}"
