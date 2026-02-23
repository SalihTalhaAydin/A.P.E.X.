"""Tests for energy tool."""

import pytest
from unittest.mock import AsyncMock, patch

from tools.base import TOOL_REGISTRY
from tools.energy import (
    get_energy_entities,
    get_energy_summary,
    _is_energy_entity,
    _format_reading,
    _categorize_power_reading,
    _fmt_w,
)


@pytest.fixture(scope="module")
def _tools_loaded():
    from tools import discover_tools
    discover_tools()


@pytest.mark.usefixtures("_tools_loaded")
def test_get_energy_entities_registered():
    """get_energy_entities is in the registry."""
    info = TOOL_REGISTRY.get("get_energy_entities")
    assert info is not None


@pytest.mark.usefixtures("_tools_loaded")
def test_get_energy_summary_registered():
    """get_energy_summary is in the registry."""
    info = TOOL_REGISTRY.get("get_energy_summary")
    assert info is not None


def test_is_energy_entity_by_device_class():
    """_is_energy_entity returns True for device_class energy/power."""
    assert _is_energy_entity(
        {"entity_id": "sensor.x", "attributes": {"device_class": "power"}}
    ) is True
    assert _is_energy_entity(
        {"entity_id": "sensor.x", "attributes": {"device_class": "energy"}}
    ) is True


def test_is_energy_entity_by_unit():
    """_is_energy_entity returns True for W, kW, Wh, kWh units."""
    for unit in ("W", "kW", "Wh", "kWh"):
        assert _is_energy_entity(
            {
                "entity_id": "sensor.x",
                "attributes": {"unit_of_measurement": unit},
            }
        ) is True


def test_is_energy_entity_by_entity_id_pattern():
    """_is_energy_entity returns True for energy-like entity_id patterns."""
    assert _is_energy_entity(
        {"entity_id": "sensor.solar_generation", "attributes": {}}
    ) is True
    assert _is_energy_entity(
        {"entity_id": "sensor.grid_consumption", "attributes": {}}
    ) is True


def test_is_energy_entity_returns_false_for_light():
    """_is_energy_entity returns False for non-energy entities."""
    assert _is_energy_entity(
        {"entity_id": "light.living_room", "attributes": {}}
    ) is False


def test_format_reading_includes_entity_id():
    """_format_reading includes entity_id in output."""
    entity = {
        "entity_id": "sensor.solar",
        "attributes": {"friendly_name": "Solar", "unit_of_measurement": "W"},
        "state": "1500",
    }
    result = _format_reading(entity)
    assert "sensor.solar" in result
    assert "1500" in result
    assert "W" in result


@pytest.mark.asyncio
async def test_get_energy_entities_empty_when_no_energy():
    """get_energy_entities returns message when no energy entities found."""
    with patch("tools.energy.ha_request", new_callable=AsyncMock) as mock_ha:
        mock_ha.return_value = [
            {"entity_id": "light.living", "attributes": {}, "state": "on"},
        ]

        result = await get_energy_entities()

        assert "No energy-related" in result or "not found" in result.lower()


@pytest.mark.asyncio
async def test_get_energy_entities_lists_power_sensors():
    """get_energy_entities lists power sensors when present."""
    with patch("tools.energy.ha_request", new_callable=AsyncMock) as mock_ha:
        mock_ha.return_value = [
            {
                "entity_id": "sensor.solar_power",
                "attributes": {
                    "device_class": "power",
                    "friendly_name": "Solar",
                    "unit_of_measurement": "W",
                },
                "state": "1200",
            },
        ]

        result = await get_energy_entities()

        assert "Power sensors" in result
        assert "solar_power" in result
        assert "1200" in result


@pytest.mark.asyncio
async def test_get_energy_summary_with_entities():
    """get_energy_summary returns summary when energy entities exist."""
    with patch("tools.energy.ha_request", new_callable=AsyncMock) as mock_ha:
        mock_ha.return_value = [
            {
                "entity_id": "sensor.home_power",
                "attributes": {
                    "device_class": "power",
                    "friendly_name": "Home Power",
                    "unit_of_measurement": "W",
                },
                "state": "450",
            },
        ]

        result = await get_energy_summary()

        assert "power" in result.lower() or "450" in result


def test_categorize_power_reading_generating():
    """_categorize_power_reading returns generating for solar/PV."""
    assert _categorize_power_reading(
        {"entity_id": "sensor.solar_power", "name": "Solar", "value_w": 5000}
    ) == "generating"
    assert _categorize_power_reading(
        {"entity_id": "sensor.pv", "name": "PV", "value_w": 100}
    ) == "generating"


def test_categorize_power_reading_from_grid():
    """_categorize_power_reading returns from_grid for grid/import/mains."""
    assert _categorize_power_reading(
        {"entity_id": "sensor.grid_import", "name": "Grid", "value_w": 2000}
    ) == "from_grid"
    assert _categorize_power_reading(
        {"entity_id": "sensor.mains_power", "name": "Mains", "value_w": 500}
    ) == "from_grid"


def test_categorize_power_reading_exporting():
    """_categorize_power_reading returns exporting for export/feed."""
    assert _categorize_power_reading(
        {"entity_id": "sensor.grid_export", "name": "Export", "value_w": 3000}
    ) == "exporting"


def test_categorize_power_reading_consumption():
    """_categorize_power_reading returns consumption for device/load sensors."""
    assert _categorize_power_reading(
        {"entity_id": "sensor.living_room_power", "name": "Living Room", "value_w": 450}
    ) == "consumption"


def test_fmt_w():
    """_fmt_w formats watts as kW or W."""
    assert _fmt_w(500) == "500.0 W"
    assert _fmt_w(1500) == "1.5 kW"
    assert _fmt_w(-2000) == "-2.0 kW"


@pytest.mark.asyncio
async def test_get_energy_summary_net_consumption():
    """get_energy_summary computes net consumption from categories (P8-BUG-135)."""
    with patch("tools.energy.ha_request", new_callable=AsyncMock) as mock_ha:
        # Solar 5kW, grid import 2kW, device 500W, export 3kW
        # Net = 2000 + 500 - 5000 - 3000 = -5500 (exporting more than consuming)
        mock_ha.return_value = [
            {
                "entity_id": "sensor.solar_power",
                "attributes": {
                    "device_class": "power",
                    "friendly_name": "Solar",
                    "unit_of_measurement": "W",
                },
                "state": "5000",
            },
            {
                "entity_id": "sensor.grid_import",
                "attributes": {
                    "device_class": "power",
                    "friendly_name": "Grid Import",
                    "unit_of_measurement": "W",
                },
                "state": "2000",
            },
            {
                "entity_id": "sensor.tv_power",
                "attributes": {
                    "device_class": "power",
                    "friendly_name": "TV",
                    "unit_of_measurement": "W",
                },
                "state": "500",
            },
            {
                "entity_id": "sensor.grid_export",
                "attributes": {
                    "device_class": "power",
                    "friendly_name": "Grid Export",
                    "unit_of_measurement": "W",
                },
                "state": "3000",
            },
        ]

        result = await get_energy_summary()

        # Old bug: would sum all 5000+2000+500+3000 = 10500 W (meaningless)
        # Fixed: net = 2000 + 500 - 5000 - 3000 = -5500 W (exporting)
        assert "Net consumption" in result
        assert "-5.5 kW" in result or "-5500" in result
        assert "(generating)" in result
        assert "(from grid)" in result
        assert "(exporting)" in result
        assert "(consuming)" in result
        assert "Breakdown" in result


@pytest.mark.asyncio
async def test_get_energy_summary_net_positive_consumption():
    """Net consumption is positive when importing and consuming."""
    with patch("tools.energy.ha_request", new_callable=AsyncMock) as mock_ha:
        # Grid 2kW, device 1kW, no solar/export
        mock_ha.return_value = [
            {
                "entity_id": "sensor.grid_import",
                "attributes": {
                    "device_class": "power",
                    "friendly_name": "Grid",
                    "unit_of_measurement": "W",
                },
                "state": "2000",
            },
            {
                "entity_id": "sensor.home_consumption",
                "attributes": {
                    "device_class": "power",
                    "friendly_name": "Home",
                    "unit_of_measurement": "W",
                },
                "state": "1000",
            },
        ]

        result = await get_energy_summary()

        assert "Net consumption" in result
        assert "3.0 kW" in result or "3000" in result


@pytest.mark.asyncio
async def test_get_energy_summary_with_only_energy_wh_sensors():
    """get_energy_summary shows energy totals when only Wh/kWh sensors exist."""
    with patch("tools.energy.ha_request", new_callable=AsyncMock) as mock_ha:
        mock_ha.return_value = [
            {
                "entity_id": "sensor.daily_consumption",
                "attributes": {
                    "device_class": "energy",
                    "friendly_name": "Daily Consumption",
                    "unit_of_measurement": "kWh",
                },
                "state": "12.5",
            },
            {
                "entity_id": "sensor.solar_production",
                "attributes": {
                    "device_class": "energy",
                    "friendly_name": "Solar Production",
                    "unit_of_measurement": "Wh",
                },
                "state": "8500",
            },
        ]

        result = await get_energy_summary()

        assert "Energy Summary" in result
        assert "Energy Totals" in result
        assert "12.5" in result
        assert "8.5" in result or "8500" in result
        assert "kWh" in result


@pytest.mark.asyncio
async def test_get_energy_entities_when_states_not_list_returns_error_message():
    """get_energy_entities returns error when ha_request returns error dict."""
    with patch("tools.energy.ha_request", new_callable=AsyncMock) as mock_ha:
        mock_ha.return_value = {"message": "Connection refused"}

        result = await get_energy_entities()

        assert "Unable" in result or "Connection" in result or "error" in result.lower()


@pytest.mark.asyncio
async def test_get_energy_summary_when_states_not_list_returns_error_message():
    """get_energy_summary returns error message when ha_request returns non-list."""
    with patch("tools.energy.ha_request", new_callable=AsyncMock) as mock_ha:
        mock_ha.return_value = {"message": "Connection refused"}

        result = await get_energy_summary()

        assert "Unable" in result or "Connection" in result or "error" in result.lower()
