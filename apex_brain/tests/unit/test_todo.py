"""Tests for todo tool."""

import pytest
from tools import discover_tools
from tools.base import TOOL_REGISTRY


@pytest.fixture(scope="module", autouse=True)
def _tools_loaded():
    discover_tools()


def test_manage_todo_registered():
    """manage_todo is registered with correct actions."""
    info = TOOL_REGISTRY.get("manage_todo")
    assert info is not None
    props = info["parameters"]["properties"]
    actions = props["action"]["enum"]
    assert "view" in actions
    assert "add" in actions
    assert "complete" in actions
    assert "remove" in actions
    assert "clear_completed" in actions


def test_manage_todo_item_optional():
    """item param is optional (only needed for add/complete/remove)."""
    info = TOOL_REGISTRY["manage_todo"]
    req = info["parameters"]["required"]
    assert "entity_id" in req
    assert "action" in req
    assert "item" not in req
