"""
Automation & Scene tools for Home Assistant.
List, trigger, enable/disable, create, update, delete automations;
list and activate scenes.
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
            s for s in states if s["entity_id"].startswith("automation.")
        ]

        if area:
            area_lower = area.lower()
            automations = [
                a
                for a in automations
                if area_lower
                in a.get("attributes", {}).get("friendly_name", "").lower()
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
            lines.append(f"- {name} ({eid}): {state}")

        return f"Found {len(lines)} automation(s):\n" + "\n".join(lines)
    except httpx.HTTPStatusError as e:
        return format_ha_error("automation.*", "automation", e)
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
        await call_ha_service("automation", "trigger", entity_id)
        return f"Done. Triggered {entity_id}."
    except httpx.HTTPStatusError as e:
        return format_ha_error(entity_id, "automation", e)
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
                    "Enable, disable, or toggle the automation."
                ),
            },
        },
        "required": ["entity_id", "action"],
    },
)
async def toggle_automation(entity_id: str, action: str) -> str:
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

        await call_ha_service("automation", service, entity_id)
        status = await verify_generic(entity_id)
        return f"Done. {status}"

    except httpx.HTTPStatusError as e:
        return format_ha_error(entity_id, "automation", e)
    except Exception as e:
        return f"Error toggling automation: {e}"


@tool(
    description=(
        "Create a new Home Assistant automation. "
        "Define triggers, conditions, and actions. "
        "The automation is saved to HA and becomes "
        "active immediately. Use for 'create an "
        "automation that turns on lights at sunset', "
        "'make an automation for motion detection'."
    ),
    parameters={
        "type": "object",
        "properties": {
            "alias": {
                "type": "string",
                "description": (
                    "Human-readable name for the "
                    "automation, e.g. 'Turn on porch "
                    "light at sunset'."
                ),
            },
            "description": {
                "type": "string",
                "description": (
                    "Optional description of what the automation does."
                ),
            },
            "triggers": {
                "type": "array",
                "items": {"type": "object"},
                "description": (
                    "List of trigger objects. Each "
                    "must have 'trigger' (platform "
                    "type) plus platform-specific "
                    "fields. Examples:\n"
                    '- {"trigger": "state", '
                    '"entity_id": "binary_sensor.'
                    'motion", "to": "on"}\n'
                    '- {"trigger": "sun", '
                    '"event": "sunset"}\n'
                    '- {"trigger": "time", '
                    '"at": "07:00:00"}'
                ),
            },
            "conditions": {
                "type": "array",
                "items": {"type": "object"},
                "description": (
                    "Optional list of conditions. "
                    'Example: [{"condition": '
                    '"state", "entity_id": '
                    '"person.salih", "state": '
                    '"home"}]'
                ),
            },
            "actions": {
                "type": "array",
                "items": {"type": "object"},
                "description": (
                    "List of actions. Examples:\n"
                    '- {"action": "light.turn_on'
                    '", "target": {"entity_id": '
                    '"light.porch"}}\n'
                    '- {"action": "notify.mobile'
                    '", "data": {"message": '
                    '"Motion detected!"}}'
                ),
            },
            "mode": {
                "type": "string",
                "description": (
                    "Automation mode: 'single', "
                    "'restart', 'queued', 'parallel'. "
                    "Default: 'single'."
                ),
            },
        },
        "required": ["alias", "triggers", "actions"],
    },
)
async def create_automation(
    alias: str,
    triggers: list,
    actions: list,
    conditions: list | None = None,
    description: str = "",
    mode: str = "single",
) -> str:
    """Create a new HA automation via the config API."""
    try:
        import secrets

        auto_id = secrets.token_hex(6)

        payload = {
            "id": auto_id,
            "alias": alias,
            "description": description,
            "trigger": triggers,
            "condition": conditions or [],
            "action": actions,
            "mode": mode,
        }

        await ha_request(
            "POST",
            "/config/automation/config/" + auto_id,
            json_data=payload,
        )

        return (
            f"Done. Created automation '{alias}' "
            f"(id: {auto_id}). It is now active."
        )
    except httpx.HTTPStatusError as e:
        return format_ha_error(
            f"automation.{alias}",
            "automation",
            e,
        )
    except Exception as e:
        return f"Error creating automation: {e}"


@tool(
    description=(
        "Update an existing Home Assistant automation. "
        "Provide the automation ID and the fields to "
        "change. Use list_automations to find IDs."
    ),
    parameters={
        "type": "object",
        "properties": {
            "automation_id": {
                "type": "string",
                "description": (
                    "The automation config ID "
                    "(not entity_id). Get from "
                    "automation attributes or HA UI."
                ),
            },
            "alias": {
                "type": "string",
                "description": ("New name. Optional."),
            },
            "triggers": {
                "type": "array",
                "items": {"type": "object"},
                "description": ("Replacement triggers. Optional."),
            },
            "conditions": {
                "type": "array",
                "items": {"type": "object"},
                "description": ("Replacement conditions. Optional."),
            },
            "actions": {
                "type": "array",
                "items": {"type": "object"},
                "description": ("Replacement actions. Optional."),
            },
            "description": {
                "type": "string",
                "description": ("New description. Optional."),
            },
        },
        "required": ["automation_id"],
    },
)
async def update_automation(
    automation_id: str,
    alias: str | None = None,
    triggers: list | None = None,
    conditions: list | None = None,
    actions: list | None = None,
    description: str | None = None,
) -> str:
    """Update an existing HA automation."""
    try:
        # Get current config first
        current = await ha_request(
            "GET",
            f"/config/automation/config/{automation_id}",
        )
        if not isinstance(current, dict):
            return f"Automation '{automation_id}' not found."

        # Merge updates
        if alias is not None:
            current["alias"] = alias
        if triggers is not None:
            current["trigger"] = triggers
        if conditions is not None:
            current["condition"] = conditions
        if actions is not None:
            current["action"] = actions
        if description is not None:
            current["description"] = description

        await ha_request(
            "POST",
            f"/config/automation/config/{automation_id}",
            json_data=current,
        )

        name = current.get("alias", automation_id)
        return f"Done. Updated automation '{name}'."

    except httpx.HTTPStatusError as e:
        return format_ha_error(automation_id, "automation", e)
    except Exception as e:
        return f"Error updating automation: {e}"


@tool(
    description=(
        "Delete a Home Assistant automation permanently. Use with caution."
    ),
    parameters={
        "type": "object",
        "properties": {
            "automation_id": {
                "type": "string",
                "description": ("The automation config ID to delete."),
            },
        },
        "required": ["automation_id"],
    },
)
async def delete_automation(
    automation_id: str,
) -> str:
    """Delete an HA automation."""
    try:
        await ha_request(
            "DELETE",
            f"/config/automation/config/{automation_id}",
        )
        return f"Done. Deleted automation '{automation_id}'."
    except httpx.HTTPStatusError as e:
        return format_ha_error(automation_id, "automation", e)
    except Exception as e:
        return f"Error deleting automation: {e}"


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
        scenes = [s for s in states if s["entity_id"].startswith("scene.")]

        if area:
            area_lower = area.lower()
            scenes = [
                s
                for s in scenes
                if area_lower
                in s.get("attributes", {}).get("friendly_name", "").lower()
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

        return f"Found {len(lines)} scene(s):\n" + "\n".join(lines)
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
        await call_ha_service("scene", "turn_on", entity_id)
        return f"Done. Activated {entity_id}."
    except httpx.HTTPStatusError as e:
        return format_ha_error(entity_id, "scene", e)
    except Exception as e:
        return f"Error activating scene: {e}"
