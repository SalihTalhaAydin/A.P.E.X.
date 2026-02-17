"""Tests for weather tool."""

import pytest
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
