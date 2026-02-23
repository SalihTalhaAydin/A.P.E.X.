"""Tests that tools handle ha_request() returning an error dict (BUG-111).

When HA is unreachable, ha_request returns {'error': '...'} instead of a list.
Tools that iterate over the result must check isinstance(states, list) first.
"""

import pytest
from unittest.mock import AsyncMock, patch


@pytest.mark.asyncio
async def test_list_automations_handles_ha_error_dict():
    """When ha_request returns error dict instead of list, return friendly error."""
    from tools.automation import list_automations

    with patch("tools.automation.ha_request", new_callable=AsyncMock) as mock_ha:
        mock_ha.return_value = {"error": "Cannot connect to Home Assistant"}
        result = await list_automations()
    assert "Error" in result
    assert "Unable to reach" in result or "connect" in result.lower()


@pytest.mark.asyncio
async def test_list_scenes_handles_ha_error_dict():
    """When ha_request returns error dict instead of list, return friendly error."""
    from tools.automation import list_scenes

    with patch("tools.automation.ha_request", new_callable=AsyncMock) as mock_ha:
        mock_ha.return_value = {"error": "Cannot connect"}
        result = await list_scenes()
    assert "Error" in result or "Unable to reach" in result or "connect" in result.lower()


@pytest.mark.asyncio
async def test_get_energy_summary_handles_ha_error_dict():
    """When ha_request returns error dict instead of list, return friendly error."""
    from tools.energy import get_energy_summary

    with patch("tools.energy.ha_request", new_callable=AsyncMock) as mock_ha:
        mock_ha.return_value = {"error": "Cannot connect"}
        result = await get_energy_summary()
    assert "Error" in result or "Unable to reach" in result or "connect" in result.lower()


@pytest.mark.asyncio
async def test_get_energy_entities_handles_ha_error_dict():
    """When ha_request returns error dict instead of list, return friendly error."""
    from tools.energy import get_energy_entities

    with patch("tools.energy.ha_request", new_callable=AsyncMock) as mock_ha:
        mock_ha.return_value = {"error": "Cannot connect"}
        result = await get_energy_entities()
    assert "Error" in result or "Unable to reach" in result or "connect" in result.lower()


@pytest.mark.asyncio
async def test_get_presence_summary_handles_ha_error_dict():
    """When ha_request returns error dict instead of list, return gracefully (no crash)."""
    from tools.presence import get_presence_summary

    with patch("tools.presence.ha_request", new_callable=AsyncMock) as mock_ha:
        mock_ha.return_value = {"error": "Cannot connect"}
        result = await get_presence_summary()
    # get_presence_summary returns "" on error dict (used by context builder)
    assert isinstance(result, str)
    assert result == "" or "Error" in result or "Unable" in result or "connect" in result.lower()


@pytest.mark.asyncio
async def test_list_webhook_automations_handles_ha_error_dict():
    """When ha_request returns error dict instead of list, return friendly error."""
    from tools.webhook import list_webhook_automations

    with patch("tools.webhook.ha_request", new_callable=AsyncMock) as mock_ha:
        mock_ha.return_value = {"error": "Cannot connect"}
        result = await list_webhook_automations()
    assert "Error" in result or "Unable to reach" in result or "connect" in result.lower()
