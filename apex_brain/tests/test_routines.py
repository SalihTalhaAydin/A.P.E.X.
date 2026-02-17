"""Tests for routines tool."""

import pytest
from tools import discover_tools
from tools.base import TOOL_REGISTRY


@pytest.fixture(scope="module", autouse=True)
def _tools_loaded():
    discover_tools()


def test_define_routine_registered():
    """define_routine is in the registry."""
    info = TOOL_REGISTRY.get("define_routine")
    assert info is not None
    req = info["parameters"]["required"]
    assert "name" in req
    assert "steps" in req


def test_define_routine_has_trigger():
    """define_routine has optional trigger."""
    info = TOOL_REGISTRY["define_routine"]
    props = info["parameters"]["properties"]
    assert "trigger" in props
    req = info["parameters"]["required"]
    assert "trigger" not in req


def test_list_routines_registered():
    """list_routines is in the registry."""
    info = TOOL_REGISTRY.get("list_routines")
    assert info is not None


def test_run_routine_registered():
    """run_routine requires name."""
    info = TOOL_REGISTRY.get("run_routine")
    assert info is not None
    req = info["parameters"]["required"]
    assert "name" in req


def test_delete_routine_registered():
    """delete_routine requires name."""
    info = TOOL_REGISTRY.get("delete_routine")
    assert info is not None
    req = info["parameters"]["required"]
    assert "name" in req
