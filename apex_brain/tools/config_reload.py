"""
Configuration reload tools for Home Assistant.
Reload automations, scripts, scenes, groups, etc. without restarting.

DEPRECATED: This tool is a thin wrapper that delegates to the generic
do() tool in tools.generic for the 'all' case. Domain-specific reloads
keep their existing implementation (the reload service paths don't map
cleanly to the generic do() pattern).
"""

import logging

from tools.base import tool
from tools.generic import do
from tools.ha_helpers import ha_request

logger = logging.getLogger(__name__)


@tool(
    description=(
        "Reload Home Assistant configuration for a "
        "specific domain. Use after editing YAML "
        "configs. Domains: 'automation', 'script', "
        "'scene', 'group', 'input_boolean', "
        "'input_number', 'input_select', 'input_text', "
        "'input_datetime', 'timer', 'counter', "
        "'template', 'all' (full core reload)."
    ),
    parameters={
        "type": "object",
        "properties": {
            "domain": {
                "type": "string",
                "description": (
                    "Domain to reload: 'automation', "
                    "'script', 'scene', 'group', "
                    "'input_boolean', 'input_number', "
                    "'input_select', 'input_text', "
                    "'input_datetime', 'timer', "
                    "'counter', 'template', or "
                    "'all' for full core reload."
                ),
            },
        },
        "required": ["domain"],
    },
)
async def reload_config(domain: str) -> str:
    """Reload HA configuration for a domain."""
    logger.warning(
        "DEPRECATED: %s() called — use %s() instead",
        "reload_config", "do",
    )
    try:
        domain = domain.lower().strip()

        if domain == "all":
            return await do(
                "homeassistant",
                "reload_all",
            )

        # Most domains use their own reload service
        reload_map = {
            "automation": "automation/reload",
            "script": "script/reload",
            "scene": "scene/reload",
            "group": "group/reload",
            "input_boolean": "input_boolean/reload",
            "input_number": "input_number/reload",
            "input_select": "input_select/reload",
            "input_text": "input_text/reload",
            "input_datetime": "input_datetime/reload",
            "timer": "timer/reload",
            "counter": "counter/reload",
            "template": "template/reload",
        }

        service_path = reload_map.get(domain)
        if not service_path:
            return (
                f"Unknown domain: '{domain}'. "
                f"Valid options: "
                f"{', '.join(sorted(reload_map))}, all"
            )

        # Use do() — split "domain/service" into parts
        reload_domain, reload_service = service_path.split("/")
        return await do(reload_domain, reload_service)

    except Exception as e:
        return f"Error reloading {domain}: {e}"
