"""Utilities for building deterministic in-memory MCP servers for tests."""

from __future__ import annotations

import asyncio
import inspect
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - typing-only imports
    from collections.abc import Callable, Mapping, Sequence
else:  # pragma: no cover - runtime fallbacks for postponed annotations
    Callable = Mapping = Sequence = object  # type: ignore[assignment]

from deepagents.integrations.mcp import MCPTool


@dataclass(slots=True)
class MockToolDefinition:
    """Declarative description of a mock MCP tool."""

    name: str
    description: str
    input_schema: Mapping[str, Any]
    handler: Callable[[Mapping[str, Any]], Any]


@dataclass(slots=True)
class MockToolCall:
    """Record representing a single invocation captured by :class:`MockMCPServer`."""

    name: str
    arguments: Mapping[str, Any]


class MockMCPServer:
    """In-memory implementation of :class:`~deepagents.integrations.mcp.MCPTransport`."""

    def __init__(self, tool_definitions: Sequence[MockToolDefinition]) -> None:
        if not tool_definitions:
            message = "MockMCPServer requires at least one tool definition."
            raise ValueError(message)

        self._tools = {definition.name: definition for definition in tool_definitions}
        if len(self._tools) != len(tool_definitions):
            duplicate_names = sorted(
                name for name, count in _name_counts(tool_definitions).items() if count > 1
            )
            message = f"Duplicate tool names detected: {', '.join(duplicate_names)}"
            raise ValueError(message)

        self._list_tools_calls = 0
        self._calls: list[MockToolCall] = []

    @property
    def list_tools_calls(self) -> int:
        """Return how many times :meth:`list_tools` has been requested."""
        return self._list_tools_calls

    @property
    def calls(self) -> Sequence[MockToolCall]:
        """Return the recorded tool invocations."""
        return list(self._calls)

    async def list_tools(self) -> Sequence[MCPTool]:
        self._list_tools_calls += 1
        await asyncio.sleep(0)  # allow cooperative scheduling in async tests
        return [
            MCPTool(
                name=definition.name,
                description=definition.description,
                input_schema=definition.input_schema,
            )
            for definition in self._tools.values()
        ]

    async def call_tool(self, name: str, *, arguments: Mapping[str, Any] | None = None) -> object:
        if name not in self._tools:
            message = f"Tool '{name}' is not registered in the mock server"
            raise ValueError(message)

        payload = arguments or {}
        self._calls.append(MockToolCall(name=name, arguments=payload))

        result = self._tools[name].handler(payload)
        if inspect.isawaitable(result):
            result = await result
        await asyncio.sleep(0)  # mirror asynchronous scheduling semantics
        return result


def _name_counts(tool_definitions: Sequence[MockToolDefinition]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for definition in tool_definitions:
        counts[definition.name] = counts.get(definition.name, 0) + 1
    return counts


__all__ = ["MockMCPServer", "MockToolCall", "MockToolDefinition"]
