"""Tests for vacuum tool and battery-level fallback."""

from unittest.mock import AsyncMock, patch

import httpx
import pytest
from tools import discover_tools
from tools.base import TOOL_REGISTRY
from tools.ha_helpers import get_battery_level


@pytest.fixture(scope="module", autouse=True)
def _tools_loaded():
    discover_tools()


def test_control_vacuum_registered():
    """control_vacuum is registered with correct actions."""
    info = TOOL_REGISTRY.get("control_vacuum")
    assert info is not None
    props = info["parameters"]["properties"]
    assert "entity_id" in props
    actions = props["action"]["enum"]
    assert "start" in actions
    assert "pause" in actions
    assert "stop" in actions
    assert "return_to_base" in actions
    assert "locate" in actions


def test_control_vacuum_has_fan_speed():
    """control_vacuum exposes optional fan_speed."""
    info = TOOL_REGISTRY["control_vacuum"]
    props = info["parameters"]["properties"]
    assert "fan_speed" in props
    req = info["parameters"]["required"]
    assert "fan_speed" not in req


# ---------------------------------------------------
# Battery-level fallback tests  (Issue #4)
# ---------------------------------------------------


@pytest.mark.asyncio
async def test_verify_vacuum_battery_from_attrs():
    """Battery shown when present in vacuum attributes."""
    from tools.vacuum import _verify_vacuum

    mock_state = {
        "state": "docked",
        "attributes": {
            "friendly_name": "Dusty",
            "battery_level": 75,
            "fan_speed": "balanced",
        },
    }
    with patch(
        "tools.vacuum.read_state",
        new_callable=AsyncMock,
        return_value=mock_state,
    ), patch(
        "tools.vacuum.get_battery_level",
        new_callable=AsyncMock,
        return_value=75,
    ):
        result = await _verify_vacuum("vacuum.dusty")
    assert "battery 75%" in result
    assert "Dusty" in result


@pytest.mark.asyncio
async def test_verify_vacuum_battery_fallback_sensor():
    """Battery shown via sensor fallback when missing
    from vacuum attributes (Issue #4)."""
    from tools.vacuum import _verify_vacuum

    mock_state = {
        "state": "docked",
        "attributes": {
            "friendly_name": "Dusty",
            "fan_speed": "balanced",
        },
    }
    with patch(
        "tools.vacuum.read_state",
        new_callable=AsyncMock,
        return_value=mock_state,
    ), patch(
        "tools.vacuum.get_battery_level",
        new_callable=AsyncMock,
        return_value=75,
    ):
        result = await _verify_vacuum("vacuum.dusty")
    assert "battery 75%" in result


@pytest.mark.asyncio
async def test_verify_vacuum_no_battery_anywhere():
    """No battery info shown when unavailable everywhere."""
    from tools.vacuum import _verify_vacuum

    mock_state = {
        "state": "cleaning",
        "attributes": {"friendly_name": "Dusty"},
    }
    with patch(
        "tools.vacuum.read_state",
        new_callable=AsyncMock,
        return_value=mock_state,
    ), patch(
        "tools.vacuum.get_battery_level",
        new_callable=AsyncMock,
        return_value=None,
    ):
        result = await _verify_vacuum("vacuum.dusty")
    assert "battery" not in result.lower()
    assert "Dusty: cleaning" in result


# ---------------------------------------------------
# Water level tests  (Bug vacuumBug1)
# ---------------------------------------------------


@pytest.mark.asyncio
async def test_verify_vacuum_water_box_mode():
    """Water box mode shown when present in attrs."""
    from tools.vacuum import _verify_vacuum

    mock_state = {
        "state": "docked",
        "attributes": {
            "friendly_name": "Dusty",
            "water_box_mode": "medium",
        },
    }
    with patch(
        "tools.vacuum.read_state",
        new_callable=AsyncMock,
        return_value=mock_state,
    ), patch(
        "tools.vacuum.get_battery_level",
        new_callable=AsyncMock,
        return_value=None,
    ):
        result = await _verify_vacuum("vacuum.dusty")
    assert "water box mode" in result.lower()
    assert "medium" in result


@pytest.mark.asyncio
async def test_verify_vacuum_water_level_attr():
    """water_level attribute shown when present."""
    from tools.vacuum import _verify_vacuum

    mock_state = {
        "state": "docked",
        "attributes": {
            "friendly_name": "Dusty",
            "water_level": 60,
        },
    }
    with patch(
        "tools.vacuum.read_state",
        new_callable=AsyncMock,
        return_value=mock_state,
    ), patch(
        "tools.vacuum.get_battery_level",
        new_callable=AsyncMock,
        return_value=None,
    ):
        result = await _verify_vacuum("vacuum.dusty")
    assert "water level" in result.lower()
    assert "60" in result


@pytest.mark.asyncio
async def test_verify_vacuum_no_water_attrs():
    """No water info when vacuum has no water attrs."""
    from tools.vacuum import _verify_vacuum

    mock_state = {
        "state": "docked",
        "attributes": {"friendly_name": "Dusty"},
    }
    with patch(
        "tools.vacuum.read_state",
        new_callable=AsyncMock,
        return_value=mock_state,
    ), patch(
        "tools.vacuum.get_battery_level",
        new_callable=AsyncMock,
        return_value=None,
    ):
        result = await _verify_vacuum("vacuum.dusty")
    assert "water" not in result.lower()


# ---------------------------------------------------
# get_battery_level helper tests
# ---------------------------------------------------


@pytest.mark.asyncio
async def test_get_battery_level_from_entity_attrs():
    """Battery returned from entity attributes directly."""
    mock_state = {
        "state": "docked",
        "attributes": {"battery_level": 53},
    }
    with patch(
        "tools.ha_helpers.read_state",
        new_callable=AsyncMock,
        return_value=mock_state,
    ):
        result = await get_battery_level("vacuum.hairy")
    assert result == 53


@pytest.mark.asyncio
async def test_get_battery_level_fallback_to_sensor():
    """Battery returned from sensor.<name>_battery
    when entity attribute is missing."""
    vacuum_state = {
        "state": "docked",
        "attributes": {},
    }
    sensor_state = {
        "state": "75",
        "attributes": {},
    }

    async def _mock_read(eid):
        if eid == "vacuum.dusty":
            return vacuum_state
        if eid == "sensor.dusty_battery":
            return sensor_state
        raise httpx.HTTPStatusError(
            "Not found",
            request=None,
            response=type("R", (), {"status_code": 404})(),
        )

    with patch(
        "tools.ha_helpers.read_state",
        side_effect=_mock_read,
    ):
        result = await get_battery_level("vacuum.dusty")
    assert result == 75


@pytest.mark.asyncio
async def test_get_battery_level_none_when_unavailable():
    """Returns None when battery is not available anywhere."""
    vacuum_state = {
        "state": "docked",
        "attributes": {},
    }
    sensor_state = {
        "state": "unavailable",
        "attributes": {},
    }

    async def _mock_read(eid):
        if eid == "vacuum.dusty":
            return vacuum_state
        if eid == "sensor.dusty_battery":
            return sensor_state
        raise Exception("not found")

    with patch(
        "tools.ha_helpers.read_state",
        side_effect=_mock_read,
    ):
        result = await get_battery_level("vacuum.dusty")
    assert result is None


# ---------------------------------------------------
# Dock error / water sensor tests
# ---------------------------------------------------


@pytest.mark.asyncio
async def test_verify_vacuum_dock_water_empty():
    """Water-empty warning shown when dock_dock_error=water_empty."""
    from tools.vacuum import _verify_vacuum

    vac_state = {
        "state": "docked",
        "attributes": {"friendly_name": "Dusty"},
    }
    dock_err_state = {"state": "water_empty", "attributes": {}}
    unavailable = {"state": "unavailable", "attributes": {}}

    async def _mock_read(eid):
        if eid == "vacuum.dusty":
            return vac_state
        if eid == "sensor.dusty_dock_dock_error":
            return dock_err_state
        return unavailable

    with patch(
        "tools.vacuum.read_state",
        side_effect=_mock_read,
    ), patch(
        "tools.vacuum.get_battery_level",
        new_callable=AsyncMock,
        return_value=None,
    ):
        result = await _verify_vacuum("vacuum.dusty")
    assert "water" in result.lower()
    assert "empty" in result.lower()


@pytest.mark.asyncio
async def test_verify_vacuum_dock_status_ok_no_warning():
    """No dock warning when dock_dock_error=ok."""
    from tools.vacuum import _verify_vacuum

    vac_state = {
        "state": "docked",
        "attributes": {"friendly_name": "Dusty"},
    }
    dock_ok_state = {"state": "ok", "attributes": {}}
    unavailable = {"state": "unavailable", "attributes": {}}

    async def _mock_read(eid):
        if eid == "vacuum.dusty":
            return vac_state
        if eid == "sensor.dusty_dock_dock_error":
            return dock_ok_state
        return unavailable

    with patch(
        "tools.vacuum.read_state",
        side_effect=_mock_read,
    ), patch(
        "tools.vacuum.get_battery_level",
        new_callable=AsyncMock,
        return_value=None,
    ):
        result = await _verify_vacuum("vacuum.dusty")
    assert "empty" not in result.lower()
    assert "Dusty: docked" in result


@pytest.mark.asyncio
async def test_verify_vacuum_dock_sensor_unavailable_no_crash():
    """_verify_vacuum does not crash when dock sensor missing."""
    from tools.vacuum import _verify_vacuum

    vac_state = {
        "state": "docked",
        "attributes": {"friendly_name": "Dusty"},
    }

    async def _mock_read(eid):
        if eid == "vacuum.dusty":
            return vac_state
        raise Exception("sensor not found")

    with patch(
        "tools.vacuum.read_state",
        side_effect=_mock_read,
    ), patch(
        "tools.vacuum.get_battery_level",
        new_callable=AsyncMock,
        return_value=None,
    ):
        result = await _verify_vacuum("vacuum.dusty")
    assert "Dusty" in result
    assert "docked" in result


@pytest.mark.asyncio
async def test_verify_vacuum_maintenance_overdue():
    """Overdue maintenance components are listed."""
    from tools.vacuum import _verify_vacuum

    vac_state = {
        "state": "docked",
        "attributes": {"friendly_name": "Dusty"},
    }
    overdue = {"state": "-200", "attributes": {}}
    unavailable = {"state": "unavailable", "attributes": {}}

    async def _mock_read(eid):
        if eid == "vacuum.dusty":
            return vac_state
        if "dock_dock_error" in eid:
            return {"state": "ok", "attributes": {}}
        if "filter_time_left" in eid:
            return overdue
        if "main_brush_time_left" in eid:
            return overdue
        return unavailable

    with patch(
        "tools.vacuum.read_state",
        side_effect=_mock_read,
    ), patch(
        "tools.vacuum.get_battery_level",
        new_callable=AsyncMock,
        return_value=None,
    ):
        result = await _verify_vacuum("vacuum.dusty")
    assert "maintenance overdue" in result.lower()
    assert "filter" in result.lower()
    assert "main brush" in result.lower()


def test_get_vacuum_status_registered():
    """get_vacuum_status is registered as a tool."""
    info = TOOL_REGISTRY.get("get_vacuum_status")
    assert info is not None
    props = info["parameters"]["properties"]
    assert "entity_id" in props
    assert info["parameters"]["required"] == ["entity_id"]


# ---------------------------------------------------
# clean_rooms tool tests
# ---------------------------------------------------


@pytest.mark.asyncio
async def test_clean_rooms_registered():
    """clean_rooms is registered in the tool registry."""
    info = TOOL_REGISTRY.get("clean_rooms")
    assert info is not None
    props = info["parameters"]["properties"]
    assert "rooms" in props
    assert "entity_id" in props
    assert "rooms" in info["parameters"]["required"]
    assert "entity_id" not in info["parameters"]["required"]


@pytest.mark.asyncio
async def test_clean_rooms_segment_lookup_from_room_list():
    """Segment IDs are correctly resolved from room_list attribute."""
    from tools.vacuum import clean_rooms

    mock_state = {
        "state": "docked",
        "attributes": {
            "friendly_name": "Dusty",
            "room_list": {"16": "Kitchen", "17": "Living Room", "18": "Bedroom"},
        },
    }

    with patch(
        "tools.vacuum.read_state",
        new_callable=AsyncMock,
        return_value=mock_state,
    ), patch(
        "tools.vacuum.ha_request",
        new_callable=AsyncMock,
        return_value={},
    ) as mock_ha:
        result = await clean_rooms(
            rooms=["kitchen"], entity_id="vacuum.dusty"
        )

    # Verify the roborock service was called with segment 16
    mock_ha.assert_called_once_with(
        "POST",
        "/services/roborock/vacuum_clean_segment",
        json_data={"entity_id": "vacuum.dusty", "segments": [16]},
    )
    assert "Kitchen" in result


@pytest.mark.asyncio
async def test_clean_rooms_partial_name_match():
    """Partial room name match: 'kitchen' matches 'Main Kitchen'."""
    from tools.vacuum import clean_rooms

    mock_state = {
        "state": "docked",
        "attributes": {
            "friendly_name": "Dusty",
            "room_list": {"21": "Main Kitchen", "22": "Playroom"},
        },
    }

    with patch(
        "tools.vacuum.read_state",
        new_callable=AsyncMock,
        return_value=mock_state,
    ), patch(
        "tools.vacuum.ha_request",
        new_callable=AsyncMock,
        return_value={},
    ) as mock_ha:
        result = await clean_rooms(
            rooms=["kitchen"], entity_id="vacuum.dusty"
        )

    mock_ha.assert_called_once_with(
        "POST",
        "/services/roborock/vacuum_clean_segment",
        json_data={"entity_id": "vacuum.dusty", "segments": [21]},
    )
    assert "Main Kitchen" in result


@pytest.mark.asyncio
async def test_clean_rooms_no_match_returns_available_list():
    """Returns available room list when no rooms match."""
    from tools.vacuum import clean_rooms

    mock_state = {
        "state": "docked",
        "attributes": {
            "friendly_name": "Dusty",
            "room_list": {"16": "Kitchen", "17": "Living Room"},
        },
    }

    with patch(
        "tools.vacuum.read_state",
        new_callable=AsyncMock,
        return_value=mock_state,
    ), patch(
        "tools.vacuum.ha_request",
        new_callable=AsyncMock,
        return_value={},
    ):
        result = await clean_rooms(
            rooms=["garage"], entity_id="vacuum.dusty"
        )

    assert "garage" in result.lower() or "No rooms matched" in result
    assert "Kitchen" in result
    assert "Living Room" in result


@pytest.mark.asyncio
async def test_clean_rooms_discovers_entity_when_not_provided():
    """When entity_id is omitted, the first vacuum is discovered."""
    from tools.vacuum import clean_rooms

    states_response = [
        {
            "entity_id": "vacuum.auto",
            "state": "docked",
            "attributes": {
                "friendly_name": "Auto Vac",
                "room_list": {"10": "Office"},
            },
        }
    ]
    mock_vac_state = {
        "state": "docked",
        "attributes": {
            "friendly_name": "Auto Vac",
            "room_list": {"10": "Office"},
        },
    }

    async def _mock_ha(method, path, json_data=None):
        if path == "/states":
            return states_response
        # Roborock service call
        return {}

    with patch(
        "tools.vacuum.ha_request",
        side_effect=_mock_ha,
    ), patch(
        "tools.vacuum.read_state",
        new_callable=AsyncMock,
        return_value=mock_vac_state,
    ):
        result = await clean_rooms(rooms=["office"])

    assert "Office" in result


@pytest.mark.asyncio
async def test_clean_rooms_fallback_when_roborock_unavailable():
    """Falls back to control_vacuum start when roborock service fails."""
    from tools.vacuum import clean_rooms

    mock_state = {
        "state": "docked",
        "attributes": {
            "friendly_name": "Dusty",
            "room_list": {"16": "Kitchen"},
        },
    }
    verify_state = {
        "state": "cleaning",
        "attributes": {"friendly_name": "Dusty"},
    }

    call_count = {"n": 0}

    async def _mock_ha(method, path, json_data=None):
        if path == "/services/roborock/vacuum_clean_segment":
            raise Exception("service not found")
        return {}

    with patch(
        "tools.vacuum.read_state",
        new_callable=AsyncMock,
        side_effect=[mock_state, verify_state],
    ), patch(
        "tools.vacuum.ha_request",
        side_effect=_mock_ha,
    ), patch(
        "tools.vacuum.get_battery_level",
        new_callable=AsyncMock,
        return_value=None,
    ), patch(
        "tools.vacuum.call_ha_service",
        new_callable=AsyncMock,
    ):
        result = await clean_rooms(
            rooms=["kitchen"], entity_id="vacuum.dusty"
        )

    assert "unavailable" in result.lower() or "fallback" in result.lower() or "full clean" in result.lower()
