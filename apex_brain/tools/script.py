"""
Script tools for Home Assistant.
List and execute HA scripts (domain: script.*).
Scripts differ from automations: they are user-defined sequences of actions
that can accept input variables and be triggered on demand.

DEPRECATED: These tools are thin wrappers that delegate to the generic
discover() and do() tools in tools.generic. Use those directly for new
code.
"""

import json
import logging

from tools.base import tool
from tools.generic import discover, do

logger = logging.getLogger(__name__)


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
    logger.warning(
        "DEPRECATED: %s() called — use %s() instead",
        "list_scripts", "discover",
    )
    try:
        filter_str = keyword if keyword else "script"
        return await discover("entities", filter_str)
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
    logger.warning(
        "DEPRECATED: %s() called — use %s() instead",
        "execute_script", "do",
    )
    try:
        data = None
        if variables:
            try:
                parsed = json.loads(variables)
                if isinstance(parsed, dict):
                    data = parsed
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

        return await do(
            "script",
            "turn_on",
            {"entity_id": entity_id},
            data,
        )

    except Exception as e:
        return f"Error executing script: {e}"
