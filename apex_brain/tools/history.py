"""
History & Logbook tools for Home Assistant.
Query past state changes and event logs.
"""

import logging

from tools.base import tool
from tools.ha_helpers import ha_request

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
    try:
        from datetime import UTC, datetime, timedelta

        hours = max(1, min(168, hours_back))
        start = datetime.now(UTC) - timedelta(hours=hours)
        start_iso = start.strftime("%Y-%m-%dT%H:%M:%S+00:00")

        result = await ha_request(
            "GET",
            f"/history/period/{start_iso}"
            f"?filter_entity_id={entity_id}"
            "&minimal_response&no_attributes",
        )

        if not result or not isinstance(result, list):
            return f"No history found for {entity_id}."

        entries = result[0] if result else []
        if not entries:
            return (
                f"No state changes for {entity_id} "
                f"in the last {hours} hours."
            )

        _MAX_ENTRIES = 50
        lines = []
        for entry in entries[-_MAX_ENTRIES:]:
            state = entry.get("state", "?")
            last_changed = entry.get("last_changed", "")
            # Trim to readable format
            if "T" in last_changed:
                ts = last_changed.split(".")[0].replace("T", " ")
            else:
                ts = last_changed
            lines.append(f"  {ts}: {state}")

        total = len(entries)
        header = (
            f"History for {entity_id} (last {hours}h, {total} changes):"
        )
        if total > _MAX_ENTRIES:
            header += f" (showing last {_MAX_ENTRIES})"

        return header + "\n" + "\n".join(lines)
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
    try:
        from datetime import UTC, datetime, timedelta

        hours = max(1, min(72, hours_back))
        start = datetime.now(UTC) - timedelta(hours=hours)
        start_iso = start.strftime("%Y-%m-%dT%H:%M:%S+00:00")

        path = f"/logbook/{start_iso}"
        if entity_id:
            path += f"?entity={entity_id}"

        result = await ha_request("GET", path)

        if not result or not isinstance(result, list):
            return "No logbook entries found."

        _MAX_ENTRIES = 40
        lines = []
        for entry in result[-_MAX_ENTRIES:]:
            name = entry.get("name", "?")
            message = entry.get("message", "")
            when = entry.get("when", "")
            if "T" in when:
                ts = when.split(".")[0].replace("T", " ")
            else:
                ts = when
            eid = entry.get("entity_id", "")

            line = f"  {ts} | {name}"
            if message:
                line += f" {message}"
            if eid:
                line += f" ({eid})"
            lines.append(line)

        total = len(result)
        header = f"Logbook (last {hours}h, {total} events):"
        if total > _MAX_ENTRIES:
            header += f" (showing last {_MAX_ENTRIES})"

        return header + "\n" + "\n".join(lines)
    except Exception as e:
        return f"Error getting logbook: {e}"
