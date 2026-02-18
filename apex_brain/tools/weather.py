"""
Weather tool for Home Assistant.
Returns current conditions and optional daily/hourly forecasts.
"""

import logging

import httpx

from tools.base import tool
from tools.ha_helpers import (
    format_ha_error,
    ha_request,
    read_state,
)

logger = logging.getLogger(__name__)


@tool(
    description=(
        "Get current weather and optionally a forecast. "
        "Use for 'what's the weather?', 'will it rain "
        "tomorrow?', 'hourly forecast'."
    ),
    parameters={
        "type": "object",
        "properties": {
            "entity_id": {
                "type": "string",
                "description": (
                    "Weather entity. Defaults to "
                    "'weather.forecast_home'."
                ),
            },
            "forecast_type": {
                "type": "string",
                "enum": ["none", "daily", "hourly"],
                "description": (
                    "Forecast type: 'none' (current "
                    "only), 'daily', or 'hourly'. "
                    "Default: 'none'."
                ),
            },
        },
        "required": [],
    },
)
async def get_weather(
    entity_id: str = "weather.forecast_home",
    forecast_type: str = "none",
) -> str:
    """Get weather conditions and optional forecast."""
    try:
        state = await read_state(entity_id)
        attrs = state.get("attributes", {})
        condition = state.get("state", "unknown")
        temp = attrs.get("temperature", "?")
        unit = attrs.get(
            "temperature_unit", "°F"
        )
        humidity = attrs.get("humidity", "?")
        wind = attrs.get("wind_speed", "?")
        wind_unit = attrs.get(
            "wind_speed_unit", "mph"
        )

        lines = [
            f"Current: {condition}, "
            f"{temp}{unit}",
            f"Humidity: {humidity}%",
            f"Wind: {wind} {wind_unit}",
        ]

        if forecast_type in ("daily", "hourly"):
            fc = await ha_request(
                "POST",
                "/services/weather/get_forecasts",
                json_data={
                    "entity_id": entity_id,
                    "type": forecast_type,
                },
                return_response=True,
            )
            # Response: {entity_id: {"forecast": [...]}}
            forecasts = (
                fc.get(entity_id, {})
                .get("forecast", [])
                if isinstance(fc, dict)
                else []
            )
            if forecasts:
                cap = 5 if forecast_type == "daily" else 8
                lines.append(
                    f"\n{forecast_type.title()} forecast:"
                )
                for f in forecasts[:cap]:
                    dt = f.get(
                        "datetime", ""
                    )[:16]
                    cond = f.get(
                        "condition", "?"
                    )
                    hi = f.get("temperature", "?")
                    lo = f.get("templow", "")
                    precip = f.get(
                        "precipitation_probability"
                    )
                    entry = f"  {dt}: {cond}, {hi}"
                    if lo != "":
                        entry += f"/{lo}"
                    entry += unit
                    if precip is not None:
                        entry += f", {precip}% rain"
                    lines.append(entry)

        return "\n".join(lines)

    except httpx.HTTPStatusError as e:
        return format_ha_error(
            entity_id, "weather", e
        )
    except Exception as e:
        return f"Error getting weather: {e}"
