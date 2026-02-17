"""Tests for smart_home tools (control_media power on/off, etc.)."""

import pytest
from tools import discover_tools
from tools.base import TOOL_REGISTRY


@pytest.fixture(scope="module", autouse=True)
def _tools_loaded():
    """Ensure all tools (including smart_home) are discovered."""
    discover_tools()


def test_control_media_has_turn_on_turn_off():
    """control_media supports turn_on and turn_off for TVs."""
    info = TOOL_REGISTRY.get("control_media")
    assert info is not None
    action_enum = info["parameters"]["properties"]["action"]["enum"]
    assert "turn_on" in action_enum
    assert "turn_off" in action_enum
