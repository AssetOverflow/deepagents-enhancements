from collections.abc import Iterable

from langchain_core.tools import StructuredTool

from deepagents.tools import ToolCatalog
from deepagents.tools.deephaven_mcp import MCPAdapterProvider, MCPToolAdapter, MCPToolSchema


class FakeClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, object]]] = []

    async def call_tool(self, server_name: str, tool_name: str, *, arguments):  # pragma: no cover - sync path preferred
        self.calls.append((server_name, tool_name, dict(arguments)))
        return {"status": "ok"}

    def call_tool_sync(self, server_name: str, tool_name: str, *, arguments):
        payload = dict(arguments)
        self.calls.append((server_name, tool_name, payload))
        return {"status": "ok"}


class FakeTransport(MCPAdapterProvider):
    def __init__(self, name: str, schemas: Iterable[MCPToolSchema], client: FakeClient) -> None:
        self.name = name
        self.schemas = list(schemas)
        self.client = client

    def build_tool_adapters(self):
        return [MCPToolAdapter(client=self.client, server_name=self.name, schema=schema) for schema in self.schemas]


def _make_tool(name: str) -> StructuredTool:
    def _func() -> str:
        return name

    return StructuredTool.from_function(name=name, func=_func, description=f"{name} tool")


def test_tool_catalog_merges_local_and_mcp_tools():
    local_tool = _make_tool("local")
    client = FakeClient()
    schemas = [
        MCPToolSchema(
            name="remote",
            description="Remote tool",
            input_schema={"type": "object", "properties": {}},
        )
    ]
    transport = FakeTransport("deephaven", schemas, client)
    catalog = ToolCatalog(local_tools=[local_tool], mcp_transports=[transport])

    tools = catalog.get_tools()
    tool_names = {tool.name if hasattr(tool, "name") else tool.get("name") for tool in tools}
    assert tool_names == {"local", "deephaven:remote"}

    remote_tool = next(tool for tool in tools if getattr(tool, "name", None) == "deephaven:remote")
    result = remote_tool.invoke({})
    assert result == {"status": "ok"}
    assert client.calls == [("deephaven", "remote", {})]


def test_tool_catalog_prefers_local_tools_on_name_collision():
    local_tool = _make_tool("deephaven:remote")
    client = FakeClient()
    schemas = [
        MCPToolSchema(
            name="remote",
            description="Remote tool",
            input_schema={"type": "object", "properties": {}},
        )
    ]
    transport = FakeTransport("deephaven", schemas, client)
    catalog = ToolCatalog(local_tools=[local_tool], mcp_transports=[transport])

    tools = catalog.get_tools()
    names = [tool.name if hasattr(tool, "name") else tool["name"] for tool in tools]
    assert names == ["deephaven:remote"]
    assert client.calls == []
