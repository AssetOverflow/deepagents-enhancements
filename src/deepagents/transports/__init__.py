"""Transport registry and helper functions."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Mapping

from deepagents.transports.base import MessageTransport
from deepagents.transports.deephaven import DeephavenTables, DeephavenTransport
from deepagents.transports.mcp import DeephavenMCPTools, DeephavenMCPTransport
from deepagents.transports.mcp import MCPTransport
from deepagents.transports.memory import InMemoryTransport

TransportFactory = Callable[[Mapping[str, Any]], MessageTransport]


_REGISTRY: dict[str, TransportFactory] = {}


def register_transport(name: str, factory: TransportFactory) -> None:
    """Register a transport factory under ``name``."""

    _REGISTRY[name] = factory


def get_transport(config: Mapping[str, Any] | None) -> MessageTransport:
    """Instantiate a transport from ``config`` using the registered factories."""

    if not config:
        return InMemoryTransport()

    backend = config.get("backend", "memory")
    factory = _REGISTRY.get(backend)
    if factory is None:
        msg = f"Unknown transport backend: {backend}"
        raise KeyError(msg)
    return factory(config)


def _create_memory_transport(_: Mapping[str, Any]) -> MessageTransport:
    return InMemoryTransport()


def _create_deephaven_transport(config: Mapping[str, Any]) -> MessageTransport:
    session = config.get("session")
    if session is None:
        msg = "Deephaven transport requires a 'session' entry in the config"
        raise ValueError(msg)
    tables_cfg = config.get("tables")
    tables = DeephavenTables(**tables_cfg) if isinstance(tables_cfg, Mapping) else None
    return DeephavenTransport(session=session, tables=tables)


def _create_deephaven_mcp_transport(config: Mapping[str, Any]) -> MessageTransport:
    client = config.get("client")
    if client is None:
        msg = "Deephaven MCP transport requires a 'client' entry in the config"
        raise ValueError(msg)
    tools_cfg = config.get("tools")
    tools = DeephavenMCPTools(**tools_cfg) if isinstance(tools_cfg, Mapping) else None
    heartbeat = float(config.get("heartbeat_interval", 30.0))
    return DeephavenMCPTransport(client=client, tools=tools, heartbeat_interval=heartbeat)


register_transport("memory", _create_memory_transport)
register_transport("deephaven", _create_deephaven_transport)
register_transport("deephaven-mcp", _create_deephaven_mcp_transport)

__all__ = [
    "DeephavenMCPTools",
    "DeephavenMCPTransport",
    "DeephavenTables",
    "DeephavenTransport",
    "InMemoryTransport",
    "MCPTransport",
    "get_transport",
    "register_transport",
]
