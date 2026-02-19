"""
Security tools for Home Assistant alarm panels and cameras.
- control_alarm: arm/disarm alarm control panels with optional PIN code.
- get_camera_snapshot: returns the HA proxy URL for a camera snapshot.
- get_camera_state: returns camera recording/streaming state.

DEPRECATED: control_alarm is a thin wrapper that delegates to the generic
do() tool in tools.generic. Use do() directly for new code.
Camera tools are kept as-is (no generic equivalent).
"""

from __future__ import annotations

import logging

import httpx

from tools.base import tool
from tools.generic import do
from tools.ha_helpers import (
    format_ha_error,
    friendly_name,
    read_state,
)

from brain.config import settings

logger = logging.getLogger(__name__)


# --------------------------------------------------
# Alarm control tool
# --------------------------------------------------


@tool(
    description=(
        "Control an alarm panel: arm home, arm away, "
        "arm night, disarm, or trigger. Some systems "
        "require a PIN code to arm/disarm."
    ),
    parameters={
        "type": "object",
        "properties": {
            "entity_id": {
                "type": "string",
                "description": (
                    "Alarm panel entity ID, e.g. "
                    "'alarm_control_panel.home_alarm'."
                ),
            },
            "action": {
                "type": "string",
                "enum": [
                    "arm_home",
                    "arm_away",
                    "arm_night",
                    "disarm",
                    "trigger",
                ],
                "description": (
                    "Action: 'arm_home', 'arm_away', "
                    "'arm_night', 'disarm', or "
                    "'trigger'."
                ),
            },
            "code": {
                "type": "string",
                "description": (
                    "PIN code for arming/disarming. "
                    "Optional (depends on system "
                    "configuration)."
                ),
            },
        },
        "required": ["entity_id", "action"],
    },
)
async def control_alarm(
    entity_id: str,
    action: str,
    code: str | None = None,
) -> str:
    """Control an alarm control panel."""
    logger.warning(
        "DEPRECATED: %s() called — use %s() instead",
        "control_alarm", "do",
    )
    try:
        svc_map = {
            "arm_home": "alarm_arm_home",
            "arm_away": "alarm_arm_away",
            "arm_night": "alarm_arm_night",
            "disarm": "alarm_disarm",
            "trigger": "alarm_trigger",
        }
        service = svc_map.get(action)
        if not service:
            return f"Unknown alarm action: {action}"

        return await do(
            "alarm_control_panel",
            service,
            {"entity_id": entity_id},
            {"code": code} if code else None,
        )

    except Exception as e:
        return f"Error controlling alarm: {e}"


# --------------------------------------------------
# Camera tools (kept as-is, no generic equivalent)
# --------------------------------------------------


@tool(
    description=(
        "Get a camera snapshot proxy URL. Returns the "
        "HA API URL that serves the latest camera image. "
        "Use this to show or reference a camera snapshot."
    ),
    parameters={
        "type": "object",
        "properties": {
            "entity_id": {
                "type": "string",
                "description": (
                    "Camera entity ID, e.g. "
                    "'camera.front_door', "
                    "'camera.backyard'."
                ),
            },
        },
        "required": ["entity_id"],
    },
)
async def get_camera_snapshot(
    entity_id: str,
) -> str:
    """Return the proxy URL for a camera snapshot."""
    try:
        # Verify the camera entity exists
        state = await read_state(entity_id)
        current = state.get("state", "unknown")

        if current == "unavailable":
            return (
                f"Error: {friendly_name(entity_id)} is "
                "unavailable. Check the camera "
                "connection."
            )

        fn = state.get("attributes", {}).get(
            "friendly_name", friendly_name(entity_id)
        )

        proxy_url = (
            f"{settings.ha_api_url}"
            f"/camera_proxy/{entity_id}"
        )
        return (
            f"{fn} snapshot URL: {proxy_url} "
            f"(camera state: {current})"
        )

    except httpx.HTTPStatusError as e:
        return format_ha_error(entity_id, "camera", e)
    except Exception as e:
        return f"Error getting camera snapshot: {e}"


@tool(
    description=(
        "Get a camera's current state and attributes "
        "(recording, streaming, motion detected, etc.)."
    ),
    parameters={
        "type": "object",
        "properties": {
            "entity_id": {
                "type": "string",
                "description": (
                    "Camera entity ID, e.g. "
                    "'camera.front_door', "
                    "'camera.backyard'."
                ),
            },
        },
        "required": ["entity_id"],
    },
)
async def get_camera_state(
    entity_id: str,
) -> str:
    """Return a camera's current state and details."""
    try:
        state = await read_state(entity_id)
        attrs = state.get("attributes", {})
        fn = attrs.get(
            "friendly_name", friendly_name(entity_id)
        )
        current = state.get("state", "unknown")

        parts = [f"{fn} ({entity_id}): {current}"]

        if "is_recording" in attrs:
            recording = attrs["is_recording"]
            parts.append(
                f"recording: {'yes' if recording else 'no'}"
            )
        if "is_streaming" in attrs:
            streaming = attrs["is_streaming"]
            parts.append(
                f"streaming: {'yes' if streaming else 'no'}"
            )
        if "motion_detection" in attrs:
            motion = attrs["motion_detection"]
            parts.append(
                f"motion detection: "
                f"{'enabled' if motion else 'disabled'}"
            )
        if "frontend_stream_type" in attrs:
            parts.append(
                f"stream type: "
                f"{attrs['frontend_stream_type']}"
            )
        if "brand" in attrs:
            parts.append(f"brand: {attrs['brand']}")
        if "model" in attrs:
            parts.append(f"model: {attrs['model']}")

        return "\n  ".join(parts)

    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            return f"Camera '{entity_id}' not found."
        return format_ha_error(entity_id, "camera", e)
    except Exception as e:
        return f"Error getting camera state: {e}"
