from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest

from deepagents.integrations.mcp import MCPClient
from tests.mcp.mock_server import MockMCPServer, MockToolDefinition

if TYPE_CHECKING:  # pragma: no cover - typing-only imports
    from collections.abc import Callable, Sequence
else:  # pragma: no cover - runtime fallbacks for postponed annotations
    Callable = Sequence = object  # type: ignore[assignment]


def test_mock_mcp_fixture_returns_deterministic_tools(mock_mcp_pair: tuple[MCPClient, MockMCPServer]) -> None:
    client, server = mock_mcp_pair

    first = asyncio.run(client.get_tools())
    second = asyncio.run(client.get_tools())

    assert {tool.name for tool in first} == {tool.name for tool in second} == {"echo", "stats"}
    assert server.list_tools_calls == 1


def test_mock_mcp_tool_invocation_records_history(mock_mcp_pair: tuple[MCPClient, MockMCPServer]) -> None:
    client, server = mock_mcp_pair

    result = asyncio.run(client.invoke("echo", arguments={"text": "hello"}))

    assert result == {"content": "hello"}
    assert len(server.calls) == 1
    assert server.calls[0].name == "echo"
    assert server.calls[0].arguments == {"text": "hello"}


def test_mock_mcp_custom_tools(
    mock_mcp_server_factory: Callable[[Sequence[MockToolDefinition] | None], MockMCPServer]
) -> None:
    async def multiply(payload: dict[str, int]) -> dict[str, int]:
        total = 1
        for value in payload.get("values", []):
            total *= value
        return {"product": total}

    server = mock_mcp_server_factory(
        [
            MockToolDefinition(
                name="multiply",
                description="Multiply numeric values together.",
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
                handler=multiply,
            )
        ]
    )

    client = MCPClient(server)
    result = asyncio.run(client.invoke("multiply", arguments={"values": [2, 3, 4]}))

    assert result == {"product": 24}
    assert server.calls[0].arguments == {"values": [2, 3, 4]}


def test_mcp_client_rejects_unknown_tool(mock_mcp_pair: tuple[MCPClient, MockMCPServer]) -> None:
    client, _ = mock_mcp_pair

    with pytest.raises(ValueError, match="Unknown MCP tool 'missing'"):
        asyncio.run(client.invoke("missing"))
