"""Minimal MCP client abstractions used across Deepagents.

The goal for this module is to provide deterministic, easily testable logic that
mirrors a subset of the behaviour offered by full Model Context Protocol (MCP)
clients.  Production integrations can layer richer transports on top of the
:class:`MCPTransport` protocol, while unit tests can exercise the
:class:`MCPClient` against in-memory mocks.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, MutableMapping
else:  # pragma: no cover - runtime fallback for postponed annotations
    Iterable = Mapping = MutableMapping = object


@dataclass(slots=True, frozen=True)
class MCPTool:
    """Metadata describing an MCP tool.

    The structure mirrors the JSON schema typically returned by MCP servers.  A
    small subset of fields is captured here so tests can focus on behaviour
    rather than transport details.
    """

    name: str
    description: str
    input_schema: Mapping[str, Any]


class MCPTransport(Protocol):
    """Transport interface consumed by :class:`MCPClient`."""

    async def list_tools(self) -> Iterable[MCPTool]:  # pragma: no cover - Protocol definition
        """Return metadata for available tools."""

    async def call_tool(
        self, name: str, *, arguments: Mapping[str, object] | None = None
    ) -> object:  # pragma: no cover - Protocol definition
        """Invoke a tool and return the server response."""


class MCPClient:
    """High-level helper for interacting with MCP transports.

    The client performs lightweight tool registry caching and offers ergonomic
    error messages when attempting to invoke unknown tools.  It purposefully
    avoids any transport-specific logic so the same abstraction can power both
    production integrations and hermetic test doubles.
    """

    def __init__(self, transport: MCPTransport) -> None:
        """Initialise a client with the provided transport."""
        self._transport = transport
        self._tool_cache: MutableMapping[str, MCPTool] | None = None

    async def get_tools(self) -> list[MCPTool]:
        """Return the available tools, caching results after the first lookup."""
        if self._tool_cache is None:
            tools = list(await self._transport.list_tools())
            tool_map: dict[str, MCPTool] = {}
            for tool in tools:
                if tool.name in tool_map:
                    message = f"Duplicate MCP tool name detected: {tool.name}"
                    raise ValueError(message)
                tool_map[tool.name] = tool
            self._tool_cache = tool_map
        return list(self._tool_cache.values())

    async def describe_tool(self, name: str) -> MCPTool:
        """Return metadata for a single tool.

        Raises:
            ValueError: if the tool is not registered with the MCP transport.
        """
        tool = (await self._ensure_tool_index()).get(name)
        if tool is None:
            available = ", ".join(sorted(await self._tool_names()))
            message = f"Unknown MCP tool '{name}'. Available tools: {available}"
            raise ValueError(message)
        return tool

    async def invoke(
        self, name: str, *, arguments: Mapping[str, object] | None = None
    ) -> object:
        """Invoke a tool by name using the underlying transport."""
        if name not in await self._tool_names():
            available = ", ".join(sorted(await self._tool_names()))
            message = f"Unknown MCP tool '{name}'. Available tools: {available}"
            raise ValueError(message)
        return await self._transport.call_tool(name, arguments=arguments or {})

    async def _ensure_tool_index(self) -> MutableMapping[str, MCPTool]:
        if self._tool_cache is None:
            await self.get_tools()
        if self._tool_cache is None:  # pragma: no cover - defensive guard
            message = "MCP tool cache failed to initialise"
            raise RuntimeError(message)
        return self._tool_cache

    async def _tool_names(self) -> list[str]:
        index = await self._ensure_tool_index()
        return list(index.keys())
