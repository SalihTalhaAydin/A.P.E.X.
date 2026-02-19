"""
Template evaluation tool for Home Assistant.
Evaluate Jinja2 templates against the HA template engine.

DEPRECATED: This tool is a thin wrapper that delegates to the generic
query() tool in tools.generic. Use query() directly for new code.
"""

import logging

from tools.base import tool
from tools.generic import query

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
    logger.warning(
        "DEPRECATED: %s() called — use %s() instead",
        "evaluate_template", "query",
    )
    try:
        return await query(template)
    except Exception as e:
        return f"Template error: {e}"
