"""Integration-style tests for the MCP stream subscriber."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager
import json
from typing import Any

import pytest

from deepagents.telemetry import (
    DeephavenTelemetryEmitter,
    MCPStreamBridgeConfig,
    MCPStreamSubscriber,
)


class RecordingWriter(AbstractContextManager["RecordingWriter"]):
    """Simple writer stub that records Deephaven writes for assertions."""

    def __init__(
        self,
        table_name: str,
        column_names: Sequence[str],
        column_types: Sequence[Any],
        sink: list["RecordingWriter"],
    ) -> None:
        self.table_name = table_name
        self.column_names = list(column_names)
        self.column_types = list(column_types)
        self.rows: list[tuple[Any, ...]] = []
        self._sink = sink

    def __enter__(self) -> "RecordingWriter":
        self._sink.append(self)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # pragma: no cover - nothing to clean up
        return None

    def write_row(self, *values: Any) -> None:
        self.rows.append(tuple(values))


class FakeSubscription(AbstractContextManager["FakeSubscription"]):
    """Context manager emulating an MCP stream subscription."""

    def __init__(self, stream: str, on_close: Callable[[str], None]) -> None:
        self.stream = stream
        self._on_close = on_close
        self.closed = False

    def __enter__(self) -> "FakeSubscription":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.closed = True
        self._on_close(self.stream)
        return None


class FakeMCPClient:
    """Lightweight MCP client double that drives callbacks synchronously."""

    def __init__(self) -> None:
        self._handlers: dict[str, Callable[[dict[str, Any]], None]] = {}
        self.closed_streams: list[str] = []

    def subscribe_stream(
        self,
        stream: str,
        *,
        params: dict[str, Any] | None,
        on_event: Callable[[dict[str, Any]], None],
    ) -> AbstractContextManager[Any]:
        self._handlers[stream] = on_event
        return FakeSubscription(stream, self.closed_streams.append)

    def push(self, stream: str, payload: dict[str, Any]) -> None:
        handler = self._handlers[stream]
        handler(payload)


@pytest.fixture()
def writer_factory() -> Callable[[str, Sequence[str], Sequence[Any]], RecordingWriter]:
    sink: list[RecordingWriter] = []

    def _factory(table_name: str, column_names: Sequence[str], column_types: Sequence[Any]) -> RecordingWriter:
        return RecordingWriter(table_name, column_names, column_types, sink)

    _factory.sink = sink  # type: ignore[attr-defined]
    return _factory


@pytest.fixture()
def fake_client() -> FakeMCPClient:
    return FakeMCPClient()


def test_stream_updates_flush_to_emitter_and_bus(writer_factory, fake_client: FakeMCPClient) -> None:
    emitter = DeephavenTelemetryEmitter(
        session=object(),
        agent_events_table="agent_events",
        agent_metrics_table="agent_metrics",
        batch_size=1,
        writer_factory=writer_factory,
    )

    bus_events: list[dict[str, Any]] = []
    config = MCPStreamBridgeConfig(
        agent_id="agent-7",
        session_id="session-1",
        run_id="run-9",
        buffer_size=2,
        stream_topics={"alerts": "bus.alerts"},
        stream_tables={"alerts": "custom_events"},
        stream_events={"alerts": "mcp.alerts"},
    )

    subscriber = MCPStreamSubscriber(
        fake_client,
        emitter,
        bridge_config=config,
        bus_publisher=bus_events.append,
    )
    subscriber.subscribe("alerts")

    fake_client.push("alerts", {"severity": "high", "id": 1})
    fake_client.push("alerts", {"severity": "high", "id": 2})

    sink: list[RecordingWriter] = writer_factory.sink  # type: ignore[attr-defined]
    assert len(sink) == 1
    writer = sink[0]
    assert writer.table_name == "custom_events"
    assert len(writer.rows) == 1
    payload = json.loads(writer.rows[0][4])
    assert payload["stream"] == "alerts"
    assert payload["topic"] == "bus.alerts"
    assert payload["updates"] == [
        {"severity": "high", "id": 1},
        {"severity": "high", "id": 2},
    ]

    assert len(bus_events) == 1
    bus_event = bus_events[0]
    assert bus_event["event"] == "mcp.alerts"
    details = json.loads(bus_event["details_json"])
    assert details["topic"] == "bus.alerts"
    assert [item["id"] for item in details["updates"]] == [1, 2]


def test_close_flushes_and_unsubscribes(writer_factory, fake_client: FakeMCPClient) -> None:
    emitter = DeephavenTelemetryEmitter(
        session=object(),
        agent_events_table="agent_events",
        agent_metrics_table="agent_metrics",
        batch_size=1,
        writer_factory=writer_factory,
    )
    bus_events: list[dict[str, Any]] = []
    config = MCPStreamBridgeConfig(agent_id="agent-42", buffer_size=10)
    subscriber = MCPStreamSubscriber(fake_client, emitter, bridge_config=config, bus_publisher=bus_events.append)
    subscriber.subscribe("prices")

    fake_client.push("prices", {"symbol": "AAPL", "price": 198.25})

    subscriber.close()

    sink: list[RecordingWriter] = writer_factory.sink  # type: ignore[attr-defined]
    assert len(sink) == 1
    row = sink[0].rows[0]
    payload = json.loads(row[4])
    assert payload["stream"] == "prices"
    assert payload["updates"] == [{"symbol": "AAPL", "price": 198.25}]
    assert len(bus_events) == 1
    assert fake_client.closed_streams == ["prices"]
