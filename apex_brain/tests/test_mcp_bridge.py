"""Tests for MCP Bridge (tools/mcp_bridge.py).

Covers:
- MCPBridge initialization
- Tool discovery and name collision skipping
- OpenAI format conversion with Gemini compatibility
- Tool execution and result parsing
- Connection failure graceful degradation
- Disconnect cleanup
- All MCP server interactions are mocked
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import (
    AsyncMock,
    MagicMock,
    patch,
)

import pytest
from tools.mcp_bridge import (
    MCPBridge,
    _ensure_property_types,
    _extract_text,
)

# ============================================================
# Helpers
# ============================================================


def _make_mcp_tool(
    name: str,
    description: str = "",
    input_schema: dict | None = None,
):
    """Create a mock MCP tool object."""
    tool = SimpleNamespace()
    tool.name = name
    tool.description = description
    tool.inputSchema = input_schema or {
        "type": "object",
        "properties": {
            "entity_id": {
                "type": "string",
                "description": "Entity ID",
            }
        },
        "required": ["entity_id"],
    }
    return tool


class _TextContent:
    def __init__(self, text):
        self.text = text


class _ImageContent:
    def __init__(self, mimeType):
        self.mimeType = mimeType


class _EmbeddedResource:
    def __init__(self, resource):
        self.resource = resource


def _make_text_content(text: str):
    """Create a mock TextContent."""
    return _TextContent(text)


def _make_image_content(mime: str = "image/png"):
    """Create a mock ImageContent."""
    return _ImageContent(mime)


def _make_embedded_resource(text: str, uri: str = ""):
    """Create a mock EmbeddedResource."""
    res = SimpleNamespace(text=text, uri=uri)
    return _EmbeddedResource(res)


def _make_call_result(content_items, is_error=False):
    """Create a mock CallToolResult."""
    result = SimpleNamespace()
    result.content = content_items
    result.isError = is_error
    return result


# ============================================================
# _ensure_property_types
# ============================================================


class TestEnsurePropertyTypes:
    """Gemini compatibility: all props need types."""

    def test_adds_missing_type(self):
        schema = {
            "type": "object",
            "properties": {
                "name": {"description": "A name"},
            },
        }
        result = _ensure_property_types(schema)
        assert result["properties"]["name"]["type"] == ("string")

    def test_preserves_existing_type(self):
        schema = {
            "type": "object",
            "properties": {
                "count": {
                    "type": "integer",
                    "description": "Count",
                },
            },
        }
        result = _ensure_property_types(schema)
        assert result["properties"]["count"]["type"] == ("integer")

    def test_recurses_nested_objects(self):
        schema = {
            "type": "object",
            "properties": {
                "data": {
                    "type": "object",
                    "properties": {
                        "val": {"description": "V"},
                    },
                }
            },
        }
        result = _ensure_property_types(schema)
        nested = result["properties"]["data"]
        assert nested["properties"]["val"]["type"] == ("string")

    def test_handles_non_dict(self):
        assert _ensure_property_types("not a dict") == ("not a dict")

    def test_handles_empty_properties(self):
        schema = {"type": "object", "properties": {}}
        result = _ensure_property_types(schema)
        assert result["properties"] == {}


# ============================================================
# MCPBridge initialization
# ============================================================


class TestMCPBridgeInit:
    def test_defaults(self):
        bridge = MCPBridge(url="http://localhost:8080/sse")
        assert bridge.url == "http://localhost:8080/sse"
        assert bridge.transport == "sse"
        assert not bridge.connected
        assert bridge.tool_count == 0
        assert bridge.tool_names == []

    def test_streamable_http(self):
        bridge = MCPBridge(
            url="http://localhost:8080/mcp",
            transport="streamable_http",
        )
        assert bridge.transport == "streamable_http"


# ============================================================
# Connection
# ============================================================


class TestConnect:
    @pytest.mark.asyncio
    async def test_connect_sse_success(self):
        bridge = MCPBridge(url="http://localhost:8080/sse")
        mock_session = AsyncMock()
        mock_session.initialize = AsyncMock()

        mock_transport_cm = AsyncMock()
        mock_transport_cm.__aenter__ = AsyncMock(
            return_value=(
                MagicMock(),
                MagicMock(),
            )
        )
        mock_transport_cm.__aexit__ = AsyncMock()

        mock_session_cm = AsyncMock()
        mock_session_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_cm.__aexit__ = AsyncMock()

        with (
            patch(
                "tools.mcp_bridge.sse_client",
                return_value=mock_transport_cm,
                create=True,
            ),
            patch(
                "mcp.ClientSession",
                return_value=mock_session_cm,
            ),
        ):
            # Patch the lazy imports inside connect()
            import tools.mcp_bridge as mod

            original_connect = mod.MCPBridge.connect

            async def patched_connect(self):
                self._transport_cm = mock_transport_cm
                await mock_transport_cm.__aenter__()
                self._session_cm = mock_session_cm
                self._session = await mock_session_cm.__aenter__()
                await self._session.initialize()
                self._connected = True

            mod.MCPBridge.connect = patched_connect
            try:
                await bridge.connect()
                assert bridge.connected
            finally:
                mod.MCPBridge.connect = original_connect

    @pytest.mark.asyncio
    async def test_connect_failure_graceful(self):
        bridge = MCPBridge(url="http://bad-host:9999/sse")

        async def failing_connect(_self):
            raise ConnectionError("refused")

        import tools.mcp_bridge as mod

        original = mod.MCPBridge.connect

        # Simulate what connect() does on failure
        async def mock_connect(self):
            try:
                raise ConnectionError("refused")
            except Exception:
                self._connected = False

        mod.MCPBridge.connect = mock_connect
        try:
            await bridge.connect()
            assert not bridge.connected
        finally:
            mod.MCPBridge.connect = original


# ============================================================
# Tool Discovery
# ============================================================


class TestDiscoverTools:
    @pytest.mark.asyncio
    async def test_discovers_tools(self):
        bridge = MCPBridge(url="http://x/sse")
        bridge._connected = True

        mock_tools = [
            _make_mcp_tool("mcp_lights", "Lights"),
            _make_mcp_tool("mcp_climate", "Climate"),
        ]
        mock_result = SimpleNamespace(tools=mock_tools)

        bridge._session = AsyncMock()
        bridge._session.list_tools = AsyncMock(return_value=mock_result)

        tools = await bridge.discover_tools()
        assert len(tools) == 2
        assert bridge.tool_count == 2
        assert "mcp_lights" in bridge.tool_names
        assert "mcp_climate" in bridge.tool_names

    @pytest.mark.asyncio
    async def test_skips_collisions(self):
        bridge = MCPBridge(url="http://x/sse")
        bridge._connected = True

        mock_tools = [
            _make_mcp_tool("do", "Overlap"),
            _make_mcp_tool("query", "Overlap"),
            _make_mcp_tool("new_tool", "New"),
        ]
        mock_result = SimpleNamespace(tools=mock_tools)

        bridge._session = AsyncMock()
        bridge._session.list_tools = AsyncMock(return_value=mock_result)

        tools = await bridge.discover_tools(skip_names={"do", "query"})
        assert len(tools) == 1
        assert bridge.has_tool("new_tool")
        assert not bridge.has_tool("do")
        assert not bridge.has_tool("query")

    @pytest.mark.asyncio
    async def test_not_connected_returns_empty(self):
        bridge = MCPBridge(url="http://x/sse")
        bridge._connected = False
        tools = await bridge.discover_tools()
        assert tools == []

    @pytest.mark.asyncio
    async def test_discovery_error_returns_empty(self):
        bridge = MCPBridge(url="http://x/sse")
        bridge._connected = True
        bridge._session = AsyncMock()
        bridge._session.list_tools = AsyncMock(
            side_effect=RuntimeError("timeout")
        )
        tools = await bridge.discover_tools()
        assert tools == []


# ============================================================
# OpenAI Tool Definitions
# ============================================================


class TestOpenAIDefinitions:
    def test_converts_to_openai_format(self):
        bridge = MCPBridge(url="http://x/sse")
        bridge._tools = [
            _make_mcp_tool(
                "get_states",
                "Get entity states",
                {
                    "type": "object",
                    "properties": {
                        "domain": {
                            "type": "string",
                            "description": "Domain",
                        }
                    },
                },
            )
        ]
        bridge._tool_names = {"get_states"}

        defs = bridge.get_openai_tool_definitions()
        assert len(defs) == 1
        d = defs[0]
        assert d["type"] == "function"
        assert d["function"]["name"] == "get_states"
        assert d["function"]["description"] == ("Get entity states")
        assert (
            d["function"]["parameters"]["properties"]["domain"]["type"]
            == "string"
        )

    def test_adds_missing_types_for_gemini(self):
        bridge = MCPBridge(url="http://x/sse")
        bridge._tools = [
            _make_mcp_tool(
                "test",
                "Test",
                {
                    "type": "object",
                    "properties": {"name": {"description": "Name only"}},
                },
            )
        ]
        bridge._tool_names = {"test"}

        defs = bridge.get_openai_tool_definitions()
        props = defs[0]["function"]["parameters"]["properties"]
        assert props["name"]["type"] == "string"

    def test_empty_tools_returns_empty(self):
        bridge = MCPBridge(url="http://x/sse")
        assert bridge.get_openai_tool_definitions() == []

    def test_missing_schema_gets_default(self):
        bridge = MCPBridge(url="http://x/sse")
        tool = SimpleNamespace()
        tool.name = "no_schema"
        tool.description = "No schema"
        tool.inputSchema = None
        bridge._tools = [tool]
        bridge._tool_names = {"no_schema"}

        defs = bridge.get_openai_tool_definitions()
        params = defs[0]["function"]["parameters"]
        assert params["type"] == "object"


# ============================================================
# Tool Execution
# ============================================================


class TestExecuteTool:
    @pytest.mark.asyncio
    async def test_text_result(self):
        bridge = MCPBridge(url="http://x/sse")
        bridge._connected = True
        bridge._tool_names = {"get_state"}

        text_content = _make_text_content("light.kitchen: on")
        mock_result = _make_call_result([text_content])

        mock_types = SimpleNamespace(
            TextContent=_TextContent,
            ImageContent=_ImageContent,
            EmbeddedResource=_EmbeddedResource,
        )
        parts = _extract_text(mock_result, mock_types)
        assert "light.kitchen: on" in parts

    @pytest.mark.asyncio
    async def test_error_result(self):
        bridge = MCPBridge(url="http://x/sse")
        bridge._connected = True
        bridge._tool_names = {"bad_tool"}

        text_content = _make_text_content("entity not found")
        mock_result = _make_call_result([text_content], is_error=True)

        bridge._session = AsyncMock()
        bridge._session.call_tool = AsyncMock(return_value=mock_result)

        mock_types = SimpleNamespace(
            TextContent=_TextContent,
            ImageContent=_ImageContent,
            EmbeddedResource=_EmbeddedResource,
        )

        with patch.dict(
            "sys.modules",
            {"mcp": SimpleNamespace(types=mock_types)},
        ):
            result = await bridge.execute_tool("bad_tool", {"id": "x"})
            assert "error" in result.lower()

    @pytest.mark.asyncio
    async def test_not_connected(self):
        bridge = MCPBridge(url="http://x/sse")
        bridge._connected = False
        result = await bridge.execute_tool("test", {})
        assert "not connected" in result.lower()

    @pytest.mark.asyncio
    async def test_exception_handling(self):
        bridge = MCPBridge(url="http://x/sse")
        bridge._connected = True
        bridge._session = AsyncMock()
        bridge._session.call_tool = AsyncMock(
            side_effect=RuntimeError("network error")
        )

        # Mock the lazy import
        with patch.dict(
            "sys.modules",
            {"mcp": SimpleNamespace(types=SimpleNamespace())},
        ):
            result = await bridge.execute_tool("test", {})
            assert "error" in result.lower()
            assert "network error" in result


# ============================================================
# has_tool
# ============================================================


class TestHasTool:
    def test_has_known_tool(self):
        bridge = MCPBridge(url="http://x/sse")
        bridge._tool_names = {"my_tool"}
        assert bridge.has_tool("my_tool")

    def test_does_not_have_unknown(self):
        bridge = MCPBridge(url="http://x/sse")
        bridge._tool_names = {"my_tool"}
        assert not bridge.has_tool("other")


# ============================================================
# Disconnect
# ============================================================


class TestDisconnect:
    @pytest.mark.asyncio
    async def test_disconnect_cleans_up(self):
        bridge = MCPBridge(url="http://x/sse")
        bridge._connected = True
        bridge._session_cm = AsyncMock()
        bridge._session_cm.__aexit__ = AsyncMock()
        bridge._transport_cm = AsyncMock()
        bridge._transport_cm.__aexit__ = AsyncMock()
        bridge._session = AsyncMock()

        await bridge.disconnect()
        assert not bridge.connected
        assert bridge._session is None

    @pytest.mark.asyncio
    async def test_disconnect_when_not_connected(self):
        bridge = MCPBridge(url="http://x/sse")
        # Should not raise
        await bridge.disconnect()
        assert not bridge.connected


# ============================================================
# _extract_text
# ============================================================


class TestExtractText:
    def test_text_content(self):
        tc = _make_text_content("hello")
        mock_types = SimpleNamespace(
            TextContent=_TextContent,
            ImageContent=_ImageContent,
            EmbeddedResource=_EmbeddedResource,
        )
        result = _make_call_result([tc])
        parts = _extract_text(result, mock_types)
        assert parts == ["hello"]

    def test_image_content(self):
        ic = _make_image_content("image/jpeg")
        mock_types = SimpleNamespace(
            TextContent=_TextContent,
            ImageContent=_ImageContent,
            EmbeddedResource=_EmbeddedResource,
        )
        result = _make_call_result([ic])
        parts = _extract_text(result, mock_types)
        assert "[Image:" in parts[0]

    def test_embedded_resource_text(self):
        er = _make_embedded_resource("config data", "file://config")
        mock_types = SimpleNamespace(
            TextContent=_TextContent,
            ImageContent=_ImageContent,
            EmbeddedResource=_EmbeddedResource,
        )
        result = _make_call_result([er])
        parts = _extract_text(result, mock_types)
        assert "config data" in parts[0]

    def test_multiple_content(self):
        tc = _make_text_content("line 1")
        tc2 = _make_text_content("line 2")
        mock_types = SimpleNamespace(
            TextContent=_TextContent,
            ImageContent=_ImageContent,
            EmbeddedResource=_EmbeddedResource,
        )
        result = _make_call_result([tc, tc2])
        parts = _extract_text(result, mock_types)
        assert len(parts) == 2

    def test_empty_content(self):
        mock_types = SimpleNamespace(
            TextContent=_TextContent,
            ImageContent=_ImageContent,
            EmbeddedResource=_EmbeddedResource,
        )
        result = _make_call_result([])
        parts = _extract_text(result, mock_types)
        assert parts == []
