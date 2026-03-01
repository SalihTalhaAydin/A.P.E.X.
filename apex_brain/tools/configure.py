"""
Entity/Device/Area registry management via WebSocket API.
Rename entities, manage areas, disable/enable entities,
clean up stale devices.

Implements tiered confirmation with dry-run mode:
  Tier 0 (Safe): rename, assign_area, enable, create_area,
                  list_stale
  Tier 1 (Moderate): disable, delete_area
  Tier 2 (Destructive): remove (device)
"""

from __future__ import annotations

import logging

from tools.base import tool
from tools.ws_helpers import ws_command

logger = logging.getLogger(__name__)


def _check_ws_result(
    result, fallback_msg: str = "Operation failed."
) -> str | None:
    """Check ws_command result; return error message if invalid, None if OK."""
    if result is None:
        return "Error: No response from Home Assistant."
    if not isinstance(result, dict):
        return "Error: Unexpected response type from Home Assistant."
    if result.get("success") is False or "error" in result:
        err = result.get("error", {})
        if isinstance(err, dict):
            msg = err.get("message", err.get("code", "unknown"))
        else:
            msg = str(err)
        return f"Error: {msg}"
    return None


# --- Tier classification ---

_TIER_0_SAFE: set[str] = {
    "rename",
    "assign_area",
    "enable",
    "create_area",
    "list_stale",
}

_TIER_2_DESTRUCTIVE: set[str] = {
    "remove",
}

# Everything else is Tier 1 (moderate)


def _get_tier(action: str) -> int:
    """Determine confirmation tier for a configure op."""
    if action in _TIER_0_SAFE:
        return 0
    if action in _TIER_2_DESTRUCTIVE:
        return 2
    return 1


def _confirmation_prompt(
    action: str,
    target: str,
    tier: int,
    detail: str = "",
) -> str:
    """Build a confirmation prompt."""
    labels = {1: "MODERATE", 2: "DESTRUCTIVE"}
    label = labels.get(tier, "REQUIRES CONFIRMATION")
    msg = (
        f"⚠ {label} OPERATION: {action} {target}\n"
        f"{detail}\n"
        f"To execute, call configure() again with "
        f'data={{"confirmed": true}}'
    )
    return msg.strip()


# --- Action handlers ---


async def _handle_rename(target: str, data: dict) -> str:
    """Rename an entity."""
    name = data.get("name", "")
    if not name:
        return "Error: data.name is required for rename."
    if not target:
        return "Error: target (entity_id) is required."

    try:
        result = await ws_command(
            {
                "type": "config/entity_registry/update",
                "entity_id": target,
                "name": name,
            }
        )
    except (ConnectionError, PermissionError, TimeoutError):
        raise
    except Exception as e:
        return f"Error: {e}"
    err = _check_ws_result(result)
    if err:
        return err
    new_name = result.get("name", name)
    return f"Renamed {target} to '{new_name}'."


async def _handle_assign_area(target: str, data: dict) -> str:
    """Assign an entity or device to an area."""
    area_id = data.get("area_id", "")
    if not area_id:
        return "Error: data.area_id is required for assign_area."
    if not target:
        return "Error: target is required."

    # Detect if target is a device_id or entity_id
    if "." in target:
        # Entity ID (contains domain.name)
        try:
            result = await ws_command(
                {
                    "type": "config/entity_registry/update",
                    "entity_id": target,
                    "area_id": area_id,
                }
            )
        except Exception as e:
            return f"Error: {e}"
    else:
        # Device ID
        try:
            result = await ws_command(
                {
                    "type": "config/device_registry/update",
                    "device_id": target,
                    "area_id": area_id,
                }
            )
        except Exception as e:
            return f"Error: {e}"
    err = _check_ws_result(result)
    if err:
        return err
    return (
        f"Assigned entity {target} to area '{area_id}'."
        if "." in target
        else f"Assigned device {target} to area '{area_id}'."
    )


async def _handle_disable(target: str, data: dict) -> str:
    """Disable an entity."""
    if not target:
        return "Error: target (entity_id) is required."

    try:
        result = await ws_command(
            {
                "type": "config/entity_registry/update",
                "entity_id": target,
                "disabled_by": "user",
            }
        )
    except (ConnectionError, PermissionError, TimeoutError):
        raise
    except Exception as e:
        return f"Error: {e}"
    err = _check_ws_result(result)
    if err:
        return err
    return f"Disabled entity {target}."


async def _handle_enable(target: str, data: dict) -> str:
    """Enable a previously disabled entity."""
    if not target:
        return "Error: target (entity_id) is required."

    try:
        result = await ws_command(
            {
                "type": "config/entity_registry/update",
                "entity_id": target,
                "disabled_by": "",
            }
        )
    except (ConnectionError, PermissionError, TimeoutError):
        raise
    except Exception as e:
        return f"Error: {e}"
    err = _check_ws_result(result)
    if err:
        return err
    return f"Enabled entity {target}."


async def _handle_create_area(target: str, data: dict) -> str:
    """Create a new area."""
    name = data.get("name", "") or target
    if not name:
        return "Error: data.name or target is required for create_area."

    try:
        result = await ws_command(
            {
                "type": "config/area_registry/create",
                "name": name,
            }
        )
    except Exception as e:
        return f"Error: {e}"
    err = _check_ws_result(result)
    if err:
        return err
    area_id = result.get("area_id", "") if isinstance(result, dict) else ""
    return f"Area '{name}' created (id: {area_id})."


async def _handle_delete_area(target: str, data: dict) -> str:
    """Delete an area."""
    if not target:
        return "Error: target (area_id) is required."

    try:
        result = await ws_command(
            {
                "type": "config/area_registry/delete",
                "area_id": target,
            }
        )
    except Exception as e:
        return f"Error: {e}"
    err = _check_ws_result(result)
    if err:
        return err
    return f"Area '{target}' deleted."


async def _handle_remove(target: str, data: dict) -> str:
    """Remove a device from the registry."""
    if not target:
        return "Error: target (device_id) is required."

    try:
        result = await ws_command(
            {
                "type": "config/device_registry/remove",
                "device_id": target,
            }
        )
    except Exception as e:
        return f"Error: {e}"
    err = _check_ws_result(result)
    if err:
        return err
    return (
        f"Device '{target}' removed from registry. "
        f"All associated entities have been deleted."
    )


async def _handle_list_stale(target: str, data: dict) -> str:
    """List entities stuck in unavailable/unknown state."""
    from tools.ha_helpers import ha_request

    try:
        result = await ws_command({"type": "config/entity_registry/list"})
    except Exception as e:
        return f"Error: {e}"
    # result is a list of entity entries; ws_command can return None or non-list
    entities = (
        result
        if isinstance(result, list)
        else ([] if result is None else [])
    )

    # Build set of non-disabled entity IDs
    active_ids: set[str] = set()
    name_map: dict[str, str] = {}
    for entry in entities:
        if entry.get("disabled_by"):
            continue
        eid = entry.get("entity_id", "")
        if eid:
            active_ids.add(eid)
            name_map[eid] = entry.get("name") or entry.get(
                "original_name", eid
            )

    if not active_ids:
        return "No active entities in registry."

    # Cross-reference with actual HA states
    try:
        states = await ha_request("GET", "/states")
    except Exception as e:
        return f"Could not fetch entity states: {e}"

    stale = []
    if isinstance(states, list):
        for s in states:
            eid = s.get("entity_id", "")
            state = s.get("state", "")
            if eid in active_ids and state in ("unavailable", "unknown"):
                name = name_map.get(eid, eid)
                stale.append(f"  - {name} ({eid}): {state}")

    if not stale:
        return "No stale entities found."

    return f"Found {len(stale)} stale entities:\n" + "\n".join(stale)


# --- Dry-run handlers ---


async def _dry_run_disable(target: str, data: dict) -> str:
    """Show what disabling an entity would do."""
    return (
        f"DRY RUN: Would disable entity {target}. "
        f"This will prevent it from updating state "
        f"and remove it from dashboards/automations "
        f"that reference it."
    )


async def _dry_run_delete_area(target: str, data: dict) -> str:
    """Show what deleting an area would do."""
    return (
        f"DRY RUN: Would delete area '{target}'. "
        f"All entities and devices currently assigned "
        f"to this area will become unassigned."
    )


async def _dry_run_remove(target: str, data: dict) -> str:
    """Show what removing a device would do."""
    return (
        f"DRY RUN: Would remove device '{target}' "
        f"and ALL its entities from HA. This is "
        f"permanent. Re-adding requires re-discovery "
        f"or re-configuration."
    )


_DRY_RUN_HANDLERS: dict = {
    "disable": _dry_run_disable,
    "delete_area": _dry_run_delete_area,
    "remove": _dry_run_remove,
}


# --- Action router ---

_HANDLERS = {
    "rename": _handle_rename,
    "assign_area": _handle_assign_area,
    "disable": _handle_disable,
    "enable": _handle_enable,
    "create_area": _handle_create_area,
    "delete_area": _handle_delete_area,
    "remove": _handle_remove,
    "list_stale": _handle_list_stale,
}

# Module-level audit store reference
_audit_store = None


def set_audit_store(store) -> None:
    """Inject the audit store at application startup."""
    global _audit_store
    _audit_store = store


@tool(
    description=(
        "Organize HA: rename entities, manage areas, "
        "configure integrations, clean up stale devices. "
        "Uses WebSocket API for registry operations. "
        "Safe operations execute immediately. "
        "Destructive operations support dry-run mode "
        "(data={'dry_run': true}) and require "
        "confirmation (data={'confirmed': true})."
    )
)
async def configure(
    action: str,
    target: str = "",
    data: dict | None = None,
    session_id: str = "default",
) -> str:
    """Registry operations via HA WebSocket API.

    action: rename, assign_area, disable, enable,
            create_area, delete_area, remove, list_stale
    target: entity_id, device_id, or area name/id
    data: operation-specific data (name, area_id, etc.)
          Use data={"dry_run": true} for preview.
          Use data={"confirmed": true} to confirm.
    session_id: originating session for audit logging.
    """
    data = data or {}
    tier = _get_tier(action)

    # Session-based escalation: event sessions
    # (apex_events*) restricted to Tier 0
    if (session_id or "").startswith("apex_events") and tier > 0:
        msg = (
            f"Operation '{action} {target}' requires "
            f"Tier {tier} access. Webhook sessions "
            f"(apex_events) are restricted to safe "
            f"(Tier 0) operations only."
        )
        if _audit_store:
            await _audit_store.log(
                tool="configure",
                action=action,
                target=target,
                config=data,
                result="denied",
                session_id=session_id,
                user_approved=False,
            )
        return msg

    # Dry-run mode for Tier 1/2 operations
    if data.get("dry_run") and tier > 0:
        dry_handler = _DRY_RUN_HANDLERS.get(action)
        if dry_handler:
            result = await dry_handler(target, data)
            if _audit_store:
                await _audit_store.log(
                    tool="configure",
                    action=action,
                    target=target,
                    config=data,
                    result="dry_run",
                    session_id=session_id,
                    user_approved=False,
                )
            return result

    # Tier 1/2: require confirmation
    if tier > 0 and not data.get("confirmed"):
        detail = ""
        if tier == 1:
            detail = (
                "This operation may affect entity "
                "availability or area organization."
            )
        elif tier == 2:
            detail = (
                "This is a PERMANENT operation that "
                "cannot be easily undone."
            )
        prompt = _confirmation_prompt(action, target, tier, detail)
        if _audit_store:
            await _audit_store.log(
                tool="configure",
                action=action,
                target=target,
                config=data,
                result="confirmation_prompted",
                session_id=session_id,
                user_approved=False,
            )
        return prompt

    # Execute the operation
    handler = _HANDLERS.get(action)
    if not handler:
        return (
            f"Unknown action: {action}. "
            f"Valid actions: "
            f"{', '.join(sorted(_HANDLERS.keys()))}"
        )

    try:
        result = await handler(target, data)
    except RuntimeError as e:
        result = f"Error: {e}"
    except ConnectionError as e:
        result = f"Connection error: {e}"
    except PermissionError as e:
        result = f"Auth error: {e}"
    except TimeoutError as e:
        result = f"Timeout: {e}"
    except Exception as e:
        result = f"Error: {e}"

    # Audit log
    if _audit_store:
        await _audit_store.log(
            tool="configure",
            action=action,
            target=target,
            config=data,
            result="executed",
            session_id=session_id,
            user_approved=tier > 0,
        )

    return result
