"""
Configuration reload tools for Home Assistant.
Reload automations, scripts, scenes, groups, etc. without restarting.
"""

import logging

from tools.base import tool
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
    try:
        domain = domain.lower().strip()

        if domain == "all":
            await ha_request(
                "POST",
                "/services/homeassistant/reload_all",
                json_data={},
            )
            return "Done. Reloaded all configurations."

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

        await ha_request(
            "POST",
            f"/services/{service_path}",
            json_data={},
        )
        return f"Done. Reloaded {domain} configuration."

    except Exception as e:
        return f"Error reloading {domain}: {e}"
