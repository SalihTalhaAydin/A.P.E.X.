"""Tests for notify tool."""

import pytest
from tools import discover_tools
from tools.base import TOOL_REGISTRY


@pytest.fixture(scope="module", autouse=True)
def _tools_loaded():
    discover_tools()


def test_send_notification_registered():
    """send_notification is registered with correct params."""
    info = TOOL_REGISTRY.get("send_notification")
    assert info is not None
    props = info["parameters"]["properties"]
    assert "entity_id" in props
    assert "message" in props
    assert "title" in props
    req = info["parameters"]["required"]
    assert "entity_id" in req
    assert "message" in req
    assert "title" not in req
