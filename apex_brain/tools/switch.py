"""
Switch and input_boolean control tool for Home Assistant.
Auto-detects the domain from the entity_id prefix and calls
the correct HA service.
"""

import httpx

from tools.base import tool
from tools.ha_helpers import (
    call_ha_service,
    format_ha_error,
    friendly_name,
    read_state,
)


async def _verify_switch(entity_id: str) -> str:
    """Read back a switch/input_boolean state."""
    try:
        state = await read_state(entity_id)
        attrs = state.get("attributes", {})
        fn = attrs.get(
            "friendly_name", friendly_name(entity_id)
        )
        current = state.get("state", "unknown")
        parts = [f"{fn}: {current}"]
        if (
            "current_power_w" in attrs
            and attrs["current_power_w"] is not None
        ):
            parts.append(
                f"{attrs['current_power_w']}W"
            )
        if (
            "today_energy_kwh" in attrs
            and attrs["today_energy_kwh"] is not None
        ):
            parts.append(
                f"{attrs['today_energy_kwh']} kWh today"
            )
        return ", ".join(parts)
    except Exception:
        return (
            f"{friendly_name(entity_id)}: "
            "(state unconfirmed)"
        )


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

        await call_ha_service(
            domain, service, entity_id
        )

        status = await _verify_switch(entity_id)
        return f"Done. {status}"

    except httpx.HTTPStatusError as e:
        return format_ha_error(entity_id, "switch", e)
    except Exception as e:
        return f"Error controlling switch: {e}"
