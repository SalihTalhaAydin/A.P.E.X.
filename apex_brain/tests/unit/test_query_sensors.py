"""Tests for query_sensors tool."""

import pytest
from tools import discover_tools
from tools.base import TOOL_REGISTRY


@pytest.fixture(scope="module", autouse=True)
def _tools_loaded():
    discover_tools()


def test_query_sensors_registered():
    """query_sensors is registered with correct params."""
    info = TOOL_REGISTRY.get("query_sensors")
    assert info is not None
    props = info["parameters"]["properties"]
    assert "sensor_type" in props
    assert "area" in props
    assert "entity_id" in props


def test_query_sensors_no_required_params():
    """query_sensors works with all-optional params."""
    info = TOOL_REGISTRY["query_sensors"]
    req = info["parameters"].get("required", [])
    assert req == []
