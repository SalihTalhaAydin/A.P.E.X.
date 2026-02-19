"""
System info, device listing, integration listing,
and service discovery tools for Home Assistant.

DEPRECATED: These tools are thin wrappers that delegate to the generic
discover() tool in tools.generic. Use discover() directly for new code.
"""

import logging

from tools.base import tool
from tools.generic import discover

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
    logger.warning(
        "DEPRECATED: %s() called — use %s() instead",
        "get_ha_info", "discover",
    )
    try:
        return await discover("info")
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
    logger.warning(
        "DEPRECATED: %s() called — use %s() instead",
        "list_services", "discover",
    )
    try:
        return await discover("services", domain)
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
    logger.warning(
        "DEPRECATED: %s() called — use %s() instead",
        "list_integrations", "discover",
    )
    try:
        return await discover("integrations", search)
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
    logger.warning(
        "DEPRECATED: %s() called — use %s() instead",
        "list_devices", "discover",
    )
    try:
        return await discover("devices", search)
    except Exception as e:
        return f"Error listing devices: {e}"
