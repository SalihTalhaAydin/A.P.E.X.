"""
Automation & Scene tools for Home Assistant.
List, trigger, enable/disable automations; list and activate scenes.
"""

import httpx

from tools.base import tool
from tools.ha_helpers import (
    call_ha_service,
    format_ha_error,
    ha_request,
    verify_generic,
)


@tool(
    description=(
        "List all Home Assistant automations with their "
        "current state (on = enabled, off = disabled). "
        "Optionally filter by area/room name."
    ),
    parameters={
        "type": "object",
        "properties": {
            "area": {
                "type": "string",
                "description": (
                    "Filter by room/area name "
                    "(e.g. 'bedroom', 'kitchen'). "
                    "Optional."
                ),
            },
        },
        "required": [],
    },
)
async def list_automations(area: str = "") -> str:
    """List all HA automations."""
    try:
        states = await ha_request("GET", "/states")
        automations = [
            s
            for s in states
            if s["entity_id"].startswith("automation.")
        ]

        if area:
            area_lower = area.lower()
            automations = [
                a
                for a in automations
                if area_lower
                in a.get("attributes", {})
                .get("friendly_name", "")
                .lower()
            ]

        if not automations:
            suffix = f" matching '{area}'" if area else ""
            return f"No automations found{suffix}."

        lines = []
        for a in automations:
            name = a.get("attributes", {}).get(
                "friendly_name", a["entity_id"]
            )
            state = a.get("state", "unknown")
            eid = a["entity_id"]
            lines.append(
                f"- {name} ({eid}): {state}"
            )

        return (
            f"Found {len(lines)} automation(s):\n"
            + "\n".join(lines)
        )
    except httpx.HTTPStatusError as e:
        return format_ha_error(
            "automation.*", "automation", e
        )
    except Exception as e:
        return f"Error listing automations: {e}"


@tool(
    description=(
        "Trigger (run) a Home Assistant automation "
        "manually. The automation runs its actions once."
    ),
    parameters={
        "type": "object",
        "properties": {
            "entity_id": {
                "type": "string",
                "description": (
                    "Automation entity ID, e.g. "
                    "'automation.motion_lights'."
                ),
            },
        },
        "required": ["entity_id"],
    },
)
async def trigger_automation(
    entity_id: str,
) -> str:
    """Trigger an automation."""
    try:
        await call_ha_service(
            "automation", "trigger", entity_id
        )
        return (
            f"Done. Triggered {entity_id}."
        )
    except httpx.HTTPStatusError as e:
        return format_ha_error(
            entity_id, "automation", e
        )
    except Exception as e:
        return f"Error triggering automation: {e}"


@tool(
    description=(
        "Enable, disable, or toggle a Home Assistant "
        "automation. Disabled automations won't fire."
    ),
    parameters={
        "type": "object",
        "properties": {
            "entity_id": {
                "type": "string",
                "description": (
                    "Automation entity ID, e.g. "
                    "'automation.motion_lights'."
                ),
            },
            "action": {
                "type": "string",
                "enum": [
                    "enable",
                    "disable",
                    "toggle",
                ],
                "description": (
                    "Enable, disable, or toggle "
                    "the automation."
                ),
            },
        },
        "required": ["entity_id", "action"],
    },
)
async def toggle_automation(
    entity_id: str, action: str
) -> str:
    """Enable, disable, or toggle an automation."""
    try:
        svc_map = {
            "enable": "turn_on",
            "disable": "turn_off",
            "toggle": "toggle",
        }
        service = svc_map.get(action)
        if not service:
            return f"Unknown action: {action}"

        await call_ha_service(
            "automation", service, entity_id
        )
        status = await verify_generic(entity_id)
        return f"Done. {status}"

    except httpx.HTTPStatusError as e:
        return format_ha_error(
            entity_id, "automation", e
        )
    except Exception as e:
        return (
            f"Error toggling automation: {e}"
        )


@tool(
    description=(
        "List all available scenes in Home Assistant. "
        "Optionally filter by area/room name."
    ),
    parameters={
        "type": "object",
        "properties": {
            "area": {
                "type": "string",
                "description": (
                    "Filter by room/area name "
                    "(e.g. 'bedroom', 'living room'). "
                    "Optional."
                ),
            },
        },
        "required": [],
    },
)
async def list_scenes(area: str = "") -> str:
    """List all HA scenes."""
    try:
        states = await ha_request("GET", "/states")
        scenes = [
            s
            for s in states
            if s["entity_id"].startswith("scene.")
        ]

        if area:
            area_lower = area.lower()
            scenes = [
                s
                for s in scenes
                if area_lower
                in s.get("attributes", {})
                .get("friendly_name", "")
                .lower()
            ]

        if not scenes:
            suffix = f" matching '{area}'" if area else ""
            return f"No scenes found{suffix}."

        lines = []
        for s in scenes:
            name = s.get("attributes", {}).get(
                "friendly_name", s["entity_id"]
            )
            eid = s["entity_id"]
            lines.append(f"- {name} ({eid})")

        return (
            f"Found {len(lines)} scene(s):\n"
            + "\n".join(lines)
        )
    except httpx.HTTPStatusError as e:
        return format_ha_error("scene.*", "scene", e)
    except Exception as e:
        return f"Error listing scenes: {e}"


@tool(
    description=(
        "Activate (turn on) a Home Assistant scene. "
        "Scenes set multiple devices to predefined "
        "states at once (e.g. 'movie mode')."
    ),
    parameters={
        "type": "object",
        "properties": {
            "entity_id": {
                "type": "string",
                "description": (
                    "Scene entity ID, e.g. "
                    "'scene.movie_mode', "
                    "'scene.bedtime'."
                ),
            },
        },
        "required": ["entity_id"],
    },
)
async def activate_scene(entity_id: str) -> str:
    """Activate a scene."""
    try:
        await call_ha_service(
            "scene", "turn_on", entity_id
        )
        return (
            f"Done. Activated {entity_id}."
        )
    except httpx.HTTPStatusError as e:
        return format_ha_error(
            entity_id, "scene", e
        )
    except Exception as e:
        return f"Error activating scene: {e}"
