"""
Input Helper tools for Home Assistant.
Control input_number, input_select, input_text,
input_datetime, and input_boolean entities.

DEPRECATED: These tools are thin wrappers that delegate to the generic
do() and discover() tools in tools.generic. Use those directly for new
code.
"""

import logging

from tools.base import tool
from tools.generic import discover, do

logger = logging.getLogger(__name__)


@tool(
    description=(
        "Control Home Assistant input helpers: "
        "input_number, input_select, input_text, "
        "input_datetime, input_boolean. "
        "Use for adjusting settings, modes, counters, "
        "timers, or any user-defined helper entity."
    ),
    parameters={
        "type": "object",
        "properties": {
            "entity_id": {
                "type": "string",
                "description": (
                    "Input helper entity ID, e.g. "
                    "'input_number.target_temp', "
                    "'input_select.house_mode', "
                    "'input_boolean.guest_mode'."
                ),
            },
            "value": {
                "type": "string",
                "description": (
                    "Value to set. For input_number: "
                    "a number like '72'. For "
                    "input_select: an option like "
                    "'home'. For input_text: any text. "
                    "For input_datetime: ISO format "
                    "'2024-01-15 08:30:00'. For "
                    "input_boolean: 'on', 'off', or "
                    "'toggle'."
                ),
            },
        },
        "required": ["entity_id", "value"],
    },
)
async def set_input_helper(entity_id: str, value: str) -> str:
    """Set the value of an input helper entity."""
    logger.warning(
        "DEPRECATED: %s() called — use %s() instead",
        "set_input_helper", "do",
    )
    try:
        domain = entity_id.split(".")[0]

        if domain == "input_boolean":
            action_map = {
                "on": "turn_on",
                "off": "turn_off",
                "toggle": "toggle",
            }
            service = action_map.get(value.lower(), "turn_on")
            return await do(
                domain,
                service,
                {"entity_id": entity_id},
            )

        elif domain == "input_number":
            try:
                numeric = float(value)
            except (ValueError, TypeError):
                return (
                    f"Invalid number: '{value}'. "
                    "Provide a numeric value."
                )
            return await do(
                domain,
                "set_value",
                {"entity_id": entity_id},
                {"value": numeric},
            )

        elif domain == "input_select":
            return await do(
                domain,
                "select_option",
                {"entity_id": entity_id},
                {"option": value},
            )

        elif domain == "input_text":
            return await do(
                domain,
                "set_value",
                {"entity_id": entity_id},
                {"value": value},
            )

        elif domain == "input_datetime":
            data = {}
            if " " in value:
                data["datetime"] = value
            elif ":" in value:
                data["time"] = value
            else:
                data["date"] = value
            return await do(
                domain,
                "set_datetime",
                {"entity_id": entity_id},
                data,
            )

        else:
            return (
                f"Unsupported domain: {domain}. "
                "Use call_service for this entity."
            )

    except Exception as e:
        return f"Error setting input helper: {e}"


@tool(
    description=(
        "List all input helper entities "
        "(input_number, input_select, input_text, "
        "input_datetime, input_boolean) and their "
        "current values."
    ),
    parameters={
        "type": "object",
        "properties": {
            "helper_type": {
                "type": "string",
                "description": (
                    "Filter by type: 'number', "
                    "'select', 'text', 'datetime', "
                    "'boolean'. Optional (shows all "
                    "if omitted)."
                ),
            },
        },
        "required": [],
    },
)
async def list_input_helpers(
    helper_type: str = "",
) -> str:
    """List all input helper entities."""
    logger.warning(
        "DEPRECATED: %s() called — use %s() instead",
        "list_input_helpers", "discover",
    )
    try:
        filter_str = f"input_{helper_type}" if helper_type else "input_"
        return await discover("entities", filter_str)
    except Exception as e:
        return f"Error listing input helpers: {e}"
