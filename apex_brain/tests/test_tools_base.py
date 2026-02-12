"""Tests for tools.base (schema, registry, execute)."""

import pytest
from tools.base import (
    TOOL_REGISTRY,
    _python_type_to_json,
    _schema_from_hints,
    execute_tool,
    get_openai_tool_definitions,
    tool,
)


def test_python_type_to_json():
    """_python_type_to_json maps built-in types to JSON schema types."""
    assert _python_type_to_json(str) == "string"
    assert _python_type_to_json(int) == "integer"
    assert _python_type_to_json(float) == "number"
    assert _python_type_to_json(bool) == "boolean"
    assert _python_type_to_json(list) == "array"
    assert _python_type_to_json(dict) == "object"


def test_schema_from_hints():
    """_schema_from_hints produces required and properties from type hints."""

    def sample(a: str, b: int, c: float = 1.0) -> str:
        return f"{a}_{b}_{c}"

    schema = _schema_from_hints(sample)
    assert schema["type"] == "object"
    assert "a" in schema["properties"]
    assert schema["properties"]["a"]["type"] == "string"
    assert schema["properties"]["b"]["type"] == "integer"
    assert schema["properties"]["c"]["type"] == "number"
    assert schema["properties"]["c"]["default"] == 1.0
    assert set(schema["required"]) == {"a", "b"}


@pytest.fixture
def registered_tool_name():
    """Register a simple sync tool and yield its name; remove after test."""

    @tool(description="Echo the input")
    def echo_sync(msg: str) -> str:
        return msg

    name = "echo_sync"
    yield name
    TOOL_REGISTRY.pop(name, None)


def test_get_openai_tool_definitions(registered_tool_name):
    """get_openai_tool_definitions returns OpenAI function format."""
    defs = get_openai_tool_definitions()
    names = [d["function"]["name"] for d in defs]
    assert registered_tool_name in names
    one = next(
        d for d in defs if d["function"]["name"] == registered_tool_name
    )
    assert one["type"] == "function"
    assert one["function"]["description"] == "Echo the input"
    assert "parameters" in one["function"]


@pytest.mark.asyncio
async def test_execute_tool_sync(registered_tool_name):
    """execute_tool runs a sync tool and returns its result."""
    result = await execute_tool(registered_tool_name, {"msg": "hello"})
    assert result == "hello"


@pytest.mark.asyncio
async def test_execute_tool_unknown():
    """execute_tool returns error message for unknown tool."""
    result = await execute_tool("nonexistent_tool", {})
    assert "Unknown tool" in result
