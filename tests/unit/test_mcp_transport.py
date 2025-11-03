"""Unit tests for the Deephaven MCP transport."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable, Mapping

import pytest

from deepagents.transports.base import TransportError
from deepagents.transports.mcp import DeephavenMCPTools, DeephavenMCPTransport


@dataclass
class _FakeSubscriptionHandle:
    callback: Callable[[Mapping[str, Any]], None]
    closed: bool = False

    def close(self) -> None:
        self.closed = True


class _FakeMCPClient:
    def __init__(self) -> None:
        self.handshake_calls = 0
        self.schemas: dict[str, Mapping[str, Any]] = {}
        self.schema_requests: list[str] = []
        self.tool_invocations: list[tuple[str, Mapping[str, Any]]] = []
        self.heartbeat_calls = 0
        self.subscriptions: list[_FakeSubscriptionHandle] = []
        self.closed = False
        self.handshake_error: Exception | None = None

    def handshake(self) -> Mapping[str, Any]:
        self.handshake_calls += 1
        if self.handshake_error is not None:
            raise self.handshake_error
        return {"server": "deephaven-mcp"}

    def get_tool_schema(self, tool_name: str) -> Mapping[str, Any]:
        self.schema_requests.append(tool_name)
        try:
            return self.schemas[tool_name]
        except KeyError as exc:  # pragma: no cover - defensive guard for misconfigured tests
            raise AssertionError(f"Schema for tool '{tool_name}' was not configured") from exc

    def invoke_tool(self, tool_name: str, arguments: Mapping[str, Any]) -> Mapping[str, Any]:
        self.tool_invocations.append((tool_name, dict(arguments)))
        return {"status": "ok"}

    def subscribe(
        self,
        tool_name: str,
        arguments: Mapping[str, Any],
        callback: Callable[[Mapping[str, Any]], None],
    ) -> _FakeSubscriptionHandle:
        handle = _FakeSubscriptionHandle(callback)
        self.subscriptions.append(handle)
        return handle

    def send_heartbeat(self) -> None:
        self.heartbeat_calls += 1

    def close(self) -> None:
        self.closed = True

    def emit(self, payload: Mapping[str, Any]) -> None:
        for handle in list(self.subscriptions):
            if not handle.closed:
                handle.callback(dict(payload))


def _create_transport(
    client: _FakeMCPClient,
    *,
    heartbeat_interval: float = 0.0,
    heartbeat: str | None = None,
) -> DeephavenMCPTransport:
    client.schemas = {
        "deephaven.messages.publish": {"type": "object"},
        "deephaven.events.publish": {"type": "object"},
        "deephaven.metrics.publish": {"type": "object"},
        "deephaven.messages.subscribe": {"type": "object"},
    }
    tools = DeephavenMCPTools(heartbeat=heartbeat)
    return DeephavenMCPTransport(client, tools=tools, heartbeat_interval=heartbeat_interval)


def test_transport_performs_handshake_and_caches_tool_schemas() -> None:
    client = _FakeMCPClient()
    transport = _create_transport(client)

    assert client.handshake_calls == 1
    assert client.schema_requests == [
        "deephaven.messages.publish",
        "deephaven.events.publish",
        "deephaven.metrics.publish",
        "deephaven.messages.subscribe",
    ]

    # Subsequent publishes should reuse the cached schema and only invoke the tool.
    transport.publish_message({"topic": "alpha"})
    assert len(client.schema_requests) == 4
    assert client.tool_invocations[-1][0] == "deephaven.messages.publish"


def test_transport_publish_event_and_metrics() -> None:
    client = _FakeMCPClient()
    transport = _create_transport(client)

    transport.publish_event({"event": "claimed"})
    transport.publish_metrics({"count": 5})

    assert client.tool_invocations[-2:] == [
        ("deephaven.events.publish", {"event": "claimed"}),
        ("deephaven.metrics.publish", {"count": 5}),
    ]


def test_transport_subscription_round_trip_filters_payload() -> None:
    client = _FakeMCPClient()
    transport = _create_transport(client)

    with transport.subscribe_messages(filters={"topic": "alpha"}) as subscription:
        client.emit({"topic": "alpha", "filters": {"topic": "alpha"}})
        received = subscription.get(timeout=0.1)

    assert received["topic"] == "alpha"
    assert received["filters"] == {"topic": "alpha"}
    assert client.subscriptions[0].closed is True


def test_transport_heartbeat_loop_executes_until_closed() -> None:
    client = _FakeMCPClient()
    transport = _create_transport(client, heartbeat_interval=0.01, heartbeat="deephaven.heartbeat")

    # Allow the heartbeat thread to fire a few times.
    time.sleep(0.05)
    transport.close()

    assert client.heartbeat_calls >= 2
    assert client.closed is True


def test_transport_wraps_handshake_errors() -> None:
    client = _FakeMCPClient()
    client.handshake_error = RuntimeError("boom")

    with pytest.raises(TransportError):
        _create_transport(client)

    assert client.closed is True
