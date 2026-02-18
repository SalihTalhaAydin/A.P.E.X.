"""
Template evaluation tool for Home Assistant.
Evaluate Jinja2 templates against the HA template engine.
"""

import logging

from tools.base import tool
from tools.ha_helpers import ha_request

logger = logging.getLogger(__name__)


@tool(
    description=(
        "Evaluate a Home Assistant Jinja2 template. "
        "Use for complex queries like 'how many lights "
        "are on?', 'list all open doors', 'average "
        "temperature across rooms', or any calculation "
        "using HA state data. Templates use HA's full "
        "Jinja2 engine with states, is_state, "
        "state_attr, etc."
    ),
    parameters={
        "type": "object",
        "properties": {
            "template": {
                "type": "string",
                "description": (
                    "Jinja2 template string. "
                    "Examples:\n"
                    "- '{{ states.light | selectattr("
                    '"state", "eq", "on") | '
                    "list | count }}'\n"
                    "- '{{ states(\"sensor.temp\") }}'\n"
                    "- '{% for s in states.binary_"
                    'sensor if s.state == "on" %}'
                    "{{ s.name }}\\n{% endfor %}'"
                ),
            },
        },
        "required": ["template"],
    },
)
async def evaluate_template(template: str) -> str:
    """Evaluate a Jinja2 template in HA."""
    try:
        result = await ha_request(
            "POST",
            "/template",
            json_data={"template": template},
        )
        if isinstance(result, str):
            return result.strip() or "(empty result)"
        return str(result)
    except Exception as e:
        return f"Template error: {e}"
