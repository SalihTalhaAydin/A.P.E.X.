"""
Lock control tool for Home Assistant smart locks.
Supports lock, unlock, and open (for locks with the open feature).
Handles jammed/unavailable states gracefully.
"""

import httpx

from tools.base import tool
from tools.ha_helpers import (
    call_ha_service,
    format_ha_error,
    friendly_name,
    read_state,
)


async def _verify_lock(entity_id: str) -> str:
    """Read back a lock's state and return a human-readable summary."""
    try:
        state = await read_state(entity_id)
        attrs = state.get("attributes", {})
        fn = attrs.get(
            "friendly_name", friendly_name(entity_id)
        )
        current = state.get("state", "unknown")
        parts = [f"{fn}: {current}"]
        if current == "jammed":
            parts.append("(lock is jammed!)")
        if current == "unavailable":
            parts.append("(device unavailable)")
        if "battery_level" in attrs:
            parts.append(
                f"battery {attrs['battery_level']}%"
            )
        return ", ".join(parts)
    except Exception:
        return (
            f"{friendly_name(entity_id)}: "
            "(state unconfirmed)"
        )


@tool(
    description=(
        "Control a smart lock: lock, unlock, or open "
        "(for locks with open feature like electric "
        "strikes). Returns current lock state after "
        "action. Handles jammed/unavailable states."
    ),
    parameters={
        "type": "object",
        "properties": {
            "entity_id": {
                "type": "string",
                "description": (
                    "Lock entity ID, e.g. "
                    "'lock.front_door', "
                    "'lock.garage_entry'."
                ),
            },
            "action": {
                "type": "string",
                "enum": ["lock", "unlock", "open"],
                "description": (
                    "Action: 'lock', 'unlock', or "
                    "'open' (electric strike/latch)."
                ),
            },
        },
        "required": ["entity_id", "action"],
    },
)
async def control_lock(
    entity_id: str,
    action: str,
) -> str:
    """Control a smart lock."""
    try:
        # Check current state first
        pre_state = await read_state(entity_id)
        current = pre_state.get("state", "unknown")

        if current == "unavailable":
            return (
                f"Error: {friendly_name(entity_id)} is "
                "unavailable. Check the device connection."
            )

        if current == "jammed":
            return (
                f"Warning: {friendly_name(entity_id)} "
                "is jammed. Manual intervention may be "
                "required."
            )

        svc_map = {
            "lock": "lock",
            "unlock": "unlock",
            "open": "open",
        }
        service = svc_map.get(action)
        if not service:
            return f"Unknown lock action: {action}"

        await call_ha_service(
            "lock", service, entity_id
        )

        status = await _verify_lock(entity_id)
        return f"Done. {status}"

    except httpx.HTTPStatusError as e:
        return format_ha_error(entity_id, "lock", e)
    except Exception as e:
        return f"Error controlling lock: {e}"
