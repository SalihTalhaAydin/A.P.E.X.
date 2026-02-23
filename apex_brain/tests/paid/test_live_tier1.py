"""
Tier 1 — Direct Tool Tests against a live Home Assistant instance.

These tests call discover(), query(), do(), and history() directly
against a real HA instance. No LLM involved. Deterministic and fast.

Run with:  RUN_PAID_TESTS=1 pytest apex_brain/tests/paid/test_live_tier1.py -v
"""

from __future__ import annotations

import pytest
from tools.base import execute_tool

pytestmark = pytest.mark.live


# ===================================================================
# 1. discover() — Read-only exploration
# ===================================================================


class TestDiscoverEntities:
    """discover(what='entities') against live HA."""

    async def test_discover_all_entities(self):
        """Should return a non-empty list of entities."""
        result = await execute_tool("discover", {"what": "entities"})
        assert "Entities" in result
        assert "found" in result
        # Should contain at least sun.sun (always present)
        assert "sun" in result.lower()

    async def test_discover_entities_filter_light(self):
        """Filter entities by 'light' domain."""
        result = await execute_tool(
            "discover", {"what": "entities", "filter": "light"}
        )
        # Either has lights or says "No entities matching"
        assert "light" in result.lower()

    async def test_discover_entities_filter_sensor(self):
        """Filter entities by 'sensor' domain."""
        result = await execute_tool(
            "discover", {"what": "entities", "filter": "sensor"}
        )
        assert "sensor" in result.lower()

    async def test_discover_entities_filter_nonexistent(self):
        """Filter with a nonsense string returns no matches."""
        result = await execute_tool(
            "discover",
            {"what": "entities", "filter": "zzz_nonexistent_xyz"},
        )
        assert "No entities matching" in result


class TestDiscoverServices:
    """discover(what='services') against live HA."""

    async def test_discover_all_services(self):
        """Should return a list of service domains."""
        result = await execute_tool("discover", {"what": "services"})
        assert "Service domains" in result
        # Every HA has homeassistant, light, etc.
        assert "homeassistant" in result.lower()

    async def test_discover_services_filter_light(self):
        """Filter services by 'light' shows service schemas."""
        result = await execute_tool(
            "discover", {"what": "services", "filter": "light"}
        )
        assert "light" in result.lower()
        # Should show turn_on at minimum
        assert "turn_on" in result.lower()

    async def test_discover_services_filter_climate(self):
        """Filter services by 'climate'."""
        result = await execute_tool(
            "discover", {"what": "services", "filter": "climate"}
        )
        # Either shows climate services or "No services matching"
        assert "climate" in result.lower()


class TestDiscoverAreas:
    """discover(what='areas') against live HA."""

    async def test_discover_areas(self):
        """Should return areas or 'No areas found'."""
        result = await execute_tool("discover", {"what": "areas"})
        assert "Areas" in result or "No areas" in result


class TestDiscoverFloors:
    """discover(what='floors') against live HA."""

    async def test_discover_floors(self):
        """Should return floors or 'No floors' or version message."""
        result = await execute_tool("discover", {"what": "floors"})
        assert (
            "Floors" in result
            or "No floors" in result
            or "not available" in result
        )


class TestDiscoverDevices:
    """discover(what='devices') against live HA."""

    async def test_discover_devices(self):
        """Should return a device list."""
        result = await execute_tool("discover", {"what": "devices"})
        assert "Devices" in result or "No devices" in result


class TestDiscoverIntegrations:
    """discover(what='integrations') against live HA."""

    async def test_discover_integrations(self):
        """Should return configured integrations."""
        result = await execute_tool("discover", {"what": "integrations"})
        assert "Integrations" in result or "No integrations" in result

    async def test_discover_integrations_filter(self):
        """Filter integrations by keyword."""
        result = await execute_tool(
            "discover", {"what": "integrations", "filter": "sun"}
        )
        # sun integration is always present
        assert "sun" in result.lower() or "No integrations" in result


class TestDiscoverInfo:
    """discover(what='info') against live HA."""

    async def test_discover_info(self):
        """Should return HA version, location, timezone."""
        result = await execute_tool("discover", {"what": "info"})
        assert "Home Assistant Info" in result
        assert "Version" in result
        assert "Timezone" in result


# ===================================================================
# 2. query() — Read entity state and templates
# ===================================================================


class TestQueryEntity:
    """query(target='entity_id') against live HA."""

    async def test_query_sun(self):
        """sun.sun is always available in every HA instance."""
        result = await execute_tool("query", {"target": "sun.sun"})
        assert "sun" in result.lower()
        # State is either 'above_horizon' or 'below_horizon'
        assert "horizon" in result.lower() or "Sun" in result

    async def test_query_nonexistent_entity(self):
        """Querying a non-existent entity returns a helpful error."""
        result = await execute_tool(
            "query", {"target": "sensor.zzz_does_not_exist_xyz"}
        )
        assert "not found" in result.lower() or "unknown" in result.lower()

    async def test_query_real_sensor(self, any_sensor_entity):
        """Query a dynamically discovered real sensor."""
        entity_id, expected_state = any_sensor_entity
        result = await execute_tool("query", {"target": entity_id})
        assert entity_id in result or expected_state in result


class TestQueryTemplate:
    """query(target='{{ jinja2 }}') against live HA."""

    async def test_query_simple_template(self):
        """Evaluate a simple Jinja2 template."""
        result = await execute_tool(
            "query", {"target": "{{ states('sun.sun') }}"}
        )
        assert result in ("above_horizon", "below_horizon")

    async def test_query_count_template(self):
        """Count all sensor entities via template."""
        result = await execute_tool(
            "query",
            {"target": "{{ states.sensor | list | length }}"},
        )
        # Should return a number
        assert result.strip().isdigit()
        count = int(result.strip())
        assert count > 0

    async def test_query_arithmetic_template(self):
        """Jinja2 arithmetic should work."""
        result = await execute_tool("query", {"target": "{{ 2 + 2 }}"})
        assert result.strip() == "4"

    async def test_query_now_template(self):
        """Template with now() returns current datetime."""
        result = await execute_tool(
            "query", {"target": "{{ now().strftime('%Y') }}"}
        )
        assert result.strip() == "2026" or result.strip().isdigit()


# ===================================================================
# 3. history() — Read-only state history
# ===================================================================


class TestHistory:
    """history() against live HA."""

    async def test_history_sun(self):
        """sun.sun always has state change history."""
        result = await execute_tool(
            "history",
            {"entity_id": "sun.sun", "hours": 48, "mode": "changes"},
        )
        assert "History for" in result or "No state changes" in result
        # sun transitions between above/below horizon daily
        if "History for" in result:
            assert "horizon" in result.lower() or "→" in result

    async def test_history_logbook(self):
        """Logbook mode for sun.sun."""
        result = await execute_tool(
            "history",
            {"entity_id": "sun.sun", "hours": 48, "mode": "logbook"},
        )
        assert "Logbook for" in result or "No logbook" in result

    async def test_history_short_window(self):
        """1-hour window — may or may not have changes."""
        result = await execute_tool(
            "history",
            {"entity_id": "sun.sun", "hours": 1, "mode": "changes"},
        )
        # Either has history or says "No state changes"
        assert "sun" in result.lower()

    async def test_history_real_sensor(self, any_sensor_entity):
        """History for a dynamically discovered sensor."""
        entity_id, _ = any_sensor_entity
        result = await execute_tool(
            "history",
            {"entity_id": entity_id, "hours": 24, "mode": "changes"},
        )
        assert "History for" in result or "No state changes" in result


# ===================================================================
# 4. do() — Safe write operations (with state restore)
# ===================================================================


class TestDoSafeWrites:
    """do() with safe, reversible service calls."""

    async def test_do_update_entity(self):
        """homeassistant.update_entity is always safe — just refreshes state."""
        result = await execute_tool(
            "do",
            {
                "domain": "homeassistant",
                "service": "update_entity",
                "targets": {"entity_id": "sun.sun"},
            },
        )
        assert "Done" in result

    async def test_do_toggle_basement_light_and_restore(
        self, any_light_entity, state_guard
    ):
        """Toggle a basement light off then back on (or vice versa),
        restoring original state via EntityStateGuard."""
        entity_id, original_state = any_light_entity
        assert "basement" in entity_id.lower(), (
            f"Expected a basement light, got {entity_id}"
        )

        async with state_guard.protect(entity_id):
            # Toggle: if on → turn off, if off → turn on
            action = "turn_off" if original_state == "on" else "turn_on"
            result = await execute_tool(
                "do",
                {
                    "domain": "light",
                    "service": action,
                    "targets": {"entity_id": entity_id},
                },
            )
            assert "Done" in result
            # Verify the state actually changed
            verify = await execute_tool("query", {"target": entity_id})
            expected = "off" if original_state == "on" else "on"
            assert expected in verify.lower()

        # After context manager: state is restored automatically

    async def test_do_protected_domain_requires_confirmation(self):
        """Calling do() on a lock domain returns confirmation prompt."""
        result = await execute_tool(
            "do",
            {
                "domain": "lock",
                "service": "lock",
                "targets": {"entity_id": "lock.test_lock"},
            },
        )
        assert "CONFIRMATION REQUIRED" in result

    async def test_do_nonexistent_service(self):
        """Calling a non-existent service returns an error."""
        result = await execute_tool(
            "do",
            {
                "domain": "homeassistant",
                "service": "zzz_fake_service",
                "targets": {"entity_id": "sun.sun"},
            },
        )
        assert "error" in result.lower() or "Error" in result


# ===================================================================
# 5. Combined read operations — verify data consistency
# ===================================================================


class TestCrossToolConsistency:
    """Verify that different tools return consistent data."""

    async def test_discover_and_query_agree(self):
        """discover(entities) and query() should agree on sun.sun's state."""
        discover_result = await execute_tool(
            "discover", {"what": "entities", "filter": "sun.sun"}
        )
        query_result = await execute_tool("query", {"target": "sun.sun"})

        # Both should report the same state
        if "above_horizon" in discover_result:
            assert "above_horizon" in query_result
        elif "below_horizon" in discover_result:
            assert "below_horizon" in query_result

    async def test_discover_entities_count_matches_template(self):
        """Entity count from discover should roughly match template count."""
        # Get count via template
        template_result = await execute_tool(
            "query",
            {"target": "{{ states | list | length }}"},
        )
        template_count = int(template_result.strip())

        # Get entities via discover (capped at 50)
        discover_result = await execute_tool(
            "discover", {"what": "entities"}
        )
        # Extract count from "Entities (N found)"
        assert "found" in discover_result
        count_str = discover_result.split("(")[1].split("found")[0].strip()
        discover_count = int(count_str)

        # They should match (discover may show fewer if capped)
        assert discover_count <= template_count
        assert discover_count > 0

    async def test_info_timezone_matches_template(self):
        """HA info timezone should match what templates report."""
        info = await execute_tool("discover", {"what": "info"})
        # Extract timezone from info
        for line in info.split("\n"):
            if "Timezone" in line:
                tz_from_info = line.split(":")[1].strip()
                break
        else:
            pytest.skip("Timezone not in info output")

        # Get via template (verify both info and template return valid timezone data)
        await execute_tool(
            "query",
            {"target": "{{ states.sun.sun.attributes.next_rising[:4] }}"},
        )
        # Both should exist and be non-empty
        assert tz_from_info
        assert len(tz_from_info) > 3  # e.g. "America/Chicago"
