"""
Apex Tool System - Decorator-based tool registration.
Drop a .py file in tools/, add @tool decorator, done. Auto-discovered.
"""

import inspect
from typing import Any, Callable, get_type_hints


# Global registry of all tools
TOOL_REGISTRY: dict[str, dict] = {}


def tool(description: str, parameters: dict | None = None):
    """
    Decorator to register a function as an Apex tool.

    Usage:
        @tool(description="Get the current weather")
        async def get_weather(location: str) -> str:
            ...

    Parameters schema is auto-generated from type hints if not provided.
    """
    def decorator(func: Callable) -> Callable:
        # Auto-generate parameter schema from type hints
        schema = parameters or _schema_from_hints(func)

        TOOL_REGISTRY[func.__name__] = {
            "function": func,
            "description": description,
            "parameters": schema,
            "is_async": inspect.iscoroutinefunction(func),
        }
        return func

    return decorator


def _schema_from_hints(func: Callable) -> dict:
    """Generate an OpenAI-compatible parameter schema from function type hints."""
    hints = get_type_hints(func)
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
    """Convert all registered tools to OpenAI function-calling format."""
    definitions = []
    for name, info in TOOL_REGISTRY.items():
        definitions.append({
            "type": "function",
            "function": {
                "name": name,
                "description": info["description"],
                "parameters": info["parameters"],
            },
        })
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
        return f"Tool error ({name}): {e}"
