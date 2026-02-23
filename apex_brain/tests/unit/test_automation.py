"""Tests for automation & scene tools."""

import pytest

from tools import discover_tools
from tools.base import TOOL_REGISTRY


@pytest.fixture(scope="module", autouse=True)
def _tools_loaded():
    discover_tools()


def test_list_automations_registered():
    """list_automations is in the registry."""
    info = TOOL_REGISTRY.get("list_automations")
    assert info is not None
    props = info["parameters"]["properties"]
    assert "area" in props


def test_trigger_automation_registered():
    """trigger_automation requires entity_id."""
    info = TOOL_REGISTRY.get("trigger_automation")
    assert info is not None
    req = info["parameters"]["required"]
    assert "entity_id" in req


def test_toggle_automation_has_action_enum():
    """toggle_automation has enable/disable/toggle."""
    info = TOOL_REGISTRY.get("toggle_automation")
    assert info is not None
    props = info["parameters"]["properties"]
    actions = props["action"]["enum"]
    assert "enable" in actions
    assert "disable" in actions
    assert "toggle" in actions


def test_list_scenes_registered():
    """list_scenes is in the registry."""
    info = TOOL_REGISTRY.get("list_scenes")
    assert info is not None
    props = info["parameters"]["properties"]
    assert "area" in props


def test_activate_scene_registered():
    """activate_scene requires entity_id."""
    info = TOOL_REGISTRY.get("activate_scene")
    assert info is not None
    req = info["parameters"]["required"]
    assert "entity_id" in req
