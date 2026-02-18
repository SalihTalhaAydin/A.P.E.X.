"""
Vacuum control tool for Home Assistant robot vacuums.
Supports start, pause, stop, return-to-base, locate, fan speed,
and room-level segment cleaning (Roborock and compatible vacuums).
"""

from __future__ import annotations

import logging

import httpx

from tools.base import tool
from tools.ha_helpers import (
    call_ha_service,
    format_ha_error,
    friendly_name,
    get_battery_level,
    ha_request,
    read_state,
)

logger = logging.getLogger(__name__)


async def _get_dock_status(name: str) -> dict:
    """Read dock/maintenance sensor data for a vacuum.

    ``name`` is the entity name part, e.g. 'dusty' for
    vacuum.dusty.  Returns a dict with keys:
      water_status  – 'water_empty' | 'ok' | None
      status        – e.g. 'charging' | 'cleaning' | None
      overdue       – list of overdue component names
    """
    result: dict = {
        "water_status": None,
        "status": None,
        "overdue": [],
    }

    _MAINTENANCE = {
        f"sensor.{name}_filter_time_left": "filter",
        f"sensor.{name}_main_brush_time_left": "main brush",
        f"sensor.{name}_side_brush_time_left": "side brush",
        f"sensor.{name}_sensor_time_left": "sensors/wipes",
        f"sensor.{name}_dock_strainer_time_left": "dock strainer",
    }

    # Dock water / error status
    try:
        dock = await read_state(
            f"sensor.{name}_dock_dock_error"
        )
        val = dock.get("state", "")
        if val not in ("unavailable", "unknown", ""):
            result["water_status"] = val
    except Exception:
        pass

    # Cleaning / charging status
    try:
        status_s = await read_state(
            f"sensor.{name}_status"
        )
        val = status_s.get("state", "")
        if val not in ("unavailable", "unknown", ""):
            result["status"] = val
    except Exception:
        pass

    # Maintenance — flag anything negative (overdue)
    for sensor_id, label in _MAINTENANCE.items():
        try:
            s = await read_state(sensor_id)
            val = s.get("state", "")
            if val in ("unavailable", "unknown", ""):
                continue
            if float(val) < 0:
                result["overdue"].append(label)
        except Exception:
            pass

    return result


async def _verify_vacuum(entity_id: str) -> str:
    """Read back a vacuum's state + battery + fan speed
    + dock water status + overdue maintenance.

    Battery level is fetched via ``get_battery_level``
    which falls back to ``sensor.<name>_battery`` when
    the vacuum entity itself no longer exposes the
    attribute (common after HA integration updates).

    Water and maintenance data come from dock companion
    sensors (e.g. sensor.dusty_dock_dock_error) since
    the Roborock HA integration no longer exposes these
    as vacuum entity attributes.
    """
    try:
        state = await read_state(entity_id)
        attrs = state.get("attributes", {})
        fn = attrs.get(
            "friendly_name", friendly_name(entity_id)
        )
        vac_state = state.get("state", "unknown")
        parts = [f"{fn}: {vac_state}"]

        battery = await get_battery_level(entity_id)
        if battery is not None:
            parts.append(f"battery {battery}%")

        if "fan_speed" in attrs:
            parts.append(
                f"fan speed: {attrs['fan_speed']}"
            )

        # Water level / mop mode — try entity attrs first,
        # then fall back to dock sensor (Roborock 2024+)
        water_shown = False
        for _wattr in (
            "water_box_mode",
            "water_level",
            "mop_mode",
        ):
            if _wattr in attrs:
                label = _wattr.replace("_", " ")
                parts.append(
                    f"{label}: {attrs[_wattr]}"
                )
                water_shown = True
                break

        # Dock sensor data (covers Roborock integration
        # where attrs above are absent)
        name = entity_id.split(".", 1)[-1]
        dock = await _get_dock_status(name)

        if not water_shown and dock["water_status"]:
            ws = dock["water_status"]
            if ws == "water_empty":
                parts.append("dock water: EMPTY — needs refill")
            elif ws != "ok":
                parts.append(f"dock status: {ws}")

        if dock["status"] and vac_state == "docked":
            # Only show sensor status when entity says docked
            # (avoids redundancy when state is 'cleaning' etc.)
            parts.append(f"status: {dock['status']}")

        if dock["overdue"]:
            parts.append(
                "maintenance overdue: "
                + ", ".join(dock["overdue"])
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
        "fan speed. Use list_entities(domain='vacuum') "
        "to discover available vacuums."
    ),
    parameters={
        "type": "object",
        "properties": {
            "entity_id": {
                "type": "string",
                "description": (
                    "Vacuum entity ID (use "
                    "list_entities to discover)."
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


@tool(
    description=(
        "Get the full status of a robot vacuum: state, "
        "battery, fan speed, dock water level, and "
        "maintenance overdue alerts. Use this when the "
        "user asks 'how is the vacuum?' or 'which vacuum "
        "needs water?' without issuing a control command."
    ),
    parameters={
        "type": "object",
        "properties": {
            "entity_id": {
                "type": "string",
                "description": (
                    "Vacuum entity ID, e.g. 'vacuum.dusty'. "
                    "Use list_entities(domain='vacuum') to "
                    "discover available vacuums."
                ),
            },
        },
        "required": ["entity_id"],
    },
)
async def get_vacuum_status(entity_id: str) -> str:
    """Return a detailed status string for a vacuum."""
    try:
        return await _verify_vacuum(entity_id)
    except Exception as e:
        return f"Error reading vacuum status: {e}"


# ---------------------------------------------------------------------------
# Room-level segment cleaning (Roborock / compatible vacuums)
# ---------------------------------------------------------------------------

_ROOM_ATTR_KEYS = (
    "room_list",
    "segment_list",
    "rooms",
    "room_mapping",
)


async def _discover_vacuum() -> str | None:
    """Return the entity_id of the first available vacuum, or None."""
    try:
        states = await ha_request("GET", "/states")
        for s in states:
            if s.get("entity_id", "").startswith("vacuum."):
                return s["entity_id"]
    except Exception:
        pass
    return None


def _find_room_map(attributes: dict) -> dict:
    """Extract a segment_id → room_name mapping from vacuum attributes.

    Handles:
      - room_list / segment_list: dict mapping segment_id → name
      - rooms: either a dict or a list of dicts with id/name keys
      - map_summary.rooms: list of dicts with id/name keys
    """
    # Try flat dict attributes first
    for key in _ROOM_ATTR_KEYS:
        val = attributes.get(key)
        if not val:
            continue
        if isinstance(val, dict):
            return {str(k): str(v) for k, v in val.items()}
        if isinstance(val, list):
            mapping: dict = {}
            for item in val:
                if isinstance(item, dict):
                    seg_id = item.get("id") or item.get("segment_id")
                    name = (
                        item.get("name")
                        or item.get("room_name")
                        or item.get("friendly_name")
                    )
                    if seg_id is not None and name:
                        mapping[str(seg_id)] = str(name)
            if mapping:
                return mapping

    # Try map_summary.rooms
    map_summary = attributes.get("map_summary", {})
    if isinstance(map_summary, dict):
        rooms = map_summary.get("rooms")
        if isinstance(rooms, list):
            mapping = {}
            for item in rooms:
                if isinstance(item, dict):
                    seg_id = item.get("id") or item.get("segment_id")
                    name = item.get("name") or item.get("room_name")
                    if seg_id is not None and name:
                        mapping[str(seg_id)] = str(name)
            if mapping:
                return mapping

    return {}


def _match_rooms(
    requested: list[str], room_map: dict
) -> tuple[list[int], list[str]]:
    """Case-insensitive partial-match room names to segment IDs.

    Returns (matched_segment_ids, unmatched_names).
    """
    matched_ids: list[int] = []
    unmatched: list[str] = []

    for req in requested:
        req_lower = req.lower().strip()
        found = False
        for seg_id, room_name in room_map.items():
            if req_lower in room_name.lower():
                matched_ids.append(int(seg_id))
                found = True
                break
        if not found:
            unmatched.append(req)

    return matched_ids, unmatched


@tool(
    description=(
        "Clean specific rooms by name using a Roborock or "
        "compatible robot vacuum. Pass a list of room names "
        "(e.g. ['kitchen', 'living room']). The vacuum will "
        "clean those segments and return to base when done. "
        "entity_id is optional — if omitted the first "
        "available vacuum is used automatically."
    ),
    parameters={
        "type": "object",
        "properties": {
            "rooms": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "List of room names to clean, "
                    "e.g. ['kitchen', 'playroom']."
                ),
            },
            "entity_id": {
                "type": "string",
                "description": (
                    "Vacuum entity ID (optional). "
                    "Discovered automatically if omitted."
                ),
            },
        },
        "required": ["rooms"],
    },
)
async def clean_rooms(
    rooms: list,
    entity_id: str | None = None,
) -> str:
    """Clean specific rooms by segment ID (Roborock / compatible vacuums)."""
    # 1. Discover vacuum if not provided
    if not entity_id:
        entity_id = await _discover_vacuum()
        if not entity_id:
            return (
                "No vacuum entities found. "
                "Please provide the entity_id explicitly."
            )

    # 2. Read vacuum state to get room map
    try:
        state = await read_state(entity_id)
    except Exception as e:
        return f"Could not read vacuum state for {entity_id}: {e}"

    attributes = state.get("attributes", {})
    room_map = _find_room_map(attributes)

    # 3. Match requested room names → segment IDs
    if not room_map:
        # No room map available — fall back to a basic start
        logger.warning(
            "No room map found for %s — falling back to start",
            entity_id,
        )
        try:
            return await control_vacuum(
                entity_id=entity_id, action="start"
            )
        except Exception as e:
            return (
                f"Room-level cleaning unavailable for {entity_id} "
                f"(no room map in attributes) and fallback failed: {e}"
            )

    matched_ids, unmatched = _match_rooms(rooms, room_map)

    if not matched_ids:
        available = ", ".join(
            f"'{name}'" for name in sorted(room_map.values())
        )
        return (
            f"No rooms matched {rooms!r}. "
            f"Available rooms: {available}. "
            "Please check spelling and try again."
        )

    # 4. Call roborock segment-cleaning service
    try:
        await ha_request(
            "POST",
            "/services/roborock/vacuum_clean_segment",
            json_data={
                "entity_id": entity_id,
                "segments": matched_ids,
            },
        )
        fn = attributes.get(
            "friendly_name", friendly_name(entity_id)
        )
        rooms_cleaned = ", ".join(
            f"'{room_map[str(sid)]}'" for sid in matched_ids
        )
        msg = f"Cleaning {rooms_cleaned} with {fn}."
        if unmatched:
            msg += (
                f" Note: {unmatched!r} did not match any known room."
            )
        return msg

    except Exception as robo_err:
        # 5. Fallback to generic start if roborock service unavailable
        logger.warning(
            "roborock.vacuum_clean_segment failed (%s) — "
            "falling back to vacuum.start for %s",
            robo_err,
            entity_id,
        )
        try:
            fallback_result = await control_vacuum(
                entity_id=entity_id, action="start"
            )
            return (
                f"Room-level cleaning unavailable "
                f"(roborock service error: {robo_err}). "
                f"Started full clean instead. {fallback_result}"
            )
        except Exception as fallback_err:
            return (
                f"Room-level cleaning failed ({robo_err}) "
                f"and fallback also failed ({fallback_err})."
            )
