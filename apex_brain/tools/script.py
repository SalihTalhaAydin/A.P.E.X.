"""
Script tools for Home Assistant.
List and execute HA scripts (domain: script.*).
Scripts differ from automations: they are user-defined sequences of actions
that can accept input variables and be triggered on demand.
"""

import json
import logging

import httpx

logger = logging.getLogger(__name__)

from tools.base import tool
from tools.ha_helpers import (
    format_ha_error,
    ha_request,
    verify_generic,
)


@tool(
    description=(
        "List all Home Assistant scripts with their "
        "current state (on = running, off = idle). "
        "Optionally filter by keyword in the name."
    ),
    parameters={
        "type": "object",
        "properties": {
            "keyword": {
                "type": "string",
                "description": (
                    "Filter by keyword in the script "
                    "name (e.g. 'morning', 'lights'). "
                    "Optional."
                ),
            },
        },
        "required": [],
    },
)
async def list_scripts(keyword: str = "") -> str:
    """List all HA scripts."""
    try:
        states = await ha_request("GET", "/states")
        scripts = [
            s
            for s in states
            if s["entity_id"].startswith("script.")
        ]

        if keyword:
            kw_lower = keyword.lower()
            scripts = [
                s
                for s in scripts
                if kw_lower
                in s.get("attributes", {})
                .get("friendly_name", "")
                .lower()
                or kw_lower in s["entity_id"].lower()
            ]

        if not scripts:
            suffix = (
                f" matching '{keyword}'" if keyword else ""
            )
            return f"No scripts found{suffix}."

        lines = []
        for s in scripts:
            name = s.get("attributes", {}).get(
                "friendly_name", s["entity_id"]
            )
            state = s.get("state", "unknown")
            eid = s["entity_id"]
            status = "running" if state == "on" else "idle"
            lines.append(
                f"- {name} ({eid}): {status}"
            )

        return (
            f"Found {len(lines)} script(s):\n"
            + "\n".join(lines)
        )
    except httpx.HTTPStatusError as e:
        return format_ha_error("script.*", "script", e)
    except Exception as e:
        return f"Error listing scripts: {e}"


@tool(
    description=(
        "Execute (trigger) a Home Assistant script. "
        "Scripts are reusable action sequences. "
        "Optionally pass variables as a JSON string."
    ),
    parameters={
        "type": "object",
        "properties": {
            "entity_id": {
                "type": "string",
                "description": (
                    "Script entity ID, e.g. "
                    "'script.good_morning', "
                    "'script.clean_kitchen'."
                ),
            },
            "variables": {
                "type": "string",
                "description": (
                    "Optional JSON string of variables "
                    "to pass to the script, e.g. "
                    "'{\"brightness\": 80}'. "
                    "Leave empty if no variables needed."
                ),
            },
        },
        "required": ["entity_id"],
    },
)
async def execute_script(
    entity_id: str, variables: str = ""
) -> str:
    """Execute a HA script with optional variables."""
    try:
        payload: dict = {"entity_id": entity_id}

        if variables:
            try:
                parsed = json.loads(variables)
                if isinstance(parsed, dict):
                    payload["variables"] = parsed
                else:
                    return (
                        "Variables must be a JSON object "
                        "(key-value pairs), e.g. "
                        "'{\"key\": \"value\"}'."
                    )
            except json.JSONDecodeError as je:
                return (
                    f"Invalid JSON in variables: {je}. "
                    "Provide a valid JSON string or "
                    "leave empty."
                )

        logger.debug("Executing %s payload=%s", entity_id, payload)
        await ha_request(
            "POST",
            "/services/script/turn_on",
            json_data=payload,
        )

        status = await verify_generic(entity_id)
        return f"Done. Executed {entity_id}. {status}"

    except httpx.HTTPStatusError as e:
        return format_ha_error(entity_id, "script", e)
    except Exception as e:
        return f"Error executing script: {e}"
