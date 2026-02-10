"""
Smart Home Tools - Control Home Assistant devices.
Used by Apex. HA REST API, auto-authenticated via SUPERVISOR_TOKEN when running as add-on.

Design: Each major HA domain gets its own tool with FLAT top-level parameters.
LLMs reliably fill flat params but consistently skip nested optional objects.
The generic call_service is kept as a fallback for domains without a dedicated tool.
"""

import httpx
from tools.base import tool
from brain.config import settings


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

async def _ha_request(method: str, path: str, json_data: dict | None = None) -> dict | list | str:
    """Make an authenticated request to the HA REST API."""
    url = f"{settings.ha_api_url}{path}"
    headers = settings.ha_headers
    token = headers.get("Authorization", "")
    print(f"  [HA API] {method} {url} (token: {'set' if len(token) > 10 else 'MISSING'})")
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.request(
            method=method,
            url=url,
            headers=headers,
            json=json_data,
        )
        if response.status_code != 200:
            print(f"  [HA API] ERROR: {response.status_code} {response.text[:300]}")
        response.raise_for_status()
        return response.json()


def _friendly_name(entity_id: str) -> str:
    """Derive a human-friendly name from an entity_id."""
    return entity_id.split(".")[-1].replace("_", " ").title()


async def _call_ha_service(domain: str, service: str, entity_id: str, data: dict | None = None) -> None:
    """Call an HA service and log the full payload."""
    payload = {"entity_id": entity_id}
    if data:
        payload.update(data)
    print(f"  [HA SVC] {domain}.{service} -> {entity_id} data={data}")
    await _ha_request("POST", f"/services/{domain}/{service}", json_data=payload)


async def _read_state(entity_id: str) -> dict:
    """Read the current state of an entity. Returns the full state dict."""
    return await _ha_request("GET", f"/states/{entity_id}")


async def _verify_light(entity_id: str) -> str:
    """Read back a light's state and return a human-readable summary."""
    try:
        state = await _read_state(entity_id)
        friendly = state.get("attributes", {}).get("friendly_name", _friendly_name(entity_id))
        on_off = state.get("state", "unknown")
        attrs = state.get("attributes", {})
        parts = [f"{friendly}: {on_off}"]
        if "brightness" in attrs and attrs["brightness"] is not None:
            parts.append(f"{round(attrs['brightness'] / 255 * 100)}% brightness")
        if "color_temp_kelvin" in attrs and attrs["color_temp_kelvin"] is not None:
            parts.append(f"{attrs['color_temp_kelvin']}K")
        if "rgb_color" in attrs and attrs["rgb_color"] is not None:
            parts.append(f"RGB{tuple(attrs['rgb_color'])}")
        return ", ".join(parts)
    except Exception:
        return f"{_friendly_name(entity_id)}: (state unconfirmed)"


async def _verify_climate(entity_id: str) -> str:
    """Read back a climate entity's state."""
    try:
        state = await _read_state(entity_id)
        friendly = state.get("attributes", {}).get("friendly_name", _friendly_name(entity_id))
        mode = state.get("state", "unknown")
        attrs = state.get("attributes", {})
        parts = [f"{friendly}: {mode}"]
        if "temperature" in attrs and attrs["temperature"] is not None:
            parts.append(f"target {attrs['temperature']}°")
        if "current_temperature" in attrs and attrs["current_temperature"] is not None:
            parts.append(f"current {attrs['current_temperature']}°")
        if "preset_mode" in attrs and attrs["preset_mode"] is not None:
            parts.append(f"preset: {attrs['preset_mode']}")
        return ", ".join(parts)
    except Exception:
        return f"{_friendly_name(entity_id)}: (state unconfirmed)"


async def _verify_media(entity_id: str) -> str:
    """Read back a media_player entity's state."""
    try:
        state = await _read_state(entity_id)
        friendly = state.get("attributes", {}).get("friendly_name", _friendly_name(entity_id))
        player_state = state.get("state", "unknown")
        attrs = state.get("attributes", {})
        parts = [f"{friendly}: {player_state}"]
        if "volume_level" in attrs and attrs["volume_level"] is not None:
            parts.append(f"volume {round(attrs['volume_level'] * 100)}%")
        if "media_title" in attrs and attrs["media_title"] is not None:
            parts.append(f"playing: {attrs['media_title']}")
        if "source" in attrs and attrs["source"] is not None:
            parts.append(f"source: {attrs['source']}")
        return ", ".join(parts)
    except Exception:
        return f"{_friendly_name(entity_id)}: (state unconfirmed)"


async def _verify_generic(entity_id: str) -> str:
    """Read back any entity's basic state."""
    try:
        state = await _read_state(entity_id)
        friendly = state.get("attributes", {}).get("friendly_name", _friendly_name(entity_id))
        return f"{friendly}: {state.get('state', 'unknown')}"
    except Exception:
        return f"{_friendly_name(entity_id)}: (state unconfirmed)"


# ---------------------------------------------------------------------------
# Discovery tools (unchanged)
# ---------------------------------------------------------------------------

@tool(
    description=(
        "List smart home entities (devices). Optionally filter by domain like "
        "'light', 'switch', 'climate', 'media_player', 'cover', 'lock', 'fan'. "
        "Returns entity IDs and their current states."
    ),
    parameters={
        "type": "object",
        "properties": {
            "domain": {
                "type": "string",
                "description": (
                    "Optional domain to filter by: light, switch, climate, "
                    "media_player, cover, lock, fan, sensor, binary_sensor, etc."
                ),
            },
        },
        "required": [],
    },
)
async def list_entities(domain: str = "") -> str:
    """List all entities, optionally filtered by domain."""
    try:
        states = await _ha_request("GET", "/states")
        if domain:
            states = [s for s in states if s["entity_id"].startswith(f"{domain}.")]

        if not states:
            return f"No entities found{f' for domain {domain}' if domain else ''}."

        lines = []
        for s in states[:50]:  # Cap at 50 to avoid huge responses
            entity_id = s["entity_id"]
            state = s["state"]
            friendly = s.get("attributes", {}).get("friendly_name", entity_id)
            lines.append(f"- {friendly} ({entity_id}): {state}")

        return "\n".join(lines)
    except Exception as e:
        return f"Error listing entities: {e}"


@tool(
    description=(
        "Get the current state and attributes of a specific smart home device. "
        "Use this to check if a light is on, what temperature the thermostat is set to, etc."
    ),
    parameters={
        "type": "object",
        "properties": {
            "entity_id": {
                "type": "string",
                "description": "The entity ID, e.g. 'light.living_room', 'climate.thermostat'",
            },
        },
        "required": ["entity_id"],
    },
)
async def get_entity_state(entity_id: str) -> str:
    """Get detailed state of a specific entity."""
    try:
        state = await _ha_request("GET", f"/states/{entity_id}")
        friendly = state.get("attributes", {}).get("friendly_name", entity_id)
        current = state.get("state", "unknown")
        attrs = state.get("attributes", {})

        info = [f"{friendly} ({entity_id}): {current}"]

        # Add relevant attributes based on domain
        if "brightness" in attrs:
            info.append(f"  Brightness: {round(attrs['brightness'] / 255 * 100)}%")
        if "color_temp_kelvin" in attrs:
            info.append(f"  Color temp: {attrs['color_temp_kelvin']}K")
        elif "color_temp" in attrs:
            info.append(f"  Color temp: {attrs['color_temp']} mireds")
        if "rgb_color" in attrs:
            info.append(f"  RGB: {attrs['rgb_color']}")
        if "temperature" in attrs:
            info.append(f"  Temperature: {attrs['temperature']}°")
        if "current_temperature" in attrs:
            info.append(f"  Current temp: {attrs['current_temperature']}°")
        if "hvac_action" in attrs:
            info.append(f"  HVAC action: {attrs['hvac_action']}")
        if "media_title" in attrs:
            info.append(f"  Playing: {attrs['media_title']}")
        if "volume_level" in attrs:
            info.append(f"  Volume: {round(attrs['volume_level'] * 100)}%")
        if "current_position" in attrs:
            info.append(f"  Position: {attrs['current_position']}%")

        return "\n".join(info)
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            return f"Entity '{entity_id}' not found."
        return f"Error: {e}"
    except Exception as e:
        return f"Error getting state: {e}"


@tool(
    description="List all rooms/areas configured in Home Assistant.",
    parameters={"type": "object", "properties": {}, "required": []},
)
async def get_areas() -> str:
    """List all areas (rooms) in Home Assistant."""
    try:
        # HA REST API doesn't have a direct area endpoint, use template
        result = await _ha_request(
            "POST",
            "/template",
            json_data={
                "template": "{% for area in areas() %}{{ area_name(area) }} ({{ area }})\n{% endfor %}"
            },
        )
        if isinstance(result, str) and result.strip():
            return f"Areas in your home:\n{result.strip()}"
        return "No areas configured yet."
    except Exception as e:
        return f"Error listing areas: {e}"


# ---------------------------------------------------------------------------
# Domain-specific control tools (flat parameters -- the AI can't miss these)
# ---------------------------------------------------------------------------

@tool(
    description=(
        "Control a light: turn on/off, set brightness, set color, set color temperature. "
        "To set brightness, you MUST provide brightness_pct (0-100). "
        "Example: to set a light to 50%, use action='on' and brightness_pct=50."
    ),
    parameters={
        "type": "object",
        "properties": {
            "entity_id": {
                "type": "string",
                "description": "The light entity ID, e.g. 'light.living_room'",
            },
            "action": {
                "type": "string",
                "enum": ["on", "off", "toggle"],
                "description": "Action: 'on' (turn on / set brightness/color), 'off', or 'toggle'",
            },
            "brightness_pct": {
                "type": "integer",
                "description": "Brightness percentage 0-100. Required when setting brightness. 50 = 50% bright.",
            },
            "color": {
                "type": "string",
                "description": "Color name (e.g. 'red', 'blue', 'warm_white') or hex (e.g. '#FF0000'). Optional.",
            },
            "color_temp_kelvin": {
                "type": "integer",
                "description": "Color temperature in Kelvin (2000=warm, 4000=neutral, 6500=cool daylight). Optional.",
            },
            "transition": {
                "type": "number",
                "description": "Transition time in seconds for the change. Optional.",
            },
        },
        "required": ["entity_id", "action"],
    },
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
    try:
        service = {"on": "turn_on", "off": "turn_off", "toggle": "toggle"}[action]
        data: dict = {}

        if action in ("on", "toggle"):
            if brightness_pct is not None:
                data["brightness_pct"] = max(0, min(100, brightness_pct))
            if color is not None:
                if color.startswith("#") and len(color) == 7:
                    r, g, b = int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)
                    data["rgb_color"] = [r, g, b]
                else:
                    data["color_name"] = color
            if color_temp_kelvin is not None:
                data["color_temp_kelvin"] = color_temp_kelvin
            if transition is not None:
                data["transition"] = transition

        await _call_ha_service("light", service, entity_id, data or None)

        # Verify actual state
        status = await _verify_light(entity_id)
        return f"Done. {status}"

    except Exception as e:
        return f"Error controlling light: {e}"


@tool(
    description=(
        "Control a thermostat / climate device: set temperature, change HVAC mode, "
        "set preset, or change fan mode. Provide at least one setting to change."
    ),
    parameters={
        "type": "object",
        "properties": {
            "entity_id": {
                "type": "string",
                "description": "The climate entity ID, e.g. 'climate.thermostat'",
            },
            "temperature": {
                "type": "number",
                "description": "Target temperature in the user's unit system (e.g. 72 for °F or 22 for °C).",
            },
            "hvac_mode": {
                "type": "string",
                "enum": ["heat", "cool", "auto", "off", "heat_cool", "fan_only", "dry"],
                "description": "HVAC mode to set.",
            },
            "preset_mode": {
                "type": "string",
                "description": "Preset mode: 'home', 'away', 'eco', 'sleep', 'comfort', etc.",
            },
            "fan_mode": {
                "type": "string",
                "description": "Fan mode: 'auto', 'low', 'medium', 'high', 'off'.",
            },
        },
        "required": ["entity_id"],
    },
)
async def control_climate(
    entity_id: str,
    temperature: float | None = None,
    hvac_mode: str | None = None,
    preset_mode: str | None = None,
    fan_mode: str | None = None,
) -> str:
    """Control a climate / thermostat device with flat parameters."""
    try:
        actions_taken = []

        if hvac_mode is not None:
            await _call_ha_service("climate", "set_hvac_mode", entity_id, {"hvac_mode": hvac_mode})
            actions_taken.append(f"mode={hvac_mode}")

        if temperature is not None:
            await _call_ha_service("climate", "set_temperature", entity_id, {"temperature": temperature})
            actions_taken.append(f"temp={temperature}°")

        if preset_mode is not None:
            await _call_ha_service("climate", "set_preset_mode", entity_id, {"preset_mode": preset_mode})
            actions_taken.append(f"preset={preset_mode}")

        if fan_mode is not None:
            await _call_ha_service("climate", "set_fan_mode", entity_id, {"fan_mode": fan_mode})
            actions_taken.append(f"fan={fan_mode}")

        if not actions_taken:
            return "No climate settings provided. Specify temperature, hvac_mode, preset_mode, or fan_mode."

        # Verify actual state
        status = await _verify_climate(entity_id)
        return f"Done ({', '.join(actions_taken)}). {status}"

    except Exception as e:
        return f"Error controlling climate: {e}"


@tool(
    description=(
        "Control a media player: play, pause, stop, set volume, mute, skip tracks, or select source. "
        "To set volume, provide volume_level as a percentage 0-100."
    ),
    parameters={
        "type": "object",
        "properties": {
            "entity_id": {
                "type": "string",
                "description": "The media_player entity ID, e.g. 'media_player.living_room_speaker'",
            },
            "action": {
                "type": "string",
                "enum": ["play", "pause", "stop", "next", "previous", "volume_up", "volume_down", "mute", "unmute"],
                "description": "Playback or volume action to perform.",
            },
            "volume_level": {
                "type": "integer",
                "description": "Volume percentage 0-100. Provide this to set an exact volume level.",
            },
            "source": {
                "type": "string",
                "description": "Input source to select, e.g. 'Spotify', 'HDMI 1', 'TV'. Optional.",
            },
        },
        "required": ["entity_id", "action"],
    },
)
async def control_media(
    entity_id: str,
    action: str,
    volume_level: int | None = None,
    source: str | None = None,
) -> str:
    """Control a media player with flat parameters."""
    try:
        # Map actions to HA services
        action_map = {
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

        # Handle mute/unmute data
        if action == "mute":
            await _call_ha_service("media_player", service, entity_id, {"is_volume_muted": True})
        elif action == "unmute":
            await _call_ha_service("media_player", service, entity_id, {"is_volume_muted": False})
        else:
            await _call_ha_service("media_player", service, entity_id)

        # Set exact volume if provided
        if volume_level is not None:
            level = max(0, min(100, volume_level)) / 100.0
            await _call_ha_service("media_player", "volume_set", entity_id, {"volume_level": level})

        # Select source if provided
        if source is not None:
            await _call_ha_service("media_player", "select_source", entity_id, {"source": source})

        # Verify actual state
        status = await _verify_media(entity_id)
        return f"Done. {status}"

    except Exception as e:
        return f"Error controlling media player: {e}"


@tool(
    description=(
        "Control a cover (blinds, shades, curtains, garage door): open, close, stop, "
        "or set to a specific position."
    ),
    parameters={
        "type": "object",
        "properties": {
            "entity_id": {
                "type": "string",
                "description": "The cover entity ID, e.g. 'cover.garage_door', 'cover.living_room_blinds'",
            },
            "action": {
                "type": "string",
                "enum": ["open", "close", "stop"],
                "description": "Action: 'open', 'close', or 'stop'.",
            },
            "position": {
                "type": "integer",
                "description": "Position percentage 0-100 (0=fully closed, 100=fully open). Optional.",
            },
            "tilt_position": {
                "type": "integer",
                "description": "Tilt position percentage 0-100. Optional.",
            },
        },
        "required": ["entity_id", "action"],
    },
)
async def control_cover(
    entity_id: str,
    action: str,
    position: int | None = None,
    tilt_position: int | None = None,
) -> str:
    """Control a cover / blind / garage door with flat parameters."""
    try:
        # If a specific position is requested, use set_cover_position instead
        if position is not None:
            pos = max(0, min(100, position))
            await _call_ha_service("cover", "set_cover_position", entity_id, {"position": pos})
        else:
            service_map = {"open": "open_cover", "close": "close_cover", "stop": "stop_cover"}
            service = service_map.get(action)
            if not service:
                return f"Unknown cover action: {action}"
            await _call_ha_service("cover", service, entity_id)

        if tilt_position is not None:
            tilt = max(0, min(100, tilt_position))
            await _call_ha_service("cover", "set_cover_tilt_position", entity_id, {"tilt_position": tilt})

        status = await _verify_generic(entity_id)
        return f"Done. {status}"

    except Exception as e:
        return f"Error controlling cover: {e}"


@tool(
    description=(
        "Control a fan: turn on/off, set speed percentage, or change direction."
    ),
    parameters={
        "type": "object",
        "properties": {
            "entity_id": {
                "type": "string",
                "description": "The fan entity ID, e.g. 'fan.bedroom'",
            },
            "action": {
                "type": "string",
                "enum": ["on", "off", "toggle"],
                "description": "Action: 'on', 'off', or 'toggle'.",
            },
            "percentage": {
                "type": "integer",
                "description": "Fan speed as a percentage 0-100. Optional.",
            },
            "direction": {
                "type": "string",
                "enum": ["forward", "reverse"],
                "description": "Fan direction. Optional.",
            },
        },
        "required": ["entity_id", "action"],
    },
)
async def control_fan(
    entity_id: str,
    action: str,
    percentage: int | None = None,
    direction: str | None = None,
) -> str:
    """Control a fan with flat parameters."""
    try:
        service = {"on": "turn_on", "off": "turn_off", "toggle": "toggle"}[action]
        data: dict = {}

        if action in ("on", "toggle") and percentage is not None:
            data["percentage"] = max(0, min(100, percentage))

        await _call_ha_service("fan", service, entity_id, data or None)

        if direction is not None:
            await _call_ha_service("fan", "set_direction", entity_id, {"direction": direction})

        status = await _verify_generic(entity_id)
        return f"Done. {status}"

    except Exception as e:
        return f"Error controlling fan: {e}"


# ---------------------------------------------------------------------------
# Generic fallback (for domains without a dedicated tool)
# ---------------------------------------------------------------------------

@tool(
    description=(
        "Generic Home Assistant service call. Use this ONLY for domains that don't have "
        "a dedicated tool: lock, switch, vacuum, scene, script, automation, input_boolean, etc. "
        "For lights use control_light, for climate use control_climate, "
        "for media use control_media, for covers use control_cover, for fans use control_fan."
    ),
    parameters={
        "type": "object",
        "properties": {
            "domain": {
                "type": "string",
                "description": "The HA domain: switch, lock, vacuum, scene, script, automation, input_boolean, etc.",
            },
            "service": {
                "type": "string",
                "description": "The service to call: turn_on, turn_off, toggle, lock, unlock, start, etc.",
            },
            "entity_id": {
                "type": "string",
                "description": "The entity ID to control, e.g. 'switch.office_plug', 'lock.front_door'",
            },
            "service_data": {
                "type": "object",
                "description": (
                    "Additional key-value data for the service call. "
                    "Most simple services (turn_on, turn_off, lock, unlock) don't need this. "
                    "Only provide when the service requires extra parameters."
                ),
            },
        },
        "required": ["domain", "service", "entity_id"],
    },
)
async def call_service(
    domain: str, service: str, entity_id: str, service_data: dict | None = None
) -> str:
    """Generic HA service call -- fallback for domains without dedicated tools."""
    try:
        await _call_ha_service(domain, service, entity_id, service_data)

        # Verify actual state
        status = await _verify_generic(entity_id)
        return f"Done. {status}"

    except Exception as e:
        return f"Error calling service: {e}"
