"""
Input Helper tools for Home Assistant.
Control input_number, input_select, input_text,
input_datetime, and input_boolean entities.
"""

import logging

import httpx

from tools.base import tool
from tools.ha_helpers import (
    call_ha_service,
    format_ha_error,
    ha_request,
    verify_generic,
)

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
    try:
        domain = entity_id.split(".")[0]

        if domain == "input_boolean":
            action_map = {
                "on": "turn_on",
                "off": "turn_off",
                "toggle": "toggle",
            }
            service = action_map.get(value.lower(), "turn_on")
            await call_ha_service(domain, service, entity_id)

        elif domain == "input_number":
            await call_ha_service(
                domain,
                "set_value",
                entity_id,
                {"value": float(value)},
            )

        elif domain == "input_select":
            await call_ha_service(
                domain,
                "select_option",
                entity_id,
                {"option": value},
            )

        elif domain == "input_text":
            await call_ha_service(
                domain,
                "set_value",
                entity_id,
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
            await call_ha_service(
                domain,
                "set_datetime",
                entity_id,
                data,
            )

        else:
            return (
                f"Unsupported domain: {domain}. "
                "Use call_service for this entity."
            )

        status = await verify_generic(entity_id)
        return f"Done. {status}"

    except httpx.HTTPStatusError as e:
        return format_ha_error(entity_id, domain, e)
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
    try:
        states = await ha_request("GET", "/states")

        input_domains = [
            "input_number",
            "input_select",
            "input_text",
            "input_datetime",
            "input_boolean",
        ]

        if helper_type:
            domain_filter = f"input_{helper_type}"
            if domain_filter in input_domains:
                input_domains = [domain_filter]

        helpers = [
            s
            for s in states
            if any(
                s["entity_id"].startswith(f"{d}.") for d in input_domains
            )
        ]

        if not helpers:
            return "No input helper entities found."

        lines = []
        for s in helpers:
            eid = s["entity_id"]
            fn = s.get("attributes", {}).get("friendly_name", eid)
            state = s.get("state", "?")
            attrs = s.get("attributes", {})

            detail = f"- {fn} ({eid}): {state}"

            # Add relevant attributes
            if "options" in attrs:
                opts = ", ".join(attrs["options"][:5])
                detail += f" [options: {opts}]"
            if "min" in attrs and "max" in attrs:
                detail += f" [range: {attrs['min']}-{attrs['max']}]"
            if "unit_of_measurement" in attrs:
                detail += f" {attrs['unit_of_measurement']}"

            lines.append(detail)

        return f"Found {len(lines)} input helper(s):\n" + "\n".join(lines)
    except Exception as e:
        return f"Error listing input helpers: {e}"
