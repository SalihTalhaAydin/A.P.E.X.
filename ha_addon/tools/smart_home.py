"""
Smart Home Tools - Control Home Assistant devices.
Used by Apex. HA REST API, auto-authenticated via SUPERVISOR_TOKEN when running as add-on.
"""

import httpx
from tools.base import tool
from brain.config import settings


async def _ha_request(method: str, path: str, json_data: dict | None = None) -> dict | list | str:
    """Make an authenticated request to the HA REST API."""
    url = f"{settings.ha_api_url}{path}"
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.request(
            method=method,
            url=url,
            headers=settings.ha_headers,
            json=json_data,
        )
        response.raise_for_status()
        return response.json()


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
        if "color_temp" in attrs:
            info.append(f"  Color temp: {attrs['color_temp']}")
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

        return "\n".join(info)
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            return f"Entity '{entity_id}' not found."
        return f"Error: {e}"
    except Exception as e:
        return f"Error getting state: {e}"


@tool(
    description=(
        "Control a smart home device: turn on/off lights, set thermostat temperature, "
        "lock/unlock doors, set brightness, play/pause media, etc. "
        "Common services: turn_on, turn_off, toggle, set_temperature, lock, unlock, "
        "set_hvac_mode, media_play, media_pause, set_volume_level."
    ),
    parameters={
        "type": "object",
        "properties": {
            "domain": {
                "type": "string",
                "description": "The domain: light, switch, climate, lock, media_player, cover, fan, etc.",
            },
            "service": {
                "type": "string",
                "description": "The service to call: turn_on, turn_off, toggle, set_temperature, etc.",
            },
            "entity_id": {
                "type": "string",
                "description": "The entity ID to control, e.g. 'light.living_room'",
            },
            "data": {
                "type": "object",
                "description": (
                    "Optional service data. Examples: "
                    "{'brightness_pct': 50} for lights, "
                    "{'temperature': 72} for climate, "
                    "{'volume_level': 0.5} for media"
                ),
            },
        },
        "required": ["domain", "service", "entity_id"],
    },
)
async def call_service(
    domain: str, service: str, entity_id: str, data: dict | None = None
) -> str:
    """Call a Home Assistant service to control a device."""
    try:
        payload = {"entity_id": entity_id}
        if data:
            payload.update(data)

        result = await _ha_request(
            "POST", f"/services/{domain}/{service}", json_data=payload
        )

        # Build a natural confirmation
        friendly = entity_id.split(".")[-1].replace("_", " ").title()
        if service == "turn_on":
            extra = ""
            if data and "brightness_pct" in data:
                extra = f" at {data['brightness_pct']}% brightness"
            return f"Done. {friendly} is now on{extra}."
        elif service == "turn_off":
            return f"Done. {friendly} is now off."
        elif service == "toggle":
            return f"Done. Toggled {friendly}."
        elif service == "set_temperature":
            temp = data.get("temperature", "?") if data else "?"
            return f"Done. {friendly} set to {temp}°."
        elif service == "lock":
            return f"Done. {friendly} is locked."
        elif service == "unlock":
            return f"Done. {friendly} is unlocked."
        else:
            return f"Done. Called {domain}.{service} on {friendly}."

    except Exception as e:
        return f"Error calling service: {e}"


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
