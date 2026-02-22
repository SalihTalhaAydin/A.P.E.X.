"""
Smart Home Tools - Control Home Assistant devices.
Used by Apex. HA REST API, auto-authenticated via SUPERVISOR_TOKEN when
running as add-on.

Design: Each major HA domain gets its own tool with FLAT top-level
parameters. LLMs reliably fill flat params but consistently skip nested
optional objects. The generic call_service is kept as a fallback for
domains without a dedicated tool.

DEPRECATED: These tools are thin wrappers that delegate to the generic
tools in tools.generic (do, query, discover). Use the generic tools
directly for new code.
"""

from __future__ import annotations

import asyncio
import logging

from tools.base import tool
from tools.generic import discover, do, query
from tools.ha_helpers import (
    call_ha_service,
    friendly_name,
    ha_request,
    read_state,
)

logger = logging.getLogger(__name__)

# --------------------------------------------------
# Domain-specific verify helpers (kept for cycle_light_timed)
# --------------------------------------------------


async def _verify_light(entity_id: str) -> str:
    """Read back a light's state and return a human-readable summary."""
    try:
        state = await read_state(entity_id)
        fn = state.get("attributes", {}).get(
            "friendly_name", friendly_name(entity_id)
        )
        on_off = state.get("state", "unknown")
        attrs = state.get("attributes", {})
        parts = [f"{fn}: {on_off}"]
        if (
            "brightness" in attrs
            and attrs["brightness"] is not None
        ):
            parts.append(
                f"{round(attrs['brightness'] / 255 * 100)}%"
                " brightness"
            )
        if (
            "color_temp_kelvin" in attrs
            and attrs["color_temp_kelvin"] is not None
        ):
            parts.append(f"{attrs['color_temp_kelvin']}K")
        if (
            "rgb_color" in attrs
            and attrs["rgb_color"] is not None
        ):
            parts.append(f"RGB{tuple(attrs['rgb_color'])}")
        return ", ".join(parts)
    except Exception:
        return (
            f"{friendly_name(entity_id)}: "
            "(state unconfirmed)"
        )


# --------------------------------------------------
# Discovery tools
# --------------------------------------------------

_MAX_ENTITIES_NO_DOMAIN = 50
_MAX_ENTITIES_WITH_DOMAIN = 200


@tool(
    description=(
        "List smart home entities (devices). Optionally "
        "filter by domain like 'light', 'switch', "
        "'climate', 'media_player', 'cover', 'lock', "
        "'fan', 'vacuum', 'notify', 'todo'. "
        "Returns entity IDs and their current states."
    ),
    parameters={
        "type": "object",
        "properties": {
            "domain": {
                "type": "string",
                "description": (
                    "Optional domain: light, switch, "
                    "climate, media_player, cover, lock, "
                    "fan, vacuum, notify, todo, sensor, "
                    "automation, script, scene, etc."
                ),
            },
        },
        "required": [],
    },
    hidden=True,
)
async def list_entities(domain: str = "") -> str:
    """List all entities, optionally filtered by domain."""
    logger.warning(
        "DEPRECATED: %s() called — use %s() instead",
        "list_entities", "discover",
    )
    try:
        return await discover("entities", domain)
    except Exception as e:
        return f"Error listing entities: {e}"


@tool(
    description=(
        "Get the current state and attributes of a "
        "specific smart home device. Check if a light "
        "is on, thermostat setting, etc."
    ),
    parameters={
        "type": "object",
        "properties": {
            "entity_id": {
                "type": "string",
                "description": (
                    "The entity ID, e.g. "
                    "'light.living_room_ceiling', "
                    "'climate.living_room_thermostat'"
                ),
            },
        },
        "required": ["entity_id"],
    },
    hidden=True,
)
async def get_entity_state(entity_id: str) -> str:
    """Get detailed state of a specific entity."""
    logger.warning(
        "DEPRECATED: %s() called — use %s() instead",
        "get_entity_state", "query",
    )
    try:
        return await query(entity_id)
    except Exception as e:
        return f"Error getting state: {e}"


@tool(
    description=(
        "List all rooms/areas configured in "
        "Home Assistant."
    ),
    parameters={
        "type": "object",
        "properties": {},
        "required": [],
    },
    hidden=True,
)
async def get_areas() -> str:
    """List all areas (rooms) in Home Assistant."""
    logger.warning(
        "DEPRECATED: %s() called — use %s() instead",
        "get_areas", "discover",
    )
    try:
        return await discover("areas")
    except Exception as e:
        return f"Error listing areas: {e}"


@tool(
    description=(
        "Query sensors by type or area. Returns matching "
        "sensor readings. Use for 'what's the temperature "
        "in the kitchen?', 'how much battery does X "
        "have?', 'what's the humidity?'."
    ),
    parameters={
        "type": "object",
        "properties": {
            "sensor_type": {
                "type": "string",
                "description": (
                    "Filter by type: 'temperature', "
                    "'humidity', 'battery', 'power', "
                    "'energy', 'motion', 'illuminance'. "
                    "Optional."
                ),
            },
            "area": {
                "type": "string",
                "description": (
                    "Filter by area/room keyword, e.g. "
                    "'kitchen', 'bedroom', 'basement'. "
                    "Optional."
                ),
            },
            "entity_id": {
                "type": "string",
                "description": (
                    "Specific sensor entity ID if known. "
                    "Overrides other filters."
                ),
            },
        },
        "required": [],
    },
    hidden=True,
)
async def query_sensors(
    sensor_type: str = "",
    area: str = "",
    entity_id: str = "",
) -> str:
    """Query sensors by type or area."""
    logger.warning(
        "DEPRECATED: %s() called — use %s() instead",
        "query_sensors", "query/discover",
    )
    try:
        if entity_id:
            return await query(entity_id)
        # Use the best available filter
        filter_str = sensor_type or area or ""
        return await discover("entities", filter_str)
    except Exception as e:
        return f"Error querying sensors: {e}"


# --------------------------------------------------
# Domain-specific control tools (flat params)
# --------------------------------------------------


@tool(
    description=(
        "Control a light: on/off, brightness, color, "
        "color temp. To set brightness, you MUST provide "
        "brightness_pct (0-100). "
        "Example: 50% -> action='on', brightness_pct=50."
    ),
    parameters={
        "type": "object",
        "properties": {
            "entity_id": {
                "type": "string",
                "description": (
                    "Light entity ID, e.g. "
                    "'light.living_room_ceiling'"
                ),
            },
            "action": {
                "type": "string",
                "enum": ["on", "off", "toggle"],
                "description": (
                    "Action: 'on', 'off', or 'toggle'."
                ),
            },
            "brightness_pct": {
                "type": "integer",
                "description": (
                    "Brightness 0-100. Required when "
                    "setting brightness."
                ),
            },
            "color": {
                "type": "string",
                "description": (
                    "Color name or hex '#FF0000'. "
                    "Optional."
                ),
            },
            "color_temp_kelvin": {
                "type": "integer",
                "description": (
                    "Color temp in Kelvin "
                    "(2000=warm, 6500=cool). Optional."
                ),
            },
            "transition": {
                "type": "number",
                "description": (
                    "Transition time in seconds. "
                    "Optional."
                ),
            },
        },
        "required": ["entity_id", "action"],
    },
    hidden=True,
)
async def control_light(
    entity_id: str,
    action: str,
    brightness_pct: int | None = None,
    color: str | None = None,
    color_temp_kelvin: int | None = None,
    transition: float | None = None,
) -> str:
    """Control a light with explicit flat parameters."""
    logger.warning(
        "DEPRECATED: %s() called — use %s() instead",
        "control_light", "do",
    )
    try:
        svc_map = {
            "on": "turn_on",
            "off": "turn_off",
            "toggle": "toggle",
        }
        service = svc_map[action]
        data: dict = {}

        if brightness_pct is not None:
            data["brightness_pct"] = max(
                0, min(100, brightness_pct)
            )
        if color is not None:
            if (
                color.startswith("#")
                and len(color) == 7
            ):
                try:
                    r, g, b = (
                        int(color[1:3], 16),
                        int(color[3:5], 16),
                        int(color[5:7], 16),
                    )
                    data["rgb_color"] = [r, g, b]
                except ValueError:
                    data["color_name"] = color
            else:
                data["color_name"] = color
        if color_temp_kelvin is not None:
            data["color_temp_kelvin"] = (
                color_temp_kelvin
            )
        if transition is not None:
            data["transition"] = transition

        return await do(
            "light",
            service,
            {"entity_id": entity_id},
            data or None,
        )

    except Exception as e:
        return f"Error controlling light: {e}"


_CYCLE_LIGHT_TIMES_MIN = 1
_CYCLE_LIGHT_TIMES_MAX = 10
_CYCLE_LIGHT_SECONDS_MIN = 1.0
_CYCLE_LIGHT_SECONDS_MAX = 60.0


@tool(
    description=(
        "Cycle a light off and on a given number of "
        "times with a delay between each cycle. "
        "Use for 'blink the light 3 times with 10s "
        "intervals'. Runs server-side in one call."
    ),
    parameters={
        "type": "object",
        "properties": {
            "entity_id": {
                "type": "string",
                "description": (
                    "The light entity ID. Use "
                    "list_entities(domain='light') "
                    "if needed."
                ),
            },
            "times": {
                "type": "integer",
                "description": (
                    "Number of off/on cycles (1-10)."
                ),
            },
            "seconds_between": {
                "type": "number",
                "description": (
                    "Seconds between off and on (1-60)."
                ),
            },
        },
        "required": [
            "entity_id",
            "times",
            "seconds_between",
        ],
    },
)
async def cycle_light_timed(
    entity_id: str,
    times: int,
    seconds_between: float,
) -> str:
    """Turn a light off and on N times with S seconds between."""
    try:
        t = max(
            _CYCLE_LIGHT_TIMES_MIN,
            min(int(times), _CYCLE_LIGHT_TIMES_MAX),
        )
        sec = max(
            _CYCLE_LIGHT_SECONDS_MIN,
            min(
                float(seconds_between),
                _CYCLE_LIGHT_SECONDS_MAX,
            ),
        )
        for i in range(t):
            await call_ha_service(
                "light", "turn_off", entity_id, None
            )
            await asyncio.sleep(sec)
            await call_ha_service(
                "light", "turn_on", entity_id, None
            )
            if i < t - 1:
                await asyncio.sleep(sec)
        status = await _verify_light(entity_id)
        return (
            f"Done. Cycled {t} times with "
            f"{sec}s between. {status}"
        )
    except Exception as e:
        return f"Error cycling light: {e}"


@tool(
    description=(
        "Control a thermostat/climate: set temperature, "
        "HVAC mode, preset, or fan mode. Provide at "
        "least one setting to change."
    ),
    parameters={
        "type": "object",
        "properties": {
            "entity_id": {
                "type": "string",
                "description": (
                    "Climate entity ID, e.g. "
                    "'climate.living_room_thermostat'"
                ),
            },
            "temperature": {
                "type": "number",
                "description": (
                    "Target temp (e.g. 72°F or 22°C)."
                ),
            },
            "hvac_mode": {
                "type": "string",
                "enum": [
                    "heat",
                    "cool",
                    "auto",
                    "off",
                    "heat_cool",
                    "fan_only",
                    "dry",
                ],
                "description": "HVAC mode to set.",
            },
            "preset_mode": {
                "type": "string",
                "description": (
                    "Preset: 'home', 'away', 'eco', "
                    "'sleep', 'comfort'."
                ),
            },
            "fan_mode": {
                "type": "string",
                "description": (
                    "Fan: 'auto', 'low', 'medium', "
                    "'high'."
                ),
            },
        },
        "required": ["entity_id"],
    },
    hidden=True,
)
async def control_climate(
    entity_id: str,
    temperature: float | None = None,
    hvac_mode: str | None = None,
    preset_mode: str | None = None,
    fan_mode: str | None = None,
) -> str:
    """Control a climate / thermostat device."""
    logger.warning(
        "DEPRECATED: %s() called — use %s() instead",
        "control_climate", "do",
    )
    try:
        actions_taken = []
        last_result = ""

        if hvac_mode is not None:
            last_result = await do(
                "climate",
                "set_hvac_mode",
                {"entity_id": entity_id},
                {"hvac_mode": hvac_mode},
            )
            actions_taken.append(f"mode={hvac_mode}")

        if temperature is not None:
            last_result = await do(
                "climate",
                "set_temperature",
                {"entity_id": entity_id},
                {"temperature": temperature},
            )
            actions_taken.append(f"temp={temperature}")

        if preset_mode is not None:
            last_result = await do(
                "climate",
                "set_preset_mode",
                {"entity_id": entity_id},
                {"preset_mode": preset_mode},
            )
            actions_taken.append(
                f"preset={preset_mode}"
            )

        if fan_mode is not None:
            last_result = await do(
                "climate",
                "set_fan_mode",
                {"entity_id": entity_id},
                {"fan_mode": fan_mode},
            )
            actions_taken.append(f"fan={fan_mode}")

        if not actions_taken:
            return (
                "No climate settings provided. "
                "Specify temperature, hvac_mode, "
                "preset_mode, or fan_mode."
            )

        return (
            f"Done ({', '.join(actions_taken)}). "
            f"{last_result}"
        )

    except Exception as e:
        return f"Error controlling climate: {e}"


@tool(
    description=(
        "Control a media player: turn on/off, play, "
        "pause, stop, volume, mute, skip, source. "
        "Set volume with volume_level 0-100."
    ),
    parameters={
        "type": "object",
        "properties": {
            "entity_id": {
                "type": "string",
                "description": (
                    "Media player entity ID, e.g. "
                    "'media_player.living_room_tv'"
                ),
            },
            "action": {
                "type": "string",
                "enum": [
                    "turn_on",
                    "turn_off",
                    "play",
                    "pause",
                    "stop",
                    "next",
                    "previous",
                    "volume_up",
                    "volume_down",
                    "mute",
                    "unmute",
                ],
                "description": (
                    "Action: turn_on/turn_off, or "
                    "playback/volume control."
                ),
            },
            "volume_level": {
                "type": "integer",
                "description": (
                    "Volume 0-100. Sets exact level."
                ),
            },
            "source": {
                "type": "string",
                "description": (
                    "Input source, e.g. 'Spotify', "
                    "'HDMI 1'. Optional."
                ),
            },
        },
        "required": ["entity_id", "action"],
    },
    hidden=True,
)
async def control_media(
    entity_id: str,
    action: str,
    volume_level: int | None = None,
    source: str | None = None,
) -> str:
    """Control a media player with flat parameters."""
    logger.warning(
        "DEPRECATED: %s() called — use %s() instead",
        "control_media", "do",
    )
    try:
        action_map = {
            "turn_on": "turn_on",
            "turn_off": "turn_off",
            "play": "media_play",
            "pause": "media_pause",
            "stop": "media_stop",
            "next": "media_next_track",
            "previous": "media_previous_track",
            "volume_up": "volume_up",
            "volume_down": "volume_down",
            "mute": "volume_mute",
            "unmute": "volume_mute",
        }

        service = action_map.get(action)
        if not service:
            return f"Unknown media action: {action}"

        # Build data for mute/unmute
        data = None
        if action == "mute":
            data = {"is_volume_muted": True}
        elif action == "unmute":
            data = {"is_volume_muted": False}

        last_result = await do(
            "media_player",
            service,
            {"entity_id": entity_id},
            data,
        )

        if volume_level is not None:
            level = (
                max(0, min(100, volume_level)) / 100.0
            )
            last_result = await do(
                "media_player",
                "volume_set",
                {"entity_id": entity_id},
                {"volume_level": level},
            )

        if source is not None:
            last_result = await do(
                "media_player",
                "select_source",
                {"entity_id": entity_id},
                {"source": source},
            )

        return last_result

    except Exception as e:
        return f"Error controlling media player: {e}"


@tool(
    description=(
        "Control a cover (blinds, shades, garage): "
        "open, close, stop, or set position."
    ),
    parameters={
        "type": "object",
        "properties": {
            "entity_id": {
                "type": "string",
                "description": (
                    "Cover entity ID, e.g. "
                    "'cover.living_room_blinds'."
                ),
            },
            "action": {
                "type": "string",
                "enum": ["open", "close", "stop"],
                "description": (
                    "Action: 'open', 'close', or 'stop'."
                ),
            },
            "position": {
                "type": "integer",
                "description": (
                    "Position 0-100 "
                    "(0=closed, 100=open). Optional."
                ),
            },
            "tilt_position": {
                "type": "integer",
                "description": (
                    "Tilt position 0-100. Optional."
                ),
            },
        },
        "required": ["entity_id", "action"],
    },
    hidden=True,
)
async def control_cover(
    entity_id: str,
    action: str,
    position: int | None = None,
    tilt_position: int | None = None,
) -> str:
    """Control a cover / blind / garage door."""
    logger.warning(
        "DEPRECATED: %s() called — use %s() instead",
        "control_cover", "do",
    )
    try:
        if position is not None:
            pos = max(0, min(100, position))
            result = await do(
                "cover",
                "set_cover_position",
                {"entity_id": entity_id},
                {"position": pos},
            )
        elif action:
            service_map = {
                "open": "open_cover",
                "close": "close_cover",
                "stop": "stop_cover",
            }
            service = service_map.get(action)
            if not service:
                return f"Unknown cover action: {action}"
            result = await do(
                "cover",
                service,
                {"entity_id": entity_id},
            )
        else:
            return (
                "No action taken: provide 'position' (0-100) "
                "or a valid 'action' (open/close/stop)."
            )

        if tilt_position is not None:
            tilt = max(0, min(100, tilt_position))
            result = await do(
                "cover",
                "set_cover_tilt_position",
                {"entity_id": entity_id},
                {"tilt_position": tilt},
            )

        return result

    except Exception as e:
        return f"Error controlling cover: {e}"


@tool(
    description=(
        "Control a fan: on/off, set speed percentage, "
        "or direction."
    ),
    parameters={
        "type": "object",
        "properties": {
            "entity_id": {
                "type": "string",
                "description": (
                    "Fan entity ID "
                    "(e.g. fan.bedroom_ceiling)"
                ),
            },
            "action": {
                "type": "string",
                "enum": ["on", "off", "toggle"],
                "description": (
                    "Action: 'on', 'off', or 'toggle'."
                ),
            },
            "percentage": {
                "type": "integer",
                "description": (
                    "Fan speed 0-100. Optional."
                ),
            },
            "direction": {
                "type": "string",
                "enum": ["forward", "reverse"],
                "description": (
                    "Fan direction. Optional."
                ),
            },
        },
        "required": ["entity_id", "action"],
    },
    hidden=True,
)
async def control_fan(
    entity_id: str,
    action: str,
    percentage: int | None = None,
    direction: str | None = None,
) -> str:
    """Control a fan with flat parameters."""
    logger.warning(
        "DEPRECATED: %s() called — use %s() instead",
        "control_fan", "do",
    )
    try:
        svc_map = {
            "on": "turn_on",
            "off": "turn_off",
            "toggle": "toggle",
        }
        service = svc_map.get(action)
        if service is None:
            return (
                f"Unknown fan action '{action}'. "
                "Use 'on', 'off', or 'toggle'."
            )
        data: dict = {}

        if (
            action in ("on", "toggle")
            and percentage is not None
        ):
            data["percentage"] = max(
                0, min(100, percentage)
            )

        result = await do(
            "fan",
            service,
            {"entity_id": entity_id},
            data or None,
        )

        if direction is not None:
            result = await do(
                "fan",
                "set_direction",
                {"entity_id": entity_id},
                {"direction": direction},
            )

        return result

    except Exception as e:
        return f"Error controlling fan: {e}"


# --------------------------------------------------
# Area-based control
# --------------------------------------------------


@tool(
    description=(
        "Control all devices of a given domain in an "
        "area/room by name. Use for 'turn off all lights "
        "in the basement', 'dim kitchen lights to 50%', "
        "'turn on bedroom lights'. Resolves the area name "
        "to an area_id automatically."
    ),
    parameters={
        "type": "object",
        "properties": {
            "area_name": {
                "type": "string",
                "description": (
                    "Human area/room name, e.g. "
                    "'basement', 'kitchen', 'bedroom'. "
                    "Case-insensitive, partial match OK."
                ),
            },
            "domain": {
                "type": "string",
                "description": (
                    "HA domain to control: 'light', "
                    "'switch', 'fan'. Default: 'light'."
                ),
            },
            "action": {
                "type": "string",
                "enum": ["on", "off", "toggle"],
                "description": (
                    "Action: 'on', 'off', or 'toggle'."
                ),
            },
            "brightness_pct": {
                "type": "integer",
                "description": (
                    "Brightness 0-100. Only for "
                    "action='on' with domain='light'. "
                    "Optional."
                ),
            },
            "color_temp_kelvin": {
                "type": "integer",
                "description": (
                    "Color temperature in Kelvin "
                    "(2000=warm, 6500=cool). Only for "
                    "action='on' with domain='light'. "
                    "Optional."
                ),
            },
        },
        "required": ["area_name", "action"],
    },
)
async def control_area(
    area_name: str,
    action: str,
    domain: str = "light",
    brightness_pct: int | None = None,
    color_temp_kelvin: int | None = None,
) -> str:
    """Control all devices of a domain in a named area."""
    logger.warning(
        "DEPRECATED: %s() called — use %s() instead",
        "control_area", "do",
    )
    try:
        # Step 1: Fetch all areas via template
        raw = await ha_request(
            "POST",
            "/template",
            json_data={
                "template": (
                    "{% for area in areas() %}"
                    "{{ area }}|{{ area_name(area) }}\n"
                    "{% endfor %}"
                )
            },
        )
        # raw may come back as {} (non-JSON) or a string
        if isinstance(raw, dict):
            return (
                "Could not retrieve area list from "
                "Home Assistant."
            )
        area_lines = [
            line.strip()
            for line in str(raw).splitlines()
            if line.strip() and "|" in line
        ]

        # Step 2: Find matching area_id (case-insensitive,
        #         prefer exact match, fall back to substring)
        search = area_name.lower()
        matched_id: str | None = None
        substring_match: str | None = None
        known_names: list[str] = []
        for line in area_lines:
            area_id, _, human = line.partition("|")
            area_id = area_id.strip()
            human = human.strip()
            known_names.append(human)
            human_lower = human.lower()
            if search == human_lower:
                matched_id = area_id
                break  # exact match wins
            if (
                substring_match is None
                and search in human_lower
            ):
                substring_match = area_id
        if matched_id is None:
            matched_id = substring_match

        if matched_id is None:
            names_list = ", ".join(known_names) or "none"
            return (
                f"No area matching '{area_name}' found. "
                f"Known areas: {names_list}."
            )

        # Step 3: Build service + data
        svc_map = {
            "on": "turn_on",
            "off": "turn_off",
            "toggle": "toggle",
        }
        service = svc_map.get(action)
        if service is None:
            return (
                f"Unknown action '{action}'. "
                "Use 'on', 'off', or 'toggle'."
            )

        data: dict = {}
        if action in ("on", "toggle"):
            if brightness_pct is not None:
                data["brightness_pct"] = max(
                    0, min(100, brightness_pct)
                )
            if color_temp_kelvin is not None:
                data["color_temp_kelvin"] = (
                    color_temp_kelvin
                )

        # Step 4: Call the service via do()
        result = await do(
            domain,
            service,
            {"area_id": matched_id},
            data or None,
        )

        # Check for errors from do()
        if isinstance(result, str) and (
            result.startswith("Error") or result.startswith("HA error")
        ):
            return result

        # Step 5: Return confirmation
        extras = []
        if brightness_pct is not None:
            extras.append(f"{brightness_pct}% brightness")
        if color_temp_kelvin is not None:
            extras.append(f"{color_temp_kelvin}K")
        extra_str = (
            f" ({', '.join(extras)})" if extras else ""
        )
        human_name = next(
            (
                line.partition("|")[2].strip()
                for line in area_lines
                if line.partition("|")[0].strip()
                == matched_id
            ),
            area_name,
        )
        return (
            f"Done — {domain} {action} in "
            f"{human_name}{extra_str}."
        )

    except Exception as e:
        return f"Error controlling area: {e}"


# --------------------------------------------------
# Generic fallback (no dedicated tool)
# --------------------------------------------------


@tool(
    description=(
        "Generic HA service call. Only for domains "
        "without a dedicated tool: siren, etc. "
        "Prefer control_light, control_climate, "
        "control_media, control_cover, control_fan, "
        "control_vacuum, control_lock, control_switch, "
        "control_alarm, manage_todo, "
        "send_notification when applicable."
    ),
    parameters={
        "type": "object",
        "properties": {
            "domain": {
                "type": "string",
                "description": (
                    "HA domain: switch, lock, siren, "
                    "input_boolean, etc."
                ),
            },
            "service": {
                "type": "string",
                "description": (
                    "Service: turn_on, turn_off, "
                    "toggle, lock, unlock, etc."
                ),
            },
            "entity_id": {
                "type": "string",
                "description": (
                    "Entity ID, e.g. "
                    "'switch.office_desk_lamp'"
                ),
            },
            "service_data": {
                "type": "object",
                "description": (
                    "Extra key-value data for the "
                    "service. Optional."
                ),
            },
        },
        "required": ["domain", "service", "entity_id"],
    },
    hidden=True,
)
async def call_service(
    domain: str,
    service: str,
    entity_id: str,
    service_data: dict | None = None,
) -> str:
    """Generic HA service call; fallback."""
    logger.warning(
        "DEPRECATED: %s() called — use %s() instead",
        "call_service", "do",
    )
    try:
        return await do(
            domain,
            service,
            {"entity_id": entity_id},
            service_data,
        )
    except Exception as e:
        return f"Error calling service: {e}"
