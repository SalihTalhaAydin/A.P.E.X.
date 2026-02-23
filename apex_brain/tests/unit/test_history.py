"""Tests for history tool (get_history, get_logbook)."""

import pytest
from unittest.mock import AsyncMock, patch

from tools import discover_tools
from tools.base import TOOL_REGISTRY
from tools.history import get_history, get_logbook


@pytest.fixture(scope="module", autouse=True)
def _tools_loaded():
    discover_tools()


def test_get_history_registered():
    """get_history is in the registry."""
    info = TOOL_REGISTRY.get("get_history")
    assert info is not None
    props = info["parameters"]["properties"]
    assert "entity_id" in props
    assert "hours_back" in props
    req = info["parameters"]["required"]
    assert "entity_id" in req


def test_get_logbook_registered():
    """get_logbook is in the registry."""
    info = TOOL_REGISTRY.get("get_logbook")
    assert info is not None
    props = info["parameters"]["properties"]
    assert "entity_id" in props
    assert "hours_back" in props


@pytest.mark.asyncio
async def test_get_history_delegates_to_generic_history():
    """get_history calls generic history() with correct args."""
    with patch(
        "tools.history.history", new_callable=AsyncMock
    ) as mock_history:
        mock_history.return_value = "Light was on from 10:00 to 14:00"
        result = await get_history("light.living_room", hours_back=24)
        mock_history.assert_called_once_with(
            "light.living_room", 24, "changes"
        )
        assert "10:00" in result or "Light" in result


@pytest.mark.asyncio
async def test_get_history_clamps_hours_back():
    """get_history clamps hours_back to 1-168."""
    with patch(
        "tools.history.history", new_callable=AsyncMock
    ) as mock_history:
        mock_history.return_value = "ok"
        await get_history("light.x", hours_back=500)
        mock_history.assert_called_once_with("light.x", 168, "changes")
        mock_history.reset_mock()
        await get_history("light.x", hours_back=0)
        mock_history.assert_called_once_with("light.x", 1, "changes")


@pytest.mark.asyncio
async def test_get_logbook_delegates_to_generic_history():
    """get_logbook calls generic history() with logbook mode."""
    with patch(
        "tools.history.history", new_callable=AsyncMock
    ) as mock_history:
        mock_history.return_value = "Door opened at 9:00"
        result = await get_logbook(
            entity_id="binary_sensor.door", hours_back=12
        )
        mock_history.assert_called_once_with(
            "binary_sensor.door", 12, "logbook"
        )
        assert "Door" in result or "9:00" in result


@pytest.mark.asyncio
async def test_get_history_returns_error_on_exception():
    """get_history returns error message when history() raises."""
    with patch(
        "tools.history.history", new_callable=AsyncMock
    ) as mock_history:
        mock_history.side_effect = RuntimeError("Connection failed")
        result = await get_history("light.x")
        assert "Error" in result
        assert "Connection" in result or "failed" in result
