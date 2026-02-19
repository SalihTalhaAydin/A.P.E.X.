"""
Energy monitoring tools for Home Assistant.
Query power (W/kW) and energy (Wh/kWh) sensors to provide
summaries of household energy consumption, solar generation, etc.
"""

from __future__ import annotations

import httpx

from tools.base import tool
from tools.ha_helpers import (
    format_ha_error,
    ha_request,
    read_state,
)

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
    try:
        states = await ha_request("GET", "/states")
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
    try:
        state = await read_state(entity_id)
        attrs = state.get("attributes", {})
        name = attrs.get("friendly_name", entity_id)
        value = state.get("state", "unknown")
        unit = attrs.get("unit_of_measurement", "")
        device_class = attrs.get("device_class", "")

        if value in ("unavailable", "unknown"):
            return (
                f"{name} ({entity_id}): {value} "
                "(sensor may be offline)"
            )

        parts = [f"{name} ({entity_id}): {value} {unit}"]

        if device_class:
            parts.append(f"  Device class: {device_class}")

        # Add context about what the reading means
        try:
            val = float(value)
            unit_lower = (unit or "").lower()
            if unit_lower in ("w", "kw"):
                if val > 0:
                    parts.append(
                        "  Status: currently drawing power"
                    )
                elif val < 0:
                    parts.append(
                        "  Status: currently "
                        "generating/exporting power"
                    )
                else:
                    parts.append(
                        "  Status: no power flow"
                    )
        except (ValueError, TypeError):
            pass

        return "\n".join(parts)

    except httpx.HTTPStatusError as e:
        return format_ha_error(entity_id, "energy", e)
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
    try:
        states = await ha_request("GET", "/states")
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
            total_w = 0
            for p in sorted(
                power_readings,
                key=lambda x: abs(x["value_w"]),
                reverse=True,
            ):
                indicator = ""
                eid_lower = p["entity_id"].lower()
                name_lower = p["name"].lower()
                if any(
                    kw in eid_lower or kw in name_lower
                    for kw in ("solar", "pv", "generat")
                ):
                    indicator = " (generating)"
                elif any(
                    kw in eid_lower or kw in name_lower
                    for kw in ("grid", "import", "mains")
                ):
                    indicator = " (from grid)"
                elif any(
                    kw in eid_lower or kw in name_lower
                    for kw in ("export", "feed")
                ):
                    indicator = " (exporting)"
                lines.append(
                    f"  {p['name']}: "
                    f"{p['display']}{indicator}"
                )
                total_w += p["value_w"]

            if len(power_readings) > 1:
                total_display = (
                    f"{round(total_w / 1000, 2)} kW"
                    if abs(total_w) >= 1000
                    else f"{round(total_w, 1)} W"
                )
                lines.append(
                    f"  --- Total: {total_display}"
                )

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
