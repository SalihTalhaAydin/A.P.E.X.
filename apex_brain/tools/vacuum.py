"""
Vacuum control tool for Home Assistant robot vacuums.
Supports start, pause, stop, return-to-base, locate, and fan speed.
"""

import httpx

from tools.base import tool
from tools.ha_helpers import (
    call_ha_service,
    format_ha_error,
    friendly_name,
    read_state,
)


async def _verify_vacuum(entity_id: str) -> str:
    """Read back a vacuum's state + battery + fan speed."""
    try:
        state = await read_state(entity_id)
        attrs = state.get("attributes", {})
        fn = attrs.get(
            "friendly_name", friendly_name(entity_id)
        )
        parts = [f"{fn}: {state.get('state', 'unknown')}"]
        if "battery_level" in attrs:
            parts.append(
                f"battery {attrs['battery_level']}%"
            )
        if "fan_speed" in attrs:
            parts.append(
                f"fan speed: {attrs['fan_speed']}"
            )
        return ", ".join(parts)
    except Exception:
        return (
            f"{friendly_name(entity_id)}: "
            "(state unconfirmed)"
        )


@tool(
    description=(
        "Control a robot vacuum: start cleaning, pause, "
        "stop, return to base, or locate. Optionally set "
        "fan speed. Vacuums: Roborock Qrevo S "
        "(vacuum.roborock_qrevo_s), Dusty "
        "(vacuum.dusty), Hairy (vacuum.hairy)."
    ),
    parameters={
        "type": "object",
        "properties": {
            "entity_id": {
                "type": "string",
                "description": (
                    "Vacuum entity ID, e.g. "
                    "'vacuum.roborock_qrevo_s', "
                    "'vacuum.dusty', 'vacuum.hairy'."
                ),
            },
            "action": {
                "type": "string",
                "enum": [
                    "start",
                    "pause",
                    "stop",
                    "return_to_base",
                    "locate",
                ],
                "description": (
                    "Action to perform on the vacuum."
                ),
            },
            "fan_speed": {
                "type": "string",
                "description": (
                    "Fan speed: 'quiet', 'balanced', "
                    "'turbo', 'max'. Optional."
                ),
            },
        },
        "required": ["entity_id", "action"],
    },
)
async def control_vacuum(
    entity_id: str,
    action: str,
    fan_speed: str | None = None,
) -> str:
    """Control a robot vacuum."""
    try:
        svc_map = {
            "start": "start",
            "pause": "pause",
            "stop": "stop",
            "return_to_base": "return_to_base",
            "locate": "locate",
        }
        service = svc_map.get(action)
        if not service:
            return f"Unknown vacuum action: {action}"

        await call_ha_service(
            "vacuum", service, entity_id
        )

        if fan_speed is not None:
            await call_ha_service(
                "vacuum",
                "set_fan_speed",
                entity_id,
                {"fan_speed": fan_speed},
            )

        status = await _verify_vacuum(entity_id)
        return f"Done. {status}"

    except httpx.HTTPStatusError as e:
        return format_ha_error(entity_id, "vacuum", e)
    except Exception as e:
        return f"Error controlling vacuum: {e}"
