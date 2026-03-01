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

    Set hidden=True for tools that should remain callable
    but not be advertised to the LLM.
    """

    def decorator(func: Callable) -> Callable:
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

        if param.default is inspect.Parameter.empty:
            required.append(name)
        else:
            if param.default is not None:
                prop["default"] = param.default

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
        return "string"


def get_openai_tool_definitions() -> list[dict]:
    """Convert visible (non-hidden) tools to OpenAI function-calling format."""
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


# Core tools for voice mode — minimal set for fast responses.
# Only action/query tools; no automation CRUD, routines, etc.
VOICE_TOOLS = frozenset({
    "do",
    "query",
    "discover",
    "history",
    "control_vacuum",
    "clean_rooms",
    "get_weather",
    "manage_todo",
    "send_notification",
    "announce",
    "remember",
    "recall",
    "get_current_datetime",
    "activate_scene",
    "trigger_automation",
})


def get_voice_tool_definitions() -> list[dict]:
    """Reduced tool set for voice mode — faster LLM decisions.

    Only includes ~15 core tools instead of ~30, cutting prompt
    tokens and reducing the chance the LLM picks wrong tools.
    """
    definitions = []
    for name, info in TOOL_REGISTRY.items():
        if name not in VOICE_TOOLS:
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
