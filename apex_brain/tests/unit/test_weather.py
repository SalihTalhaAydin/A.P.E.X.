"""Tests for weather tool."""

import pytest
from unittest.mock import AsyncMock, patch

from tools import discover_tools
from tools.base import TOOL_REGISTRY


@pytest.fixture(scope="module", autouse=True)
def _tools_loaded():
    discover_tools()


def test_get_weather_registered():
    """get_weather is registered with forecast_type enum."""
    info = TOOL_REGISTRY.get("get_weather")
    assert info is not None
    props = info["parameters"]["properties"]
    assert "entity_id" in props
    ft = props["forecast_type"]
    assert ft["type"] == "string"
    assert "daily" in ft["enum"]
    assert "hourly" in ft["enum"]
    assert "none" in ft["enum"]


def test_get_weather_no_required_params():
    """get_weather works with no required params (defaults)."""
    info = TOOL_REGISTRY["get_weather"]
    req = info["parameters"].get("required", [])
    assert req == []


@pytest.mark.asyncio
async def test_get_weather_forecast_templow_null_no_none_in_output():
    """BUG-97: When HA returns templow: null, output must not contain 'None'."""
    from tools.weather import get_weather

    async def mock_read_state(entity_id):
        return {
            "state": "cloudy",
            "attributes": {
                "temperature": 72,
                "temperature_unit": "°F",
                "humidity": 65,
                "wind_speed": 10,
                "wind_speed_unit": "mph",
            },
        }

    # Forecast with templow: null (key exists, value is None)
    mock_forecast = {
        "weather.forecast_home": {
            "forecast": [
                {
                    "datetime": "2025-02-22T12:00:00",
                    "condition": "cloudy",
                    "temperature": 72,
                    "templow": None,  # HA returns null for some forecasts
                    "precipitation_probability": 20,
                },
            ]
        }
    }

    with (
        patch("tools.weather.read_state", side_effect=mock_read_state),
        patch("tools.weather.ha_request", new_callable=AsyncMock, return_value=mock_forecast),
    ):
        result = await get_weather(
            entity_id="weather.forecast_home",
            forecast_type="daily",
        )

    assert "None" not in result, f"Output must not contain 'None' when templow is null: {result!r}"
