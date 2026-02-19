"""
Switch and input_boolean control tool for Home Assistant.
Auto-detects the domain from the entity_id prefix and calls
the correct HA service.

DEPRECATED: This tool is a thin wrapper that delegates to the generic
do() tool in tools.generic. Use do() directly for new code.
"""

import logging

from tools.base import tool
from tools.generic import do

logger = logging.getLogger(__name__)


@tool(
    description=(
        "Control a switch or input_boolean: turn on, "
        "off, or toggle. Auto-detects the domain from "
        "the entity_id (switch.* or input_boolean.*). "
        "Use for smart plugs, relays, virtual switches."
    ),
    parameters={
        "type": "object",
        "properties": {
            "entity_id": {
                "type": "string",
                "description": (
                    "Entity ID, e.g. "
                    "'switch.office_desk_lamp', "
                    "'input_boolean.guest_mode'."
                ),
            },
            "action": {
                "type": "string",
                "enum": ["on", "off", "toggle"],
                "description": (
                    "Action: 'on', 'off', or 'toggle'."
                ),
            },
        },
        "required": ["entity_id", "action"],
    },
)
async def control_switch(
    entity_id: str,
    action: str,
) -> str:
    """Control a switch or input_boolean."""
    logger.warning(
        "DEPRECATED: %s() called — use %s() instead",
        "control_switch", "do",
    )
    try:
        # Auto-detect domain from entity_id prefix
        if entity_id.startswith("input_boolean."):
            domain = "input_boolean"
        elif entity_id.startswith("switch."):
            domain = "switch"
        else:
            return (
                f"Unsupported entity domain for "
                f"control_switch: {entity_id}. "
                "Expected switch.* or input_boolean.*."
            )

        svc_map = {
            "on": "turn_on",
            "off": "turn_off",
            "toggle": "toggle",
        }
        service = svc_map.get(action)
        if not service:
            return f"Unknown switch action: {action}"

        return await do(
            domain,
            service,
            {"entity_id": entity_id},
        )

    except Exception as e:
        return f"Error controlling switch: {e}"
