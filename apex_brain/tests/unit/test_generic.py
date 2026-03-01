"""Tests for generic tools (discover, query, do, history).

Covers:
- Tool registration (present in TOOL_REGISTRY with correct params)
- Normal operation for each tool
- Edge cases (empty results, bad input, missing entities)
- Error handling (HA API failures)
- Security gate for do() on protected domains
- All HA API calls are mocked — no real API calls
"""

from __future__ import annotations

from datetime import timezone
from unittest.mock import AsyncMock, patch

import pytest
from tools import discover_tools
from tools.base import TOOL_REGISTRY


@pytest.fixture(scope="module", autouse=True)
def _tools_loaded():
    """Ensure all tools (including generic) are discovered."""
    discover_tools()


# ==================================================================
# Registration tests
# ==================================================================


class TestRegistration:
    """Verify all four tools are registered with correct schemas."""

    def test_discover_registered(self):
        info = TOOL_REGISTRY.get("discover")
        assert info is not None

    def test_discover_required_params(self):
        required = TOOL_REGISTRY["discover"]["parameters"]["required"]
        assert "what" in required

    def test_discover_what_enum(self):
        enum = TOOL_REGISTRY["discover"]["parameters"]["properties"][
            "what"
        ]["enum"]
        assert set(enum) == {
            "entities",
            "services",
            "areas",
            "floors",
            "devices",
            "integrations",
            "info",
        }

    def test_query_registered(self):
        info = TOOL_REGISTRY.get("query")
        assert info is not None

    def test_query_required_params(self):
        required = TOOL_REGISTRY["query"]["parameters"]["required"]
        assert "target" in required

    def test_do_registered(self):
        info = TOOL_REGISTRY.get("do")
        assert info is not None

    def test_do_required_params(self):
        required = TOOL_REGISTRY["do"]["parameters"]["required"]
        assert "domain" in required
        assert "service" in required

    def test_do_has_targets_and_data(self):
        props = TOOL_REGISTRY["do"]["parameters"]["properties"]
        assert "targets" in props
        assert "data" in props

    def test_history_registered(self):
        info = TOOL_REGISTRY.get("history")
        assert info is not None

    def test_history_required_params(self):
        required = TOOL_REGISTRY["history"]["parameters"]["required"]
        assert "entity_id" in required

    def test_history_mode_enum(self):
        enum = TOOL_REGISTRY["history"]["parameters"]["properties"][
            "mode"
        ]["enum"]
        assert set(enum) == {"changes", "logbook"}


# ==================================================================
# discover() tests
# ==================================================================


class TestDiscover:
    """Tests for discover() tool."""

    async def test_entities_no_filter(self):
        from tools.generic import discover

        states = [
            {
                "entity_id": "light.kitchen",
                "state": "on",
                "attributes": {"friendly_name": "Kitchen Light"},
            },
            {
                "entity_id": "sensor.temp",
                "state": "72",
                "attributes": {"friendly_name": "Temperature"},
            },
        ]
        with patch(
            "tools.generic.ha_request",
            new_callable=AsyncMock,
            return_value=states,
        ):
            result = await discover(what="entities")

        assert "light.kitchen" in result
        assert "sensor.temp" in result
        assert "Kitchen Light" in result
        assert "2 found" in result

    async def test_entities_with_domain_filter(self):
        from tools.generic import discover

        states = [
            {
                "entity_id": "light.kitchen",
                "state": "on",
                "attributes": {"friendly_name": "Kitchen Light"},
            },
            {
                "entity_id": "sensor.temp",
                "state": "72",
                "attributes": {"friendly_name": "Temperature"},
            },
        ]
        with patch(
            "tools.generic.ha_request",
            new_callable=AsyncMock,
            return_value=states,
        ):
            result = await discover(what="entities", filter_str="light")

        assert "light.kitchen" in result
        assert "sensor.temp" not in result

    async def test_entities_with_name_filter(self):
        from tools.generic import discover

        states = [
            {
                "entity_id": "light.kitchen",
                "state": "on",
                "attributes": {"friendly_name": "Kitchen Light"},
            },
            {
                "entity_id": "light.bedroom",
                "state": "off",
                "attributes": {"friendly_name": "Bedroom Light"},
            },
        ]
        with patch(
            "tools.generic.ha_request",
            new_callable=AsyncMock,
            return_value=states,
        ):
            result = await discover(what="entities", filter_str="kitchen")

        assert "light.kitchen" in result
        assert "light.bedroom" not in result

    async def test_entities_no_match(self):
        from tools.generic import discover

        states = [
            {
                "entity_id": "light.kitchen",
                "state": "on",
                "attributes": {},
            },
        ]
        with patch(
            "tools.generic.ha_request",
            new_callable=AsyncMock,
            return_value=states,
        ):
            result = await discover(what="entities", filter_str="garage")

        assert "No entities matching" in result

    async def test_entities_handles_ha_request_error(self):
        """discover(what='entities') surfaces HA errors clearly (BUG-39)."""
        from tools.ha_helpers import HomeAssistantError
        from tools.generic import discover

        with patch(
            "tools.generic.ha_request",
            new_callable=AsyncMock,
            side_effect=HomeAssistantError("HA API error 503: Service Unavailable"),
        ):
            result = await discover(what="entities")

        assert "connection error" in result.lower() or "503" in result

    async def test_entities_caps_at_50(self):
        from tools.generic import discover

        states = [
            {
                "entity_id": f"sensor.item_{i}",
                "state": str(i),
                "attributes": {"friendly_name": f"Item {i}"},
            }
            for i in range(60)
        ]
        with patch(
            "tools.generic.ha_request",
            new_callable=AsyncMock,
            return_value=states,
        ):
            result = await discover(what="entities")

        assert "60 found" in result
        assert "showing first 50" in result
        # Only 50 entity lines
        entity_lines = [
            l for l in result.splitlines() if "sensor.item_" in l
        ]
        assert len(entity_lines) == 50

    async def test_services_no_filter_lists_domains(self):
        from tools.generic import discover

        services = [
            {"domain": "light", "services": {}},
            {"domain": "climate", "services": {}},
            {"domain": "switch", "services": {}},
        ]
        with patch(
            "tools.generic.ha_request",
            new_callable=AsyncMock,
            return_value=services,
        ):
            result = await discover(what="services")

        assert "Service domains" in result
        assert "light" in result
        assert "climate" in result

    async def test_services_with_filter_shows_schemas(self):
        from tools.generic import discover

        services = [
            {
                "domain": "light",
                "services": {
                    "turn_on": {
                        "description": "Turn on a light",
                        "fields": {
                            "brightness_pct": {
                                "description": "Brightness percentage",
                                "selector": {
                                    "number": {
                                        "min": 0,
                                        "max": 100,
                                    }
                                },
                            },
                        },
                    },
                    "turn_off": {
                        "description": "Turn off a light",
                        "fields": {},
                    },
                },
            },
        ]
        with patch(
            "tools.generic.ha_request",
            new_callable=AsyncMock,
            return_value=services,
        ):
            result = await discover(what="services", filter_str="light")

        assert "light.turn_on" in result
        assert "light.turn_off" in result
        assert "brightness_pct" in result

    async def test_services_no_match(self):
        from tools.generic import discover

        services = [
            {"domain": "light", "services": {}},
        ]
        with patch(
            "tools.generic.ha_request",
            new_callable=AsyncMock,
            return_value=services,
        ):
            result = await discover(what="services", filter_str="vacuum")

        assert "No services matching" in result

    async def test_areas(self):
        from tools.generic import discover

        with patch(
            "tools.generic.ha_request",
            new_callable=AsyncMock,
            return_value="kitchen|Kitchen\nbedroom|Bedroom\n",
        ):
            result = await discover(what="areas")

        assert "Kitchen" in result
        assert "Bedroom" in result
        assert "2" in result

    async def test_areas_with_filter(self):
        from tools.generic import discover

        with patch(
            "tools.generic.ha_request",
            new_callable=AsyncMock,
            return_value="kitchen|Kitchen\nbedroom|Bedroom\n",
        ):
            result = await discover(what="areas", filter_str="kitchen")

        assert "Kitchen" in result
        assert "Bedroom" not in result

    async def test_areas_empty(self):
        from tools.generic import discover

        with patch(
            "tools.generic.ha_request",
            new_callable=AsyncMock,
            return_value="",
        ):
            result = await discover(what="areas")

        assert "No areas found" in result

    async def test_info(self):
        from tools.generic import discover

        config = {
            "version": "2024.1.0",
            "location_name": "My Home",
            "time_zone": "America/Chicago",
            "unit_system": {"temperature": "°F"},
            "elevation": 100,
            "latitude": 30.0,
            "longitude": -97.0,
        }
        with patch(
            "tools.generic.ha_request",
            new_callable=AsyncMock,
            return_value=config,
        ):
            result = await discover(what="info")

        assert "2024.1.0" in result
        assert "My Home" in result
        assert "America/Chicago" in result

    async def test_integrations(self):
        from tools.generic import discover

        entries = [
            {
                "domain": "zha",
                "title": "Zigbee HA",
                "state": "loaded",
            },
            {
                "domain": "mqtt",
                "title": "MQTT",
                "state": "loaded",
            },
        ]
        with patch(
            "tools.generic.ha_request",
            new_callable=AsyncMock,
            return_value=entries,
        ):
            result = await discover(what="integrations")

        assert "zha" in result
        assert "MQTT" in result

    async def test_unknown_what(self):
        from tools.generic import discover

        result = await discover(what="foobar")

        assert "Unknown discover target" in result

    async def test_api_error_handled(self):
        from tools.generic import discover

        with patch(
            "tools.generic.ha_request",
            new_callable=AsyncMock,
            side_effect=Exception("Connection refused"),
        ):
            result = await discover(what="entities")

        assert "Error" in result

    async def test_devices(self):
        from tools.generic import discover

        template_result = (
            "light.kitchen|Kitchen Light|on\nsensor.temp|Temperature|72\n"
        )
        with patch(
            "tools.generic.ha_request",
            new_callable=AsyncMock,
            return_value=template_result,
        ):
            result = await discover(what="devices")

        assert "Kitchen Light" in result
        assert "Temperature" in result

    async def test_devices_with_filter(self):
        from tools.generic import discover

        template_result = (
            "light.kitchen|Kitchen Light|on\n"
            "light.bedroom|Bedroom Light|off\n"
        )
        with patch(
            "tools.generic.ha_request",
            new_callable=AsyncMock,
            return_value=template_result,
        ):
            result = await discover(what="devices", filter_str="kitchen")

        assert "Kitchen Light" in result
        assert "Bedroom Light" not in result

    async def test_floors(self):
        from tools.generic import discover

        floor_response = (
            "floor_1|First Floor|kitchen,living_room\n"
            "floor_2|Basement|basement\n"
        )
        with patch(
            "tools.generic.ha_request",
            new_callable=AsyncMock,
            return_value=floor_response,
        ):
            result = await discover(what="floors")

        assert "First Floor" in result
        assert "Basement" in result
        assert "2" in result

    async def test_floors_with_filter(self):
        from tools.generic import discover

        floor_response = (
            "floor_1|First Floor|kitchen,living_room\n"
            "floor_2|Basement|basement\n"
        )
        with patch(
            "tools.generic.ha_request",
            new_callable=AsyncMock,
            return_value=floor_response,
        ):
            result = await discover(what="floors", filter_str="basement")

        assert "Basement" in result
        assert "First Floor" not in result

    async def test_floors_empty(self):
        from tools.generic import discover

        with patch(
            "tools.generic.ha_request",
            new_callable=AsyncMock,
            return_value="",
        ):
            result = await discover(what="floors")

        assert "No floors found" in result

    async def test_floors_not_supported(self):
        from tools.generic import discover

        with patch(
            "tools.generic.ha_request",
            new_callable=AsyncMock,
            side_effect=Exception("Template error"),
        ):
            result = await discover(what="floors")

        assert "not available" in result.lower()


# ==================================================================
# query() tests
# ==================================================================


class TestQuery:
    """Tests for query() tool."""

    async def test_entity_query(self):
        from tools.generic import query

        state = {
            "entity_id": "light.kitchen",
            "state": "on",
            "attributes": {
                "friendly_name": "Kitchen Light",
                "brightness": 255,
                "color_temp_kelvin": 4000,
            },
        }
        with patch(
            "tools.generic.read_state",
            new_callable=AsyncMock,
            return_value=state,
        ):
            result = await query(target="light.kitchen")

        assert "Kitchen Light" in result
        assert "on" in result
        assert "brightness: 100%" in result
        assert "color_temp: 4000K" in result

    async def test_climate_query_shows_temps(self):
        from tools.generic import query

        state = {
            "entity_id": "climate.living_room",
            "state": "heat",
            "attributes": {
                "friendly_name": "Living Room",
                "temperature": 72,
                "current_temperature": 68,
                "hvac_action": "heating",
            },
        }
        with patch(
            "tools.generic.read_state",
            new_callable=AsyncMock,
            return_value=state,
        ):
            result = await query(target="climate.living_room")

        assert "heat" in result
        assert "target: 72" in result
        assert "current: 68" in result
        assert "heating" in result

    async def test_media_player_query(self):
        from tools.generic import query

        state = {
            "entity_id": "media_player.tv",
            "state": "playing",
            "attributes": {
                "friendly_name": "TV",
                "media_title": "Movie Night",
                "volume_level": 0.5,
                "source": "HDMI 1",
            },
        }
        with patch(
            "tools.generic.read_state",
            new_callable=AsyncMock,
            return_value=state,
        ):
            result = await query(target="media_player.tv")

        assert "playing" in result
        assert "Movie Night" in result
        assert "volume: 50%" in result
        assert "HDMI 1" in result

    async def test_template_query(self):
        from tools.generic import query

        with patch(
            "tools.generic.ha_request",
            new_callable=AsyncMock,
            return_value="72°F",
        ):
            result = await query(target='{{ states("sensor.temp") }}°F')

        assert "72°F" in result

    async def test_template_with_for_loop(self):
        from tools.generic import query

        template = (
            "{% for e in states.light "
            "if e.state == 'on' %}"
            "{{ e.name }}\n{% endfor %}"
        )
        with patch(
            "tools.generic.ha_request",
            new_callable=AsyncMock,
            return_value="Kitchen\nBedroom\n",
        ):
            result = await query(target=template)

        assert "Kitchen" in result
        assert "Bedroom" in result

    async def test_entity_not_found_fallback_to_template(
        self,
    ):
        from tools.ha_helpers import HomeAssistantError
        from tools.generic import query

        async def mock_read_state(eid):
            raise HomeAssistantError("404 Not Found")

        with patch(
            "tools.generic.read_state",
            side_effect=mock_read_state,
        ):
            with patch(
                "tools.generic.ha_request",
                new_callable=AsyncMock,
                return_value="on",
            ):
                result = await query(target="light.kitchen")

        assert "light.kitchen" in result
        assert "on" in result

    async def test_entity_not_found_no_fallback(self):
        from tools.generic import query

        async def mock_read_state(eid):
            raise Exception("404 Not Found")

        with patch(
            "tools.generic.read_state",
            side_effect=mock_read_state,
        ):
            with patch(
                "tools.generic.ha_request",
                new_callable=AsyncMock,
                side_effect=Exception("also failed"),
            ):
                result = await query(target="light.nonexistent")

        assert "not found" in result.lower()

    async def test_invalid_target(self):
        from tools.generic import query

        result = await query(target="just_a_word")

        assert "Cannot query" in result

    async def test_vacuum_query_shows_attrs(self):
        from tools.generic import query

        state = {
            "entity_id": "vacuum.dusty",
            "state": "docked",
            "attributes": {
                "friendly_name": "Dusty",
                "battery_level": 95,
                "fan_speed": "turbo",
            },
        }
        with patch(
            "tools.generic.read_state",
            new_callable=AsyncMock,
            return_value=state,
        ):
            result = await query(target="vacuum.dusty")

        assert "docked" in result
        assert "battery: 95%" in result
        assert "fan_speed: turbo" in result

    async def test_sensor_query_shows_unit(self):
        from tools.generic import query

        state = {
            "entity_id": "sensor.outdoor_temp",
            "state": "72.5",
            "attributes": {
                "friendly_name": "Outdoor Temp",
                "unit_of_measurement": "°F",
                "device_class": "temperature",
            },
        }
        with patch(
            "tools.generic.read_state",
            new_callable=AsyncMock,
            return_value=state,
        ):
            result = await query(target="sensor.outdoor_temp")

        assert "72.5" in result
        assert "unit: °F" in result

    async def test_cover_query_shows_position(self):
        from tools.generic import query

        state = {
            "entity_id": "cover.garage",
            "state": "open",
            "attributes": {
                "friendly_name": "Garage Door",
                "current_position": 75,
            },
        }
        with patch(
            "tools.generic.read_state",
            new_callable=AsyncMock,
            return_value=state,
        ):
            result = await query(target="cover.garage")

        assert "open" in result
        assert "position: 75%" in result


# ==================================================================
# do() tests
# ==================================================================


class TestDo:
    """Tests for do() tool."""

    async def test_simple_service_call(self):
        from tools.generic import do

        with patch(
            "tools.generic.ha_request",
            new_callable=AsyncMock,
            return_value={},
        ):
            with patch(
                "tools.generic.verify_generic",
                new_callable=AsyncMock,
                return_value="Kitchen Light: on",
            ):
                with patch("asyncio.sleep", new_callable=AsyncMock):
                    result = await do(
                        domain="light",
                        service="turn_on",
                        targets={"entity_id": "light.kitchen"},
                    )

        assert "Done" in result
        assert "Kitchen Light: on" in result

    async def test_service_call_with_data(self):
        from tools.generic import do

        captured = {}

        async def mock_ha_request(method, path, json_data=None, **kw):
            if "/services/" in path:
                captured.update(json_data or {})
            return {}

        with patch(
            "tools.generic.ha_request",
            side_effect=mock_ha_request,
        ):
            with patch(
                "tools.generic.verify_generic",
                new_callable=AsyncMock,
                return_value="Kitchen Light: on",
            ):
                with patch("asyncio.sleep", new_callable=AsyncMock):
                    result = await do(
                        domain="light",
                        service="turn_on",
                        targets={"entity_id": "light.kitchen"},
                        data={"brightness_pct": 50},
                    )

        assert "Done" in result
        assert captured.get("brightness_pct") == 50
        assert captured.get("entity_id") == "light.kitchen"

    async def test_service_call_area_target(self):
        from tools.generic import do

        captured = {}

        async def mock_ha_request(method, path, json_data=None, **kw):
            if "/services/" in path:
                captured.update(json_data or {})
                return {}
            # Template call for verification
            return (
                "light.kitchen_ceiling|on|"
                "Kitchen Ceiling\n"
                "light.kitchen_lamp|on|"
                "Kitchen Lamp\n"
            )

        with patch(
            "tools.generic.ha_request",
            side_effect=mock_ha_request,
        ):
            with patch(
                "asyncio.sleep",
                new_callable=AsyncMock,
            ):
                result = await do(
                    domain="light",
                    service="turn_on",
                    targets={"area_id": "kitchen"},
                )

        assert "Done" in result
        assert captured.get("area_id") == "kitchen"
        assert "entity_id" not in captured
        # Concise verification: count-based summary
        assert "2" in result
        assert "kitchen" in result

    async def test_service_call_area_target_empty(self):
        """Area call with no entities in area."""
        from tools.generic import do

        async def mock_ha_request(method, path, json_data=None, **kw):
            if "/services/" in path:
                return {}
            # Template returns empty (no entities)
            return ""

        with patch(
            "tools.generic.ha_request",
            side_effect=mock_ha_request,
        ):
            with patch(
                "asyncio.sleep",
                new_callable=AsyncMock,
            ):
                result = await do(
                    domain="light",
                    service="turn_on",
                    targets={"area_id": "garage"},
                )

        assert "Done" in result
        assert "no light entities" in result.lower()

    async def test_service_call_floor_target(self):
        """Floor-based targeting verifies entities."""
        from tools.generic import do

        captured = {}

        async def mock_ha_request(method, path, json_data=None, **kw):
            if "/services/" in path:
                captured.update(json_data or {})
                return {}
            return (
                "light.basement_ceiling|on|"
                "Basement Ceiling\n"
                "light.basement_lamp|on|"
                "Basement Lamp\n"
            )

        with patch(
            "tools.generic.ha_request",
            side_effect=mock_ha_request,
        ):
            with patch(
                "asyncio.sleep",
                new_callable=AsyncMock,
            ):
                result = await do(
                    domain="light",
                    service="turn_on",
                    targets={"floor_id": "floor_basement"},
                )

        assert "Done" in result
        assert captured.get("floor_id") == ("floor_basement")
        # Concise verification: count-based summary
        assert "2" in result
        assert "floor_basement" in result

    async def test_no_targets_no_data(self):
        from tools.generic import do

        with patch(
            "tools.generic.ha_request",
            new_callable=AsyncMock,
            return_value={},
        ):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                result = await do(
                    domain="script",
                    service="morning_routine",
                )

        assert "Done" in result
        assert "script.morning_routine" in result

    async def test_protected_domain_lock_blocked(self):
        from tools.generic import do

        result = await do(
            domain="lock",
            service="unlock",
            targets={"entity_id": "lock.front_door"},
        )

        assert "CONFIRMATION REQUIRED" in result
        assert "lock.unlock" in result
        assert "lock.front_door" in result

    async def test_protected_domain_alarm_blocked(self):
        from tools.generic import do

        result = await do(
            domain="alarm_control_panel",
            service="alarm_disarm",
            targets={"entity_id": "alarm_control_panel.home"},
        )

        assert "CONFIRMATION REQUIRED" in result

    async def test_protected_domain_cover_blocked(self):
        from tools.generic import do

        result = await do(
            domain="cover",
            service="open_cover",
            targets={"entity_id": "cover.garage"},
        )

        assert "CONFIRMATION REQUIRED" in result

    async def test_protected_domain_camera_blocked(self):
        from tools.generic import do

        result = await do(
            domain="camera",
            service="turn_off",
            targets={"entity_id": "camera.front_porch"},
        )

        assert "CONFIRMATION REQUIRED" in result

    async def test_confirmation_bypass_without_token_fails(self):
        """Bypass attempt: confirmed=true without valid token returns CONFIRMATION REQUIRED."""
        from tools.generic import do

        result = await do(
            domain="lock",
            service="unlock",
            targets={"entity_id": "lock.front_door"},
            data={"confirmed": True},
        )

        assert "CONFIRMATION REQUIRED" in result
        assert "confirmation_token:" in result

    async def test_confirmation_valid_token_succeeds(self):
        """Valid token from first call allows second call to succeed."""
        from tools.generic import do

        captured = {}

        async def mock_ha_request(method, path, json_data=None, **kw):
            if "/services/" in path:
                captured.update(json_data or {})
            return {}

        result1 = await do(
            domain="alarm_control_panel",
            service="alarm_disarm",
            targets={"entity_id": "alarm_control_panel.home"},
        )
        assert "CONFIRMATION REQUIRED" in result1
        token = result1.split("confirmation_token:")[-1].strip().split()[0]

        with patch(
            "tools.generic.ha_request", side_effect=mock_ha_request
        ):
            with patch(
                "tools.generic.verify_generic",
                new_callable=AsyncMock,
                return_value="Home: disarmed",
            ):
                with patch("asyncio.sleep", new_callable=AsyncMock):
                    result2 = await do(
                        domain="alarm_control_panel",
                        service="alarm_disarm",
                        targets={"entity_id": "alarm_control_panel.home"},
                        data={
                            "confirmed": True,
                            "confirmation_token": token,
                        },
                    )

        assert "Done" in result2
        assert "disarmed" in result2
        assert "confirmation_token" not in captured

    async def test_confirmation_expired_token_fails(self):
        """Expired confirmation token returns CONFIRMATION REQUIRED again."""
        from datetime import datetime, timedelta

        from tools.generic import do

        # First call to get a token
        result1 = await do(
            domain="lock",
            service="unlock",
            targets={"entity_id": "lock.safe"},
        )
        assert "CONFIRMATION REQUIRED" in result1
        token = result1.split("confirmation_token:")[-1].strip().split()[0]

        # Expire the token by setting its expiry to the past
        import tools.generic as generic_module

        generic_module._pending_confirmations[token] = datetime.now(
            timezone.utc
        ) - timedelta(seconds=1)

        # Second call with expired token should fail
        result2 = await do(
            domain="lock",
            service="unlock",
            targets={"entity_id": "lock.safe"},
            data={"confirmed": True, "confirmation_token": token},
        )

        assert "CONFIRMATION REQUIRED" in result2

    async def test_protected_domain_confirmed(self):
        """Valid two-step flow: first call returns token, second with token succeeds."""
        from tools.generic import do

        captured = {}

        async def mock_ha_request(method, path, json_data=None, **kw):
            if "/services/" in path:
                captured.update(json_data or {})
            return {}

        # First call: get confirmation token
        result1 = await do(
            domain="lock",
            service="unlock",
            targets={"entity_id": "lock.front_door"},
        )
        assert "CONFIRMATION REQUIRED" in result1
        assert "confirmation_token:" in result1
        token = result1.split("confirmation_token:")[-1].strip().split()[0]

        # Second call with valid token
        with patch(
            "tools.generic.ha_request",
            side_effect=mock_ha_request,
        ):
            with patch(
                "tools.generic.verify_generic",
                new_callable=AsyncMock,
                return_value="Front Door: unlocked",
            ):
                with patch("asyncio.sleep", new_callable=AsyncMock):
                    result2 = await do(
                        domain="lock",
                        service="unlock",
                        targets={"entity_id": "lock.front_door"},
                        data={
                            "confirmed": True,
                            "confirmation_token": token,
                        },
                    )

        assert "Done" in result2
        assert "unlocked" in result2
        assert "confirmed" not in captured
        assert "confirmation_token" not in captured

    async def test_api_error_handled(self):
        from tools.generic import do

        with patch(
            "tools.generic.ha_request",
            new_callable=AsyncMock,
            side_effect=Exception("Connection refused"),
        ):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                result = await do(
                    domain="light",
                    service="turn_on",
                    targets={"entity_id": "light.kitchen"},
                )

        assert "Error" in result or "error" in result

    async def test_confirmed_data_preserved(self):
        """When confirmed + extra data, extra data is kept."""
        from tools.generic import do

        captured = {}

        async def mock_ha_request(method, path, json_data=None, **kw):
            if "/services/" in path:
                captured.update(json_data or {})
            return {}

        # First call: get token
        result1 = await do(
            domain="cover",
            service="open_cover",
            targets={"entity_id": "cover.garage"},
        )
        assert "CONFIRMATION REQUIRED" in result1
        token = result1.split("confirmation_token:")[-1].strip().split()[0]

        with patch(
            "tools.generic.ha_request",
            side_effect=mock_ha_request,
        ):
            with patch(
                "tools.generic.verify_generic",
                new_callable=AsyncMock,
                return_value="Garage: open",
            ):
                with patch("asyncio.sleep", new_callable=AsyncMock):
                    result = await do(
                        domain="cover",
                        service="open_cover",
                        targets={"entity_id": "cover.garage"},
                        data={
                            "confirmed": True,
                            "confirmation_token": token,
                            "position": 50,
                        },
                    )

        assert "Done" in result
        assert captured.get("position") == 50
        assert "confirmed" not in captured
        assert "confirmation_token" not in captured


# ==================================================================
# history() tests
# ==================================================================


class TestHistory:
    """Tests for history() tool."""

    async def test_changes_mode(self):
        from tools.generic import history

        ha_response = [
            [
                {
                    "state": "off",
                    "last_changed": "2024-01-15T08:00:00+00:00",
                },
                {
                    "state": "on",
                    "last_changed": "2024-01-15T09:30:00+00:00",
                },
                {
                    "state": "off",
                    "last_changed": "2024-01-15T22:00:00+00:00",
                },
            ]
        ]
        with patch(
            "tools.generic.ha_request",
            new_callable=AsyncMock,
            return_value=ha_response,
        ):
            result = await history(
                entity_id="light.kitchen",
                hours=24,
                mode="changes",
            )

        assert "light.kitchen" in result
        assert "off" in result
        assert "on" in result
        # Should show transitions
        assert "→" in result

    async def test_changes_no_data(self):
        from tools.generic import history

        with patch(
            "tools.generic.ha_request",
            new_callable=AsyncMock,
            return_value=[],
        ):
            result = await history(
                entity_id="light.kitchen",
                hours=24,
                mode="changes",
            )

        assert "No state changes" in result

    async def test_changes_empty_inner_list(self):
        from tools.generic import history

        with patch(
            "tools.generic.ha_request",
            new_callable=AsyncMock,
            return_value=[[]],
        ):
            result = await history(
                entity_id="light.kitchen",
                hours=24,
                mode="changes",
            )

        assert "No state changes" in result

    async def test_logbook_mode(self):
        from tools.generic import history

        ha_response = [
            {
                "name": "Kitchen Light",
                "message": "turned on",
                "when": "2024-01-15T09:30:00+00:00",
            },
            {
                "name": "Kitchen Light",
                "state": "off",
                "when": "2024-01-15T22:00:00+00:00",
            },
        ]
        with patch(
            "tools.generic.ha_request",
            new_callable=AsyncMock,
            return_value=ha_response,
        ):
            result = await history(
                entity_id="light.kitchen",
                hours=24,
                mode="logbook",
            )

        assert "Logbook" in result
        assert "Kitchen Light" in result
        assert "turned on" in result

    async def test_logbook_no_data(self):
        from tools.generic import history

        with patch(
            "tools.generic.ha_request",
            new_callable=AsyncMock,
            return_value=[],
        ):
            result = await history(
                entity_id="light.kitchen",
                hours=24,
                mode="logbook",
            )

        assert "No logbook entries" in result

    async def test_logbook_caps_at_50(self):
        from tools.generic import history

        ha_response = [
            {
                "name": f"Event {i}",
                "message": f"action {i}",
                "when": "2024-01-15T09:30:00+00:00",
            }
            for i in range(60)
        ]
        with patch(
            "tools.generic.ha_request",
            new_callable=AsyncMock,
            return_value=ha_response,
        ):
            result = await history(
                entity_id="sensor.test",
                hours=24,
                mode="logbook",
            )

        assert "50 of 60" in result

    async def test_custom_hours(self):
        from tools.generic import history

        captured_path = []

        async def mock_ha_request(method, path, json_data=None, **kw):
            captured_path.append(path)
            return [[]]

        with patch(
            "tools.generic.ha_request",
            side_effect=mock_ha_request,
        ):
            await history(
                entity_id="light.kitchen",
                hours=48,
                mode="changes",
            )

        assert len(captured_path) == 1
        assert "light.kitchen" in captured_path[0]

    async def test_api_error_handled(self):
        from tools.generic import history

        with patch(
            "tools.generic.ha_request",
            new_callable=AsyncMock,
            side_effect=Exception("Connection refused"),
        ):
            result = await history(entity_id="light.kitchen")

        assert "Error" in result

    async def test_default_mode_is_changes(self):
        from tools.generic import history

        captured_path = []

        async def mock_ha_request(method, path, json_data=None, **kw):
            captured_path.append(path)
            return [[]]

        with patch(
            "tools.generic.ha_request",
            side_effect=mock_ha_request,
        ):
            await history(entity_id="light.kitchen")

        # Should use history/period endpoint, not logbook
        assert any("/history/period" in p for p in captured_path)

    async def test_dedup_consecutive_same_state(self):
        """Consecutive identical states are deduplicated."""
        from tools.generic import history

        ha_response = [
            [
                {
                    "state": "on",
                    "last_changed": "2024-01-15T08:00:00+00:00",
                },
                {
                    "state": "on",
                    "last_changed": "2024-01-15T08:00:01+00:00",
                },
                {
                    "state": "off",
                    "last_changed": "2024-01-15T09:00:00+00:00",
                },
            ]
        ]
        with patch(
            "tools.generic.ha_request",
            new_callable=AsyncMock,
            return_value=ha_response,
        ):
            result = await history(
                entity_id="light.kitchen",
                hours=24,
                mode="changes",
            )

        # Should show only 2 entries (on, on→off),
        # not 3
        change_lines = [
            l
            for l in result.splitlines()
            if ":" in l and ("→" in l or "on" in l)
        ]
        # First line is "on", second is "on → off"
        assert len(change_lines) == 2


# ==================================================================
# Helper function tests
# ==================================================================


class TestHelpers:
    """Tests for internal helper functions."""

    def test_is_template_double_braces(self):
        from tools.generic import _is_template

        assert _is_template('{{ states("sensor.temp") }}')

    def test_is_template_block(self):
        from tools.generic import _is_template

        assert _is_template(
            "{% for e in states.light %}{{ e.name }}{% endfor %}"
        )

    def test_is_template_plain_entity(self):
        from tools.generic import _is_template

        assert not _is_template("light.kitchen")

    def test_is_template_plain_text(self):
        from tools.generic import _is_template

        assert not _is_template("hello world")

    def test_format_domain_attrs_light(self):
        from tools.generic import _format_domain_attrs

        result = _format_domain_attrs(
            "light",
            {"brightness": 128, "color_temp_kelvin": 3000},
        )
        assert "brightness: 50%" in result
        assert "color_temp: 3000K" in result

    def test_format_domain_attrs_climate(self):
        from tools.generic import _format_domain_attrs

        result = _format_domain_attrs(
            "climate",
            {
                "temperature": 72,
                "current_temperature": 68,
                "hvac_action": "heating",
            },
        )
        assert "target: 72" in result
        assert "current: 68" in result
        assert "heating" in result

    def test_format_domain_attrs_empty(self):
        from tools.generic import _format_domain_attrs

        result = _format_domain_attrs("light", {})
        assert result == ""

    def test_selector_to_type_number(self):
        from tools.generic import _selector_to_type

        result = _selector_to_type({"number": {"min": 0, "max": 100}})
        assert "number" in result
        assert "0" in result
        assert "100" in result

    def test_selector_to_type_boolean(self):
        from tools.generic import _selector_to_type

        result = _selector_to_type({"boolean": None})
        assert result == "boolean"

    def test_selector_to_type_entity(self):
        from tools.generic import _selector_to_type

        result = _selector_to_type({"entity": {"domain": "light"}})
        assert "entity" in result
        assert "light" in result

    def test_selector_to_type_empty(self):
        from tools.generic import _selector_to_type

        result = _selector_to_type({})
        assert result == "any"

    def test_format_timestamp_iso(self):
        from tools.generic import _format_timestamp

        result = _format_timestamp("2024-01-15T09:30:45+00:00")
        assert "09:30:45" in result

    def test_format_timestamp_empty(self):
        from tools.generic import _format_timestamp

        result = _format_timestamp("")
        assert result == "?"

    def test_format_timestamp_z_suffix(self):
        from tools.generic import _format_timestamp

        result = _format_timestamp("2024-01-15T09:30:45Z")
        assert "09:30:45" in result

    def test_protected_domains_set(self):
        from tools.generic import PROTECTED_DOMAINS

        assert "lock" in PROTECTED_DOMAINS
        assert "alarm_control_panel" in PROTECTED_DOMAINS
        assert "camera" in PROTECTED_DOMAINS
        assert "cover" in PROTECTED_DOMAINS
        assert "light" not in PROTECTED_DOMAINS
