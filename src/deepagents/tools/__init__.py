"""Utilities for working with DeepAgents tool catalogs."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from typing import Any, Mapping, Protocol, runtime_checkable

from langchain_core.tools import BaseTool

from deepagents.tools.deephaven_mcp import MCPAdapterProvider

ToolLike = BaseTool | Callable[..., Any] | Mapping[str, Any]


@runtime_checkable
class ToolProvider(Protocol):
    """Protocol describing an object capable of yielding tools on demand."""

    def get_tools(self) -> Sequence[ToolLike]:
        """Return a sequence of tools."""


class StaticToolProvider(ToolProvider):
    """Provider that always returns the same collection of tools."""

    def __init__(self, tools: Sequence[ToolLike] | None = None) -> None:
        self._tools = list(tools or [])

    def get_tools(self) -> Sequence[ToolLike]:
        return list(self._tools)


class CallableToolProvider(ToolProvider):
    """Provider backed by a factory callable returning tool collections."""

    def __init__(self, factory: Callable[[], Iterable[ToolLike]]) -> None:
        self._factory = factory

    def get_tools(self) -> Sequence[ToolLike]:
        tools = list(self._factory())
        return tools


def _tool_name(tool: ToolLike) -> str | None:
    if isinstance(tool, Mapping):
        name = tool.get("name")
    elif isinstance(tool, BaseTool):
        name = tool.name
    else:
        name = getattr(tool, "name", None) or getattr(tool, "__name__", None)
    return str(name) if name else None


def _deduplicate_tools(tools: Iterable[ToolLike]) -> list[ToolLike]:
    seen: set[str] = set()
    ordered: list[ToolLike] = []
    for tool in tools:
        name = _tool_name(tool)
        if name is None or name not in seen:
            if name:
                seen.add(name)
            ordered.append(tool)
    return ordered


class ToolCatalog(ToolProvider):
    """Composite provider that merges local tools with MCP-provided adapters."""

    def __init__(
        self,
        *,
        local_tools: ToolProvider | Sequence[ToolLike] | None = None,
        mcp_transports: Iterable[MCPAdapterProvider] | None = None,
    ) -> None:
        self._local_provider = ensure_tool_provider(local_tools)
        self._mcp_providers = list(mcp_transports or [])

    def add_mcp_transport(self, transport: MCPAdapterProvider) -> None:
        """Register an additional MCP transport provider."""

        self._mcp_providers.append(transport)

    def get_tools(self) -> list[ToolLike]:
        tools: list[ToolLike] = list(self._local_provider.get_tools())
        for transport in self._mcp_providers:
            adapters = list(transport.build_tool_adapters())
            tools.extend(adapter.to_tool() for adapter in adapters)
        return _deduplicate_tools(tools)


def ensure_tool_provider(
    tools: ToolProvider | Sequence[ToolLike] | None,
) -> ToolProvider:
    """Normalize ``tools`` into a :class:`ToolProvider`."""

    if isinstance(tools, ToolProvider):
        return tools
    if tools is None:
        return StaticToolProvider([])
    if isinstance(tools, Sequence):
        return StaticToolProvider(tools)
    msg = "Tools must be provided as a sequence or ToolProvider"
    raise TypeError(msg)


__all__ = [
    "CallableToolProvider",
    "ToolCatalog",
    "ToolLike",
    "ToolProvider",
    "StaticToolProvider",
    "ensure_tool_provider",
]
