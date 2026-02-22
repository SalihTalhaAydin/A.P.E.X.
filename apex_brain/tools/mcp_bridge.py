"""
MCP Bridge - Connect to an MCP server for expanded
Home Assistant capabilities.

Discovers tools from the MCP server at startup and
makes them available alongside native APEX tools.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def _ensure_property_types(
    schema: dict[str, Any],
) -> dict[str, Any]:
    """Ensure every property has a type field.

    Gemini (via LiteLLM) requires explicit types on
    every property in the JSON schema.
    """
    if not isinstance(schema, dict):
        return schema

    props = schema.get("properties", {})
    for key, prop in props.items():
        if isinstance(prop, dict) and "type" not in prop:
            props[key] = {**prop, "type": "string"}
        # Recurse into nested objects
        if isinstance(prop, dict) and prop.get("type") == "object":
            props[key] = _ensure_property_types(prop)

    return schema


class MCPBridge:
    """Bridge between APEX and a remote MCP server.

    Connects via SSE or Streamable HTTP, discovers
    tools, and forwards tool calls.
    """

    def __init__(
        self,
        url: str,
        transport: str = "sse",
    ):
        self.url = url
        self.transport = transport
        self._session = None
        self._transport_cm = None
        self._session_cm = None
        self._tools: list = []
        self._tool_names: set[str] = set()
        self._connected = False

    async def connect(self) -> None:
        """Open transport and initialize session."""
        try:
            if self.transport == "streamable_http":
                from mcp.client.streamable_http import (
                    streamable_http_client,
                )

                self._transport_cm = streamable_http_client(self.url)
            else:
                from mcp.client.sse import sse_client

                self._transport_cm = sse_client(url=self.url)

            streams = await self._transport_cm.__aenter__()
            # SDK may yield 2 or 3 values
            if len(streams) >= 2:
                read_stream = streams[0]
                write_stream = streams[1]
            else:
                raise ValueError("MCP transport did not yield streams")

            from mcp import ClientSession

            self._session_cm = ClientSession(read_stream, write_stream)
            try:
                self._session = await self._session_cm.__aenter__()
                await self._session.initialize()
            except Exception:
                # Clean up transport if session init fails
                await self._transport_cm.__aexit__(
                    None, None, None
                )
                raise
            self._connected = True
            logger.info(
                "MCP bridge connected to %s (%s)",
                self.url,
                self.transport,
            )
        except Exception as e:
            logger.warning(
                "MCP bridge failed to connect to %s: %s"
                " — continuing with native tools only",
                self.url,
                e,
            )
            self._connected = False

    async def disconnect(self) -> None:
        """Clean up session and transport."""
        try:
            if self._session_cm:
                await self._session_cm.__aexit__(None, None, None)
            if self._transport_cm:
                await self._transport_cm.__aexit__(None, None, None)
        except Exception as e:
            logger.debug("MCP disconnect cleanup: %s", e)
        finally:
            self._session = None
            self._connected = False
            logger.info("MCP bridge disconnected.")

    async def discover_tools(
        self,
        skip_names: set[str] | None = None,
    ) -> list:
        """Discover tools from the MCP server.

        Args:
            skip_names: Tool names to skip (e.g. native
                tools that should take priority).

        Returns:
            List of discovered MCP tool objects.
        """
        if not self._connected or not self._session:
            logger.warning(
                "MCP bridge not connected — no tools discovered."
            )
            return []

        skip = skip_names or set()

        try:
            result = await self._session.list_tools()
            self._tools = []
            self._tool_names = set()

            for tool in result.tools:
                if tool.name in skip:
                    logger.debug(
                        "MCP tool '%s' skipped (native tool exists)",
                        tool.name,
                    )
                    continue
                self._tools.append(tool)
                self._tool_names.add(tool.name)

            logger.info(
                "MCP bridge discovered %d tools (skipped %d collisions)",
                len(self._tools),
                len(skip & {t.name for t in result.tools}),
            )
            return self._tools
        except Exception as e:
            logger.error("MCP tool discovery failed: %s", e)
            return []

    def get_openai_tool_definitions(
        self,
    ) -> list[dict[str, Any]]:
        """Convert MCP tools to OpenAI function format.

        Returns definitions compatible with LiteLLM
        (which translates to Gemini/Claude/GPT format).
        """
        definitions = []
        for tool in self._tools:
            schema = tool.inputSchema or {
                "type": "object",
                "properties": {},
            }
            # Ensure Gemini compatibility
            schema = _ensure_property_types(schema)

            definitions.append(
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": (tool.description or ""),
                        "parameters": schema,
                    },
                }
            )
        return definitions

    def has_tool(self, name: str) -> bool:
        """Check if a tool name is an MCP tool."""
        return name in self._tool_names

    async def execute_tool(
        self,
        name: str,
        arguments: dict[str, Any],
    ) -> str:
        """Execute a tool on the MCP server.

        Returns the result as a string for the AI.
        """
        if not self._connected or not self._session:
            return f"MCP bridge not connected — cannot execute '{name}'."

        try:
            from mcp import types

            result = await self._session.call_tool(
                name, arguments=arguments
            )

            if result.isError:
                parts = _extract_text(result, types)
                return f"MCP tool '{name}' error: {' '.join(parts)}"

            parts = _extract_text(result, types)
            return "\n".join(parts) if parts else "Done."
        except Exception as e:
            return f"MCP tool error ({name}): {e}"

    @property
    def connected(self) -> bool:
        """Whether the MCP bridge is connected."""
        return self._connected

    @property
    def tool_count(self) -> int:
        """Number of discovered MCP tools."""
        return len(self._tools)

    @property
    def tool_names(self) -> list[str]:
        """Names of all discovered MCP tools."""
        return sorted(self._tool_names)


def _extract_text(result, types) -> list[str]:
    """Extract text parts from a CallToolResult."""
    parts: list[str] = []
    for content in result.content:
        if isinstance(content, types.TextContent):
            parts.append(content.text)
        elif isinstance(content, types.ImageContent):
            parts.append(f"[Image: {content.mimeType}]")
        elif isinstance(content, types.EmbeddedResource):
            res = content.resource
            if hasattr(res, "text"):
                parts.append(res.text)
            else:
                parts.append(f"[Resource: {res.uri}]")
    return parts
