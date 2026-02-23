"""
Apex Tool System - Decorator-based tool registration.
Drop a .py file in tools/, add @tool decorator, done. Auto-discovered.
"""

from __future__ import annotations

import inspect
import logging
from collections.abc import Callable
from typing import Any, get_type_hints

logger = logging.getLogger(__name__)

# Global registry of all tools
TOOL_REGISTRY: dict[str, dict] = {}


def tool(
    description: str,
    parameters: dict | None = None,
    hidden: bool = False,
):
    """
    Decorator to register a function as an Apex tool.

    Usage:
        @tool(description="Get the current weather")
        async def get_weather(location: str) -> str:
            ...

    Parameters schema is auto-generated from type hints if not provided.

    Set hidden=True for deprecated tools that should remain callable
    but not be advertised to the LLM (reduces tool count confusion).
    """

    def decorator(func: Callable) -> Callable:
        # Auto-generate parameter schema from type hints
        schema = parameters or _schema_from_hints(func)

        TOOL_REGISTRY[func.__name__] = {
            "function": func,
            "description": description,
            "parameters": schema,
            "is_async": inspect.iscoroutinefunction(func),
            "hidden": hidden,
        }
        return func

    return decorator


def _schema_from_hints(func: Callable) -> dict:
    """Generate an OpenAI-compatible parameter schema from function type hints."""
    try:
        hints = get_type_hints(func)
    except (TypeError, NameError):
        # Fallback for older Python where PEP 604 unions can't be evaluated
        hints = {}
    sig = inspect.signature(func)

    properties = {}
    required = []

    for name, param in sig.parameters.items():
        if name in ("self", "cls"):
            continue

        hint = hints.get(name, str)
        json_type = _python_type_to_json(hint)

        prop: dict[str, Any] = {"type": json_type}

        # Use parameter default as description hint if no other info
        if param.default is inspect.Parameter.empty:
            required.append(name)
        else:
            if param.default is not None:
                prop["default"] = param.default

        # Clean up the parameter name for description
        prop["description"] = name.replace("_", " ").capitalize()

        properties[name] = prop

    return {
        "type": "object",
        "properties": properties,
        "required": required,
    }


def _python_type_to_json(hint) -> str:
    """Map Python type hints to JSON Schema types."""
    origin = getattr(hint, "__origin__", None)

    if hint is str:
        return "string"
    elif hint is int:
        return "integer"
    elif hint is float:
        return "number"
    elif hint is bool:
        return "boolean"
    elif hint is list or origin is list:
        return "array"
    elif hint is dict or origin is dict:
        return "object"
    else:
        return "string"  # Default fallback


def get_openai_tool_definitions() -> list[dict]:
    """Convert visible (non-hidden) tools to OpenAI function-calling format.

    Hidden tools (deprecated wrappers) are still callable via execute_tool()
    but are not advertised to the LLM, reducing tool count and confusion.
    """
    definitions = []
    for name, info in TOOL_REGISTRY.items():
        if info.get("hidden"):
            continue
        definitions.append(
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": info["description"],
                    "parameters": info["parameters"],
                },
            }
        )
    return definitions


def hide_tools(*names: str) -> None:
    """Mark tools as hidden (not advertised to LLM but still callable).

    Used to suppress deprecated wrapper tools that create confusion
    when the LLM sees 70+ overlapping tool definitions.
    """
    for name in names:
        if name in TOOL_REGISTRY:
            TOOL_REGISTRY[name]["hidden"] = True


# Deprecated wrapper tools that delegate to the 6 generic tools.
# Kept callable for backward compatibility but hidden from the LLM
# to reduce tool count from ~70 to ~30 and prevent confusion.
DEPRECATED_TOOLS = (
    # smart_home.py wrappers → do/query/discover
    "list_entities",
    "get_entity_state",
    "get_areas",
    "query_sensors",
    "control_light",
    "control_climate",
    "control_media",
    "control_cover",
    "control_fan",
    # control_area kept visible (not in DEPRECATED): accepts area_name,
    # resolves to area_id. do() requires area_id — LLM needs control_area.
    "call_service",
    # history.py → history()
    "get_history",
    "get_logbook",
    # lock.py → do()
    "control_lock",
    # switch.py → do()
    "control_switch",
    # security.py → do()  (camera tools kept — no generic equivalent)
    "control_alarm",
    # template.py → query()
    "evaluate_template",
    # script.py → do/discover()
    "list_scripts",
    "execute_script",
    # system_info.py → discover()
    "get_ha_info",
    "list_devices",
    "list_integrations",
    "list_services",
    # presence.py → query()
    "get_presence",
    # config_reload.py → do()
    "reload_config",
    # input_helpers.py → do/query()
    "set_input_helper",
    "list_input_helpers",
    # energy.py → query()
    "get_energy_summary",
)


async def execute_tool(name: str, arguments: dict) -> str:
    """Execute a registered tool by name with given arguments."""
    if name not in TOOL_REGISTRY:
        return f"Unknown tool: {name}"

    info = TOOL_REGISTRY[name]
    func = info["function"]

    try:
        if info["is_async"]:
            result = await func(**arguments)
        else:
            result = func(**arguments)
        return str(result)
    except Exception as e:
        logger.exception(
            "Tool '%s' raised an exception with args %s",
            name,
            arguments,
        )
        return f"Tool error ({name}): {e}"
