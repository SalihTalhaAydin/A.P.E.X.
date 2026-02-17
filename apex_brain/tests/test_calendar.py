"""Tests for calendar tool."""

import pytest
from tools import discover_tools
from tools.base import TOOL_REGISTRY


@pytest.fixture(scope="module", autouse=True)
def _tools_loaded():
    discover_tools()


def test_get_events_registered():
    """get_events is in the registry."""
    info = TOOL_REGISTRY.get("get_events")
    assert info is not None
    props = info["parameters"]["properties"]
    assert "days_ahead" in props


def test_create_event_registered():
    """create_event requires title, start, end."""
    info = TOOL_REGISTRY.get("create_event")
    assert info is not None
    req = info["parameters"]["required"]
    assert "title" in req
    assert "start" in req
    assert "end" in req


def test_create_event_has_optional_fields():
    """create_event has description and location."""
    info = TOOL_REGISTRY["create_event"]
    props = info["parameters"]["properties"]
    assert "description" in props
    assert "location" in props
    req = info["parameters"]["required"]
    assert "description" not in req
    assert "location" not in req


def test_get_today_schedule_registered():
    """get_today_schedule is in the registry."""
    info = TOOL_REGISTRY.get("get_today_schedule")
    assert info is not None


def test_delete_event_registered():
    """delete_event requires event_id."""
    info = TOOL_REGISTRY.get("delete_event")
    assert info is not None
    req = info["parameters"]["required"]
    assert "event_id" in req
