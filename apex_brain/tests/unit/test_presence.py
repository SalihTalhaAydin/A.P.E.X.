"""Tests for presence tool."""

import pytest
from tools import discover_tools
from tools.base import TOOL_REGISTRY


@pytest.fixture(scope="module", autouse=True)
def _tools_loaded():
    discover_tools()


def test_get_presence_registered():
    """get_presence is in the registry."""
    info = TOOL_REGISTRY.get("get_presence")
    assert info is not None


def test_get_presence_has_person_param():
    """get_presence has optional person parameter."""
    info = TOOL_REGISTRY["get_presence"]
    props = info["parameters"]["properties"]
    assert "person" in props
    req = info["parameters"]["required"]
    assert "person" not in req
