"""Global pytest fixtures."""

from __future__ import annotations

import importlib
import sys
import types
from functools import lru_cache
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:  # pragma: no cover - typing-only imports
    from collections.abc import Callable, Mapping, Sequence

    from deepagents.integrations.mcp import MCPClient
    from tests.mcp.mock_server import MockMCPServer, MockToolDefinition
else:  # pragma: no cover - runtime fallbacks for postponed annotations
    Callable = Mapping = Sequence = object  # type: ignore[assignment]
    MCPClient = type("_MCPClientStub", (), {})  # type: ignore[assignment]


def _ensure_pydeephaven_stub() -> None:
    module = sys.modules.get("pydeephaven")
    if module is not None and hasattr(module, "dtypes"):
        return

    stub = types.ModuleType("pydeephaven")
    stub.dtypes = types.SimpleNamespace(
        Instant="Instant",
        string="String",
        double="Double",
    )
    stub.Session = type("Session", (), {})
    stub.DHError = type("DHError", (Exception,), {})
    table_module = types.ModuleType("pydeephaven.table")
    stub.table = table_module
    sys.modules["pydeephaven.table"] = table_module
    sys.modules["pydeephaven"] = stub


_ensure_pydeephaven_stub()


def _load_mcp_client() -> type[MCPClient]:
    _ensure_pydeephaven_stub()
    module = importlib.import_module("deepagents.integrations.mcp")
    return module.MCPClient


@lru_cache
def _mock_server_classes() -> tuple[type[MockMCPServer], type[MockToolDefinition]]:
    _ensure_pydeephaven_stub()
    module = importlib.import_module("tests.mcp.mock_server")
    return module.MockMCPServer, module.MockToolDefinition


def _default_mock_tools() -> tuple[MockToolDefinition, ...]:
    _, tool_definition_cls = _mock_server_classes()
    return (
        tool_definition_cls(
            name="echo",
            description="Return the provided payload.",
            input_schema={
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
            handler=lambda payload: {"content": payload.get("text", "")},
        ),
        tool_definition_cls(
            name="stats",
            description="Compute simple statistics for a numeric sequence.",
            input_schema={
                "type": "object",
                "properties": {
                    "values": {
                        "type": "array",
                        "items": {"type": "number"},
                    }
                },
                "required": ["values"],
            },
            handler=_summarise_numbers,
        ),
    )


def _summarise_numbers(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    values = list(payload.get("values", []))
    count = len(values)
    total = float(sum(values)) if values else 0.0
    mean = total / count if count else 0.0
    return {"count": count, "sum": total, "mean": mean}


@pytest.fixture
def mock_mcp_server_factory() -> Callable[[Sequence[MockToolDefinition] | None], MockMCPServer]:
    """Factory fixture returning configured :class:`MockMCPServer` instances."""
    server_cls, _ = _mock_server_classes()

    def factory(tool_definitions: Sequence[MockToolDefinition] | None = None) -> MockMCPServer:
        return server_cls(tuple(tool_definitions) if tool_definitions else _default_mock_tools())

    return factory


@pytest.fixture
def mock_mcp_pair(
    mock_mcp_server_factory: Callable[[Sequence[MockToolDefinition] | None], MockMCPServer]
) -> tuple[MCPClient, MockMCPServer]:
    """Return a tuple of (:class:`MCPClient`, :class:`MockMCPServer`)."""
    server = mock_mcp_server_factory()
    client_cls = _load_mcp_client()
    client = client_cls(server)
    return client, server
