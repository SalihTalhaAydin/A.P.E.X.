"""
System info, device listing, integration listing,
and service discovery tools for Home Assistant.
"""

import logging

from tools.base import tool
from tools.ha_helpers import ha_request

logger = logging.getLogger(__name__)


@tool(
    description=(
        "Get Home Assistant system information: "
        "version, uptime, location, timezone, "
        "installation type, and more."
    ),
    parameters={
        "type": "object",
        "properties": {},
        "required": [],
    },
)
async def get_ha_info() -> str:
    """Get HA system information."""
    try:
        config = await ha_request("GET", "/config")
        if not isinstance(config, dict):
            return "Could not retrieve HA config."

        lines = [
            "Home Assistant System Info:",
            f"  Version: {config.get('version', '?')}",
            f"  Location: {config.get('location_name', '?')}",
            f"  Timezone: {config.get('time_zone', '?')}",
            f"  Unit system: {config.get('unit_system', {}).get('temperature', '?')}",
            f"  Elevation: {config.get('elevation', '?')}m",
            f"  Latitude: {config.get('latitude', '?')}",
            f"  Longitude: {config.get('longitude', '?')}",
            f"  Internal URL: {config.get('internal_url', 'n/a')}",
            f"  External URL: {config.get('external_url', 'n/a')}",
        ]

        components = config.get("components", [])
        if components:
            lines.append(f"  Loaded integrations: {len(components)}")

        return "\n".join(lines)
    except Exception as e:
        return f"Error getting HA info: {e}"


@tool(
    description=(
        "List all available services (actions) in "
        "Home Assistant, grouped by domain. Use to "
        "discover what actions are possible. "
        "Optionally filter by domain."
    ),
    parameters={
        "type": "object",
        "properties": {
            "domain": {
                "type": "string",
                "description": (
                    "Filter by domain, e.g. 'light', "
                    "'climate', 'automation'. Optional."
                ),
            },
        },
        "required": [],
    },
)
async def list_services(domain: str = "") -> str:
    """List available HA services."""
    try:
        result = await ha_request("GET", "/services")
        if not isinstance(result, list):
            return "Could not retrieve services."

        if domain:
            result = [s for s in result if s.get("domain") == domain]

        if not result:
            suffix = f" for domain '{domain}'" if domain else ""
            return f"No services found{suffix}."

        lines = []
        for svc_group in result:
            d = svc_group.get("domain", "?")
            services = svc_group.get("services", {})
            svc_names = list(services.keys())
            if len(svc_names) <= 5:
                svc_list = ", ".join(svc_names)
            else:
                svc_list = (
                    ", ".join(svc_names[:5])
                    + f" (+{len(svc_names) - 5} more)"
                )
            lines.append(f"  {d}: {svc_list}")

        _MAX_DOMAINS = 50
        total = len(lines)
        shown = lines[:_MAX_DOMAINS]

        header = f"Available services ({total} domains):"
        if total > _MAX_DOMAINS:
            header += f" (showing first {_MAX_DOMAINS})"

        return header + "\n" + "\n".join(shown)
    except Exception as e:
        return f"Error listing services: {e}"


@tool(
    description=(
        "List all integrations (components) loaded "
        "in Home Assistant. Shows what platforms and "
        "services are available."
    ),
    parameters={
        "type": "object",
        "properties": {
            "search": {
                "type": "string",
                "description": (
                    "Filter integrations by keyword "
                    "(e.g. 'zwave', 'mqtt', 'hue'). "
                    "Optional."
                ),
            },
        },
        "required": [],
    },
)
async def list_integrations(
    search: str = "",
) -> str:
    """List loaded HA integrations."""
    try:
        config = await ha_request("GET", "/config")
        if not isinstance(config, dict):
            return "Could not retrieve config."

        components = config.get("components", [])
        if not components:
            return "No integrations found."

        if search:
            s = search.lower()
            components = [c for c in components if s in c.lower()]

        if not components:
            return f"No integrations matching '{search}'."

        # Group by base integration
        grouped: dict[str, list[str]] = {}
        for c in sorted(components):
            parts = c.split(".")
            base = parts[0]
            if base not in grouped:
                grouped[base] = []
            if len(parts) > 1:
                grouped[base].append(parts[1])

        lines = []
        for base, platforms in sorted(grouped.items()):
            if platforms:
                plats = ", ".join(platforms[:5])
                extra = (
                    f" +{len(platforms) - 5}" if len(platforms) > 5 else ""
                )
                lines.append(f"  {base}: {plats}{extra}")
            else:
                lines.append(f"  {base}")

        _MAX = 60
        total = len(lines)
        shown = lines[:_MAX]

        header = f"Loaded integrations ({total} total):"
        if total > _MAX:
            header += f" (showing first {_MAX})"

        return header + "\n" + "\n".join(shown)
    except Exception as e:
        return f"Error listing integrations: {e}"


@tool(
    description=(
        "List all physical devices registered in "
        "Home Assistant. Shows device name, "
        "manufacturer, model, and area. Optionally "
        "filter by keyword or area."
    ),
    parameters={
        "type": "object",
        "properties": {
            "search": {
                "type": "string",
                "description": (
                    "Filter by keyword in device "
                    "name, manufacturer, or model. "
                    "Optional."
                ),
            },
        },
        "required": [],
    },
)
async def list_devices(search: str = "") -> str:
    """List registered HA devices via template."""
    try:
        # Use template API to get device info
        template = (
            "{% for device in devices() %}"
            "{{ device_attr(device, 'name') or '?' }}"
            " | {{ device_attr(device, 'manufacturer') or '?' }}"
            " | {{ device_attr(device, 'model') or '?' }}"
            " | {{ area_name(device_attr(device, 'area_id')) or 'No area' }}"
            " | {{ device }}"
            "\n{% endfor %}"
        )
        result = await ha_request(
            "POST",
            "/template",
            json_data={"template": template},
        )

        if not isinstance(result, str) or not result.strip():
            return "No devices found."

        lines = result.strip().split("\n")

        if search:
            s = search.lower()
            lines = [ln for ln in lines if s in ln.lower()]

        if not lines:
            return f"No devices matching '{search}'."

        formatted = []
        for line in lines:
            parts = line.split(" | ")
            if len(parts) >= 4:
                name = parts[0].strip()
                mfr = parts[1].strip()
                model = parts[2].strip()
                area = parts[3].strip()
                formatted.append(f"  {name} ({mfr} {model}) - {area}")
            else:
                formatted.append(f"  {line.strip()}")

        _MAX = 60
        total = len(formatted)
        shown = formatted[:_MAX]

        header = f"Registered devices ({total} total):"
        if total > _MAX:
            header += f" (showing first {_MAX})"

        return header + "\n" + "\n".join(shown)
    except Exception as e:
        return f"Error listing devices: {e}"
