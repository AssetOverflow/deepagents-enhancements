"""Transport registry and helper functions."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Mapping

from deepagents.transports.base import MessageTransport
from deepagents.config import load_deephaven_mcp_settings
from deepagents.transports.deephaven import DeephavenTables, DeephavenTransport
from deepagents.transports.deephaven_mcp import DeephavenMCPTransport
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
    settings = load_deephaven_mcp_settings(config, require_url=True)
    if settings is None:  # pragma: no cover - defensive, require_url enforces URL
        msg = "Deephaven MCP settings could not be loaded"
        raise ValueError(msg)
    return DeephavenMCPTransport(settings=settings)


register_transport("memory", _create_memory_transport)
register_transport("deephaven", _create_deephaven_transport)
register_transport("deephaven_mcp", _create_deephaven_mcp_transport)

__all__ = [
    "DeephavenMCPTransport",
    "DeephavenTables",
    "DeephavenTransport",
    "InMemoryTransport",
    "MCPTransport",
    "get_transport",
    "register_transport",
]
