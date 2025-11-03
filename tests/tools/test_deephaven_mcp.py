import asyncio

import pytest

from deepagents.tools.deephaven_mcp import MCPToolAdapter, MCPToolSchema


class FakeClient:
    def __init__(self) -> None:
        self.sync_calls: list[tuple[str, str, dict[str, object]]] = []
        self.async_calls: list[tuple[str, str, dict[str, object]]] = []

    async def call_tool(self, server_name: str, tool_name: str, *, arguments):
        self.async_calls.append((server_name, tool_name, dict(arguments)))
        return {"status": "ok", "rows": [{"value": arguments.get("limit", 0)}]}

    def call_tool_sync(self, server_name: str, tool_name: str, *, arguments):
        payload = dict(arguments)
        self.sync_calls.append((server_name, tool_name, payload))
        return {"status": "ok", "rows": [{"value": payload.get("limit", 0)}]}


def test_mcp_tool_adapter_coerces_input_and_output():
    client = FakeClient()
    schema = MCPToolSchema(
        name="run_query",
        description="Execute a Deephaven query.",
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Query to execute."},
                "limit": {"type": "integer", "description": "Row limit.", "default": 100},
            },
            "required": ["query"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "status": {"type": "string"},
                "rows": {
                    "type": "array",
                    "items": {"type": "object"},
                },
            },
            "required": ["status"],
        },
        metadata={"scope": "deephaven"},
    )
    adapter = MCPToolAdapter(client=client, server_name="deephaven", schema=schema)
    tool = adapter.to_tool()

    assert tool.name == "deephaven:run_query"
    assert tool.metadata["source"] == "mcp"
    assert tool.metadata["server"] == "deephaven"
    assert tool.metadata["scope"] == "deephaven"

    result = tool.invoke({"query": "SELECT * FROM table"})
    assert result == {"status": "ok", "rows": [{"value": 100}]}
    assert client.sync_calls == [
        ("deephaven", "run_query", {"query": "SELECT * FROM table", "limit": 100})
    ]


def test_mcp_tool_adapter_async_invocation():
    client = FakeClient()
    schema = MCPToolSchema(
        name="run_query",
        description="Execute a Deephaven query.",
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer", "default": 10},
            },
            "required": ["query"],
        },
        output_schema={"type": "object", "properties": {"status": {"type": "string"}}},
    )
    adapter = MCPToolAdapter(client=client, server_name="deephaven", schema=schema)
    tool = adapter.to_tool()

    result = asyncio.run(tool.ainvoke({"query": "SELECT 1", "limit": "5"}))
    assert result["status"] == "ok"
    assert client.async_calls == [
        ("deephaven", "run_query", {"query": "SELECT 1", "limit": 5})
    ]


def test_mcp_tool_adapter_validates_output_schema():
    class InvalidClient(FakeClient):
        def call_tool_sync(self, server_name: str, tool_name: str, *, arguments):
            self.sync_calls.append((server_name, tool_name, dict(arguments)))
            return {"rows": []}

    client = InvalidClient()
    schema = MCPToolSchema(
        name="run_query",
        description="Execute a Deephaven query.",
        input_schema={"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
        output_schema={"type": "object", "properties": {"status": {"type": "string"}}, "required": ["status"]},
    )
    adapter = MCPToolAdapter(client=client, server_name="deephaven", schema=schema)
    tool = adapter.to_tool()

    with pytest.raises(ValueError):
        tool.invoke({"query": "SELECT 1"})
