"""
Energy monitoring tools for Home Assistant.
Query power (W/kW) and energy (Wh/kWh) sensors to provide
summaries of household energy consumption, solar generation, etc.

DEPRECATED: get_entity_power is a thin wrapper that delegates to the
generic query() tool. get_energy_entities and get_energy_summary keep
their existing implementations (complex logic with no direct generic
equivalent).
"""

from __future__ import annotations

import logging

import httpx

from tools.base import tool
from tools.generic import query
from tools.ha_helpers import (
    format_ha_error,
    ha_request,
)

logger = logging.getLogger(__name__)

# Device classes and units that indicate energy-related sensors
_ENERGY_DEVICE_CLASSES = {"energy", "power"}
_ENERGY_UNITS = {"w", "kw", "wh", "kwh"}

# Patterns in entity_id that suggest energy sensors
_ENERGY_ID_PATTERNS = (
    "energy",
    "power",
    "consumption",
    "generation",
    "solar",
    "grid",
    "battery_power",
)


def _is_energy_entity(entity: dict) -> bool:
    """Check if an entity is energy-related by device_class, unit, or name."""
    attrs = entity.get("attributes", {})
    device_class = (
        attrs.get("device_class", "") or ""
    ).lower()
    unit = (
        attrs.get("unit_of_measurement", "") or ""
    ).lower()
    eid = entity.get("entity_id", "").lower()

    if device_class in _ENERGY_DEVICE_CLASSES:
        return True
    if unit in _ENERGY_UNITS:
        return True
    if any(pat in eid for pat in _ENERGY_ID_PATTERNS):
        return True
    return False


def _format_reading(entity: dict) -> str:
    """Format a single energy entity into a readable line."""
    attrs = entity.get("attributes", {})
    name = attrs.get(
        "friendly_name", entity["entity_id"]
    )
    state = entity.get("state", "unknown")
    unit = attrs.get("unit_of_measurement", "")
    eid = entity["entity_id"]

    if state in ("unavailable", "unknown"):
        return f"- {name} ({eid}): {state}"
    return f"- {name} ({eid}): {state} {unit}".rstrip()


def _categorize_power_reading(p: dict) -> str:
    """Return category for power reading: generating, from_grid, exporting, consumption."""
    eid_lower = p["entity_id"].lower()
    name_lower = p["name"].lower()
    if any(
        kw in eid_lower or kw in name_lower
        for kw in ("solar", "pv", "generat")
    ):
        return "generating"
    if any(
        kw in eid_lower or kw in name_lower
        for kw in ("grid", "import", "mains")
    ):
        return "from_grid"
    if any(
        kw in eid_lower or kw in name_lower
        for kw in ("export", "feed")
    ):
        return "exporting"
    return "consumption"


def _fmt_w(val_w: float) -> str:
    """Format watts as kW or W string."""
    if abs(val_w) >= 1000:
        return f"{round(val_w / 1000, 2)} kW"
    return f"{round(val_w, 1)} W"


def _categorize_reading(
    entity: dict,
) -> tuple[str, float | None, str]:
    """Categorize an energy reading as power or energy, with its value.

    Returns (category, numeric_value, unit).
    category is 'power' (W/kW) or 'energy' (Wh/kWh) or 'other'.
    """
    attrs = entity.get("attributes", {})
    unit = (
        attrs.get("unit_of_measurement", "") or ""
    ).lower()
    device_class = (
        attrs.get("device_class", "") or ""
    ).lower()
    state = entity.get("state", "")

    try:
        value = float(state)
    except (ValueError, TypeError):
        return ("other", None, unit)

    if device_class == "power" or unit in ("w", "kw"):
        return ("power", value, unit)
    if device_class == "energy" or unit in ("wh", "kwh"):
        return ("energy", value, unit)
    return ("other", value, unit)


@tool(
    description=(
        "List all energy-related entities in "
        "Home Assistant. Finds sensors with "
        "device_class energy/power or units W, kW, "
        "Wh, kWh. Useful for discovering what energy "
        "monitoring is available."
    ),
    parameters={
        "type": "object",
        "properties": {},
        "required": [],
    },
)
async def get_energy_entities() -> str:
    """List all energy-related entities."""
    # Kept as-is: complex filtering logic has no direct
    # generic equivalent.
    try:
        states = await ha_request("GET", "/states")
        if not isinstance(states, list):
            return (
                "Unable to reach Home Assistant. "
                "Check connection and try again."
            )
        energy = [
            s for s in states if _is_energy_entity(s)
        ]

        if not energy:
            return (
                "No energy-related entities found. "
                "Check if energy monitoring is set up "
                "in Home Assistant."
            )

        # Group by type
        power_entities = []
        energy_entities = []
        other_entities = []

        for e in energy:
            cat, _, _ = _categorize_reading(e)
            if cat == "power":
                power_entities.append(e)
            elif cat == "energy":
                energy_entities.append(e)
            else:
                other_entities.append(e)

        lines = []
        if power_entities:
            lines.append(
                f"Power sensors ({len(power_entities)}):"
            )
            for e in power_entities:
                lines.append(_format_reading(e))

        if energy_entities:
            if lines:
                lines.append("")
            lines.append(
                f"Energy sensors ({len(energy_entities)}):"
            )
            for e in energy_entities:
                lines.append(_format_reading(e))

        if other_entities:
            if lines:
                lines.append("")
            lines.append(
                f"Other energy-related "
                f"({len(other_entities)}):"
            )
            for e in other_entities:
                lines.append(_format_reading(e))

        total = len(energy)
        return (
            f"Found {total} energy-related "
            f"entity(ies):\n" + "\n".join(lines)
        )

    except httpx.HTTPStatusError as e:
        return format_ha_error(
            "sensor.*", "energy", e
        )
    except Exception as e:
        return f"Error listing energy entities: {e}"


@tool(
    description=(
        "Get the current power or energy reading for "
        "a specific sensor. Returns the value with "
        "unit and friendly name."
    ),
    parameters={
        "type": "object",
        "properties": {
            "entity_id": {
                "type": "string",
                "description": (
                    "Energy sensor entity ID, e.g. "
                    "'sensor.solar_power', "
                    "'sensor.grid_consumption'."
                ),
            },
        },
        "required": ["entity_id"],
    },
)
async def get_entity_power(entity_id: str) -> str:
    """Get current power/energy reading for a sensor."""
    logger.warning(
        "DEPRECATED: %s() called — use %s() instead",
        "get_entity_power", "query",
    )
    try:
        return await query(entity_id)
    except Exception as e:
        return f"Error reading energy sensor: {e}"


@tool(
    description=(
        "Get a summary of energy usage across the "
        "home. Shows total power draw, solar "
        "generation, grid consumption, and energy "
        "totals. Automatically finds and summarizes "
        "all energy-related sensors."
    ),
    parameters={
        "type": "object",
        "properties": {},
        "required": [],
    },
)
async def get_energy_summary() -> str:
    """Query common energy entities and build a summary."""
    # Kept as-is: complex aggregation logic has no direct
    # generic equivalent.
    try:
        states = await ha_request("GET", "/states")
        if not isinstance(states, list):
            return (
                "Unable to reach Home Assistant. "
                "Check connection and try again."
            )
        energy = [
            s for s in states if _is_energy_entity(s)
        ]

        if not energy:
            return (
                "No energy-related entities found. "
                "Check if energy monitoring is "
                "configured in Home Assistant "
                "(Settings > Dashboards > Energy)."
            )

        # Separate power (instantaneous) vs energy (cumulative)
        power_readings = []
        energy_readings = []

        for e in energy:
            cat, value, unit = _categorize_reading(e)
            if value is None:
                continue
            attrs = e.get("attributes", {})
            name = attrs.get(
                "friendly_name", e["entity_id"]
            )
            eid = e["entity_id"]

            if cat == "power":
                # Normalize to W for comparison
                val_w = (
                    value * 1000
                    if unit == "kw"
                    else value
                )
                display_unit = (
                    "kW"
                    if abs(val_w) >= 1000
                    else "W"
                )
                display_val = (
                    round(val_w / 1000, 2)
                    if display_unit == "kW"
                    else round(val_w, 1)
                )
                power_readings.append(
                    {
                        "name": name,
                        "entity_id": eid,
                        "value_w": val_w,
                        "display": (
                            f"{display_val} "
                            f"{display_unit}"
                        ),
                    }
                )
            elif cat == "energy":
                # Normalize to kWh
                val_kwh = (
                    value / 1000
                    if unit == "wh"
                    else value
                )
                energy_readings.append(
                    {
                        "name": name,
                        "entity_id": eid,
                        "value_kwh": val_kwh,
                        "display": (
                            f"{round(val_kwh, 2)} kWh"
                        ),
                    }
                )

        lines = ["Energy Summary"]
        lines.append("=" * 40)

        # Power (real-time)
        if power_readings:
            lines.append("")
            lines.append(
                "Current Power ("
                + str(len(power_readings))
                + " sensors):"
            )
            # Net consumption = grid import + device use - solar - grid export
            solar_w = 0.0
            grid_import_w = 0.0
            grid_export_w = 0.0
            consumption_w = 0.0

            for p in sorted(
                power_readings,
                key=lambda x: abs(x["value_w"]),
                reverse=True,
            ):
                category = _categorize_power_reading(p)
                val = p["value_w"]
                if category == "generating":
                    solar_w += val
                    indicator = " (generating)"
                elif category == "from_grid":
                    grid_import_w += val
                    indicator = " (from grid)"
                elif category == "exporting":
                    grid_export_w += val
                    indicator = " (exporting)"
                else:
                    consumption_w += val
                    indicator = " (consuming)"
                lines.append(
                    f"  {p['name']}: "
                    f"{p['display']}{indicator}"
                )

            # Net consumption: grid import + device use - solar - grid export
            net_w = grid_import_w + consumption_w - solar_w - grid_export_w
            if len(power_readings) > 1:
                net_display = (
                    f"{round(net_w / 1000, 2)} kW"
                    if abs(net_w) >= 1000
                    else f"{round(net_w, 1)} W"
                )
                lines.append(f"  --- Net consumption: {net_display}")
                # Per-category breakdown when we have multiple categories
                has_solar = solar_w != 0
                has_grid = grid_import_w != 0 or grid_export_w != 0
                if (has_solar or has_grid) and (consumption_w != 0 or grid_import_w != 0):
                    parts = []
                    if grid_import_w > 0:
                        parts.append(
                            f"grid +{_fmt_w(grid_import_w)}"
                        )
                    if consumption_w > 0:
                        parts.append(
                            f"devices +{_fmt_w(consumption_w)}"
                        )
                    if solar_w > 0:
                        parts.append(
                            f"solar -{_fmt_w(solar_w)}"
                        )
                    if grid_export_w > 0:
                        parts.append(
                            f"export -{_fmt_w(grid_export_w)}"
                        )
                    if parts:
                        lines.append(f"  Breakdown: {' '.join(parts)}")

        # Energy (cumulative)
        if energy_readings:
            lines.append("")
            lines.append(
                "Energy Totals ("
                + str(len(energy_readings))
                + " sensors):"
            )
            for e in sorted(
                energy_readings,
                key=lambda x: x["value_kwh"],
                reverse=True,
            ):
                lines.append(
                    f"  {e['name']}: {e['display']}"
                )

        if not power_readings and not energy_readings:
            lines.append("")
            lines.append(
                "Found energy entities but none have "
                "valid numeric readings right now."
            )
            lines.append("Entities found:")
            for e in energy[:10]:
                lines.append(
                    f"  - {_format_reading(e)}"
                )

        return "\n".join(lines)

    except httpx.HTTPStatusError as e:
        return format_ha_error(
            "sensor.*", "energy", e
        )
    except Exception as e:
        return f"Error getting energy summary: {e}"
