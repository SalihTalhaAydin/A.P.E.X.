"""Tests for vacuum tool."""

import pytest
from tools import discover_tools
from tools.base import TOOL_REGISTRY


@pytest.fixture(scope="module", autouse=True)
def _tools_loaded():
    discover_tools()


def test_control_vacuum_registered():
    """control_vacuum is registered with correct actions."""
    info = TOOL_REGISTRY.get("control_vacuum")
    assert info is not None
    props = info["parameters"]["properties"]
    assert "entity_id" in props
    actions = props["action"]["enum"]
    assert "start" in actions
    assert "pause" in actions
    assert "stop" in actions
    assert "return_to_base" in actions
    assert "locate" in actions


def test_control_vacuum_has_fan_speed():
    """control_vacuum exposes optional fan_speed."""
    info = TOOL_REGISTRY["control_vacuum"]
    props = info["parameters"]["properties"]
    assert "fan_speed" in props
    req = info["parameters"]["required"]
    assert "fan_speed" not in req
