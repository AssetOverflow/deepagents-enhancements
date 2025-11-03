"""Adapters for translating Deephaven MCP tool schemas into LangChain tools."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Protocol, Sequence

from pydantic import BaseModel, Field, ValidationError, create_model
from langchain_core.tools import StructuredTool


JSONType = Mapping[str, Any]


class MCPTransportClient(Protocol):
    """Protocol describing the minimal MCP client surface consumed by adapters."""

    async def call_tool(
        self, server_name: str, tool_name: str, *, arguments: Mapping[str, Any]
    ) -> Any:
        """Asynchronously execute ``tool_name`` against ``server_name``."""

    def call_tool_sync(
        self, server_name: str, tool_name: str, *, arguments: Mapping[str, Any]
    ) -> Any:
        """Execute ``tool_name`` synchronously. Optional but enables sync tool usage."""


@dataclass(frozen=True)
class MCPToolSchema:
    """Lightweight representation of an MCP tool definition."""

    name: str
    description: str
    input_schema: Mapping[str, Any]
    output_schema: Mapping[str, Any] | None = None
    metadata: Mapping[str, Any] | None = None


def _map_json_type(schema: Mapping[str, Any]) -> Any:
    """Translate a JSON schema primitive into a Python annotation."""

    schema_type = schema.get("type")
    if isinstance(schema_type, list):
        # Handle nullable schemas expressed as ["null", "type"]
        non_null_types = [t for t in schema_type if t != "null"]
        if len(non_null_types) == 1:
            from typing import Optional

            base = _map_json_type({"type": non_null_types[0], **{k: v for k, v in schema.items() if k != "type"}})
            return Optional[base]
        schema_type = non_null_types[0] if non_null_types else None

    if "enum" in schema:
        from typing import Literal

        enum_values = schema["enum"]
        if isinstance(enum_values, Sequence) and enum_values:
            return Literal[tuple(enum_values)]  # type: ignore[arg-type]

    if schema_type == "string":
        return str
    if schema_type == "integer":
        return int
    if schema_type == "number":
        return float
    if schema_type == "boolean":
        return bool
    if schema_type == "array":
        item_schema = schema.get("items", {})
        item_type = _map_json_type(item_schema) if item_schema else Any
        return list[item_type]  # type: ignore[valid-type]
    if schema_type == "object":
        return dict[str, Any]
    return Any


def _build_model_from_schema(name: str, schema: Mapping[str, Any]) -> type[BaseModel]:
    """Create a Pydantic model mirroring the provided JSON schema."""

    if schema.get("type", "object") != "object":
        # Fallback - represent the entire payload as an opaque mapping
        return create_model(name, __base__=BaseModel, payload=(dict[str, Any], ...))

    properties: Mapping[str, JSONType] = schema.get("properties", {})
    required_fields = set(schema.get("required", []))
    field_definitions: dict[str, tuple[Any, Any]] = {}

    for prop, prop_schema in properties.items():
        annotation = _map_json_type(prop_schema)
        description = prop_schema.get("description")
        default = prop_schema.get("default")
        if prop in required_fields and default is None:
            field_definitions[prop] = (annotation, Field(..., description=description))
        else:
            field_definitions[prop] = (
                annotation,
                Field(default, description=description),
            )

    additional_props = schema.get("additionalProperties", False)
    if additional_props:
        # Permit arbitrary extras when the schema allows additional properties.
        field_definitions["__root__extras"] = (dict[str, Any], Field(default_factory=dict))

    if not field_definitions:
        # Empty schema - allow calls with no parameters.
        return create_model(name, __base__=BaseModel)  # type: ignore[misc]

    model = create_model(  # type: ignore[misc]
        name,
        __base__=BaseModel,
        **field_definitions,
    )
    return model


class MCPToolAdapter:
    """Bridge between MCP tool schemas and LangChain-compatible tools."""

    def __init__(
        self,
        *,
        client: MCPTransportClient,
        server_name: str,
        schema: MCPToolSchema,
    ) -> None:
        self._client = client
        self._server_name = server_name
        self._schema = schema
        self._args_model = _build_model_from_schema(
            f"MCP{server_name.title()}{schema.name.title().replace('_', '')}Input",
            schema.input_schema,
        )
        self._output_model = (
            _build_model_from_schema(
                f"MCP{server_name.title()}{schema.name.title().replace('_', '')}Output",
                schema.output_schema,
            )
            if schema.output_schema
            else None
        )

    @property
    def tool_name(self) -> str:
        """Namespaced tool name used inside DeepAgents."""

        return f"{self._server_name}:{self._schema.name}"

    def _coerce_input(self, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        try:
            model = self._args_model(**payload)
        except ValidationError as exc:  # pragma: no cover - defensive branch
            raise ValueError(f"Invalid arguments for tool '{self.tool_name}': {exc}") from exc
        data = model.model_dump(exclude_none=True)
        data.pop("__root__extras", None)
        return data

    def _coerce_output(self, result: Any) -> Any:
        if self._output_model is None:
            return result
        try:
            model = self._output_model.model_validate(result)
        except ValidationError as exc:
            raise ValueError(
                f"Tool '{self.tool_name}' returned data that does not conform to its output schema: {exc}"
            ) from exc
        return model.model_dump(exclude_none=True)

    def _call_sync(self, arguments: Mapping[str, Any]) -> Any:
        if hasattr(self._client, "call_tool_sync"):
            return self._client.call_tool_sync(
                self._server_name,
                self._schema.name,
                arguments=arguments,
            )

        async def _runner() -> Any:
            return await self._client.call_tool(
                self._server_name,
                self._schema.name,
                arguments=arguments,
            )

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(_runner())
        else:  # pragma: no cover - exercised in async contexts at runtime
            return loop.run_until_complete(_runner())

    def _call_async(self, arguments: Mapping[str, Any]) -> Any:
        return self._client.call_tool(
            self._server_name,
            self._schema.name,
            arguments=arguments,
        )

    def to_tool(self) -> StructuredTool:
        """Materialize the MCP tool as a LangChain ``StructuredTool`` instance."""

        metadata = {
            "source": "mcp",
            "server": self._server_name,
            "original_name": self._schema.name,
        }
        if self._schema.metadata:
            metadata.update(self._schema.metadata)

        def _invoke(runtime=None, **kwargs):
            arguments = self._coerce_input(kwargs)
            result = self._call_sync(arguments)
            return self._coerce_output(result)

        async def _ainvoke(runtime=None, **kwargs):
            arguments = self._coerce_input(kwargs)
            result = await self._call_async(arguments)
            return self._coerce_output(result)

        tool = StructuredTool.from_function(
            name=self.tool_name,
            func=_invoke,
            coroutine=_ainvoke,
            description=self._schema.description,
            args_schema=self._args_model,
        )
        tool.metadata = metadata
        return tool


class MCPAdapterProvider(Protocol):
    """Protocol implemented by MCP transports that expose tool adapters."""

    def build_tool_adapters(self) -> Iterable[MCPToolAdapter]:
        """Return adapters for the currently available MCP tools."""


__all__ = [
    "MCPAdapterProvider",
    "MCPToolAdapter",
    "MCPToolSchema",
    "MCPTransportClient",
]
