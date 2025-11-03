"""Deephaven-backed telemetry emitters."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from contextlib import AbstractContextManager, ExitStack
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from threading import Lock
from typing import Any, Callable, Mapping as MappingType, Protocol

try:
    from pydeephaven import dtypes as dh_dtypes
except Exception:  # pragma: no cover - fallback for optional dependency
    dh_dtypes = None


class _WriterProtocol(Protocol):
    """Protocol for Deephaven table writers used by the telemetry emitter."""

    def write_row(self, *values: Any) -> None:  # pragma: no cover - interface only
        """Append a row to the underlying table."""


WriterFactory = Callable[
    [str, Sequence[str], Sequence[Any]],
    AbstractContextManager[_WriterProtocol],
]


@dataclass(frozen=True)
class ColumnSpec:
    """Specification for Deephaven table columns."""

    name: str
    dtype: Any


def _default_event_schema() -> tuple[ColumnSpec, ...]:
    if dh_dtypes is None:  # pragma: no cover - exercised when dependency unavailable
        return (
            ColumnSpec("timestamp", "Instant"),
            ColumnSpec("agent_id", "String"),
            ColumnSpec("event_type", "String"),
            ColumnSpec("run_id", "String"),
            ColumnSpec("payload_json", "String"),
        )
    return (
        ColumnSpec("timestamp", dh_dtypes.Instant),
        ColumnSpec("agent_id", dh_dtypes.string),
        ColumnSpec("event_type", dh_dtypes.string),
        ColumnSpec("run_id", dh_dtypes.string),
        ColumnSpec("payload_json", dh_dtypes.string),
    )


def _default_metric_schema() -> tuple[ColumnSpec, ...]:
    if dh_dtypes is None:  # pragma: no cover - exercised when dependency unavailable
        return (
            ColumnSpec("timestamp", "Instant"),
            ColumnSpec("agent_id", "String"),
            ColumnSpec("metric_name", "String"),
            ColumnSpec("metric_value", "Double"),
            ColumnSpec("labels_json", "String"),
        )
    return (
        ColumnSpec("timestamp", dh_dtypes.Instant),
        ColumnSpec("agent_id", dh_dtypes.string),
        ColumnSpec("metric_name", dh_dtypes.string),
        ColumnSpec("metric_value", dh_dtypes.double),
        ColumnSpec("labels_json", dh_dtypes.string),
    )


DEFAULT_EVENT_SCHEMA: tuple[ColumnSpec, ...] = _default_event_schema()
DEFAULT_METRIC_SCHEMA: tuple[ColumnSpec, ...] = _default_metric_schema()


class DeephavenTelemetryEmitter:
    """Batching telemetry emitter that writes into Deephaven tables."""

    def __init__(
        self,
        session: Any,
        *,
        agent_events_table: str,
        agent_metrics_table: str,
        batch_size: int = 50,
        event_schema: Sequence[ColumnSpec] | None = None,
        metric_schema: Sequence[ColumnSpec] | None = None,
        writer_factory: WriterFactory | None = None,
    ) -> None:
        if batch_size <= 0:
            msg = "batch_size must be positive"
            raise ValueError(msg)

        self._session = session
        self._agent_events_table = agent_events_table
        self._agent_metrics_table = agent_metrics_table
        self._batch_size = batch_size
        self._event_schema = tuple(event_schema) if event_schema is not None else DEFAULT_EVENT_SCHEMA
        self._metric_schema = tuple(metric_schema) if metric_schema is not None else DEFAULT_METRIC_SCHEMA
        self._writer_factory = writer_factory or self._default_writer_factory
        self._event_buffer: list[dict[str, Any]] = []
        self._metric_buffer: list[dict[str, Any]] = []
        self._lock = Lock()
        self._closed = False

    def _default_writer_factory(
        self, table_name: str, column_names: Sequence[str], column_types: Sequence[Any]
    ) -> AbstractContextManager[_WriterProtocol]:
        batch_writer = getattr(self._session, "batch_table_writer", None)
        if batch_writer is None:  # pragma: no cover - defensive programming
            msg = "Session does not expose batch_table_writer"
            raise AttributeError(msg)
        return batch_writer(table_name, column_names, column_types)

    def emit_event(
        self,
        *,
        timestamp: datetime,
        agent_id: str,
        event_type: str,
        run_id: str | None = None,
        payload: Mapping[str, Any] | None = None,
    ) -> None:
        """Queue an agent event for persistence."""

        event_payload = json.dumps(payload or {}, sort_keys=True, default=str)
        row = {
            "timestamp": timestamp,
            "agent_id": agent_id,
            "event_type": event_type,
            "run_id": run_id,
            "payload_json": event_payload,
        }
        with self._lock:
            self._event_buffer.append(row)
            if len(self._event_buffer) >= self._batch_size:
                self._flush_events_locked()

    def emit_metric(
        self,
        *,
        timestamp: datetime,
        agent_id: str,
        metric_name: str,
        metric_value: float,
        labels: Mapping[str, Any] | None = None,
    ) -> None:
        """Queue an agent metric for persistence."""

        metric_labels = json.dumps(labels or {}, sort_keys=True, default=str)
        row = {
            "timestamp": timestamp,
            "agent_id": agent_id,
            "metric_name": metric_name,
            "metric_value": float(metric_value),
            "labels_json": metric_labels,
        }
        with self._lock:
            self._metric_buffer.append(row)
            if len(self._metric_buffer) >= self._batch_size:
                self._flush_metrics_locked()

    def flush(self) -> None:
        """Flush any buffered telemetry to Deephaven."""

        with self._lock:
            self._flush_events_locked()
            self._flush_metrics_locked()

    def close(self) -> None:
        """Flush remaining telemetry and prevent future writes."""

        with self._lock:
            if self._closed:
                return
            self._flush_events_locked()
            self._flush_metrics_locked()
            self._closed = True

    def __enter__(self) -> "DeephavenTelemetryEmitter":  # pragma: no cover - convenience
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # pragma: no cover - convenience
        self.close()

    def _flush_events_locked(self) -> None:
        if not self._event_buffer:
            return
        rows = self._event_buffer
        self._event_buffer = []
        self._write_rows(self._agent_events_table, self._event_schema, rows)

    def _flush_metrics_locked(self) -> None:
        if not self._metric_buffer:
            return
        rows = self._metric_buffer
        self._metric_buffer = []
        self._write_rows(self._agent_metrics_table, self._metric_schema, rows)

    def _write_rows(
        self,
        table_name: str,
        schema: Sequence[ColumnSpec],
        rows: Sequence[Mapping[str, Any]],
    ) -> None:
        column_names = [column.name for column in schema]
        column_types = [column.dtype for column in schema]
        with self._writer_factory(table_name, column_names, column_types) as writer:
            for row in rows:
                writer.write_row(*(row.get(column) for column in column_names))

    def persist_events(
        self,
        rows: Sequence[Mapping[str, Any]],
        *,
        table_name: str | None = None,
    ) -> None:
        """Immediately persist rows to the events table.

        Args:
            rows: Iterable of mappings matching the configured event schema.
            table_name: Optional override for the destination table. Defaults to
                the primary agent events table configured for the emitter.
        """

        if not rows:
            return
        target_table = table_name or self._agent_events_table
        with self._lock:
            self._write_rows(target_table, self._event_schema, rows)


class MCPStreamClient(Protocol):
    """Protocol describing the minimum MCP stream subscription interface."""

    def subscribe_stream(
        self,
        stream: str,
        *,
        params: MappingType[str, Any] | None,
        on_event: Callable[[MappingType[str, Any]], None],
    ) -> AbstractContextManager[Any]:  # pragma: no cover - runtime contract
        """Subscribe to an MCP stream, invoking ``on_event`` for updates."""


BusPublisher = Callable[[Mapping[str, Any]], None]


@dataclass(slots=True)
class MCPStreamBridgeConfig:
    """Runtime configuration for bridging MCP stream telemetry."""

    agent_id: str
    session_id: str | None = None
    run_id: str | None = None
    buffer_size: int = 10
    stream_topics: Mapping[str, str] | None = None
    stream_tables: Mapping[str, str] | None = None
    stream_events: Mapping[str, str] | None = None

    def resolve_topic(self, stream: str) -> str:
        mapping = self.stream_topics or {}
        return mapping.get(stream, stream)

    def resolve_table(self, stream: str) -> str | None:
        mapping = self.stream_tables or {}
        return mapping.get(stream)

    def resolve_event(self, stream: str) -> str:
        mapping = self.stream_events or {}
        return mapping.get(stream, f"mcp.stream.{stream}")


class MCPStreamSubscriber:
    """Fan out MCP stream updates to Deephaven tables and the message bus."""

    def __init__(
        self,
        client: MCPStreamClient,
        emitter: DeephavenTelemetryEmitter,
        *,
        bridge_config: MCPStreamBridgeConfig,
        bus_publisher: BusPublisher | None = None,
    ) -> None:
        if bridge_config.buffer_size <= 0:
            msg = "buffer_size must be positive"
            raise ValueError(msg)

        self._client = client
        self._emitter = emitter
        self._config = bridge_config
        self._bus_publisher = bus_publisher
        self._buffers: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
        self._subscriptions: dict[str, AbstractContextManager[Any]] = {}
        self._stack = ExitStack()

    def subscribe(self, stream: str, *, params: Mapping[str, Any] | None = None) -> None:
        """Subscribe to a single MCP stream and start buffering events."""

        if stream in self._subscriptions:
            return

        def _handler(payload: Mapping[str, Any]) -> None:
            self._handle_event(stream, payload)

        subscription = self._client.subscribe_stream(stream, params=params, on_event=_handler)
        entered = self._stack.enter_context(subscription)
        # Some MCP clients may return auxiliary objects when entering the context.
        self._subscriptions[stream] = subscription
        if entered is not None:
            # Entered value is ignored; ``on_event`` drives the workflow.
            _ = entered

    def _handle_event(self, stream: str, payload: Mapping[str, Any]) -> None:
        buffer = self._buffers[stream]
        buffer.append(dict(payload))
        if len(buffer) >= self._config.buffer_size:
            self._flush_stream(stream)

    def _flush_stream(self, stream: str) -> None:
        buffer = self._buffers.get(stream)
        if not buffer:
            return
        rows = [
            {
                "timestamp": datetime.now(timezone.utc),
                "agent_id": self._config.agent_id,
                "event_type": self._config.resolve_event(stream),
                "run_id": self._config.run_id,
                "payload_json": json.dumps(
                    {
                        "stream": stream,
                        "topic": self._config.resolve_topic(stream),
                        "updates": buffer,
                    },
                    sort_keys=True,
                    default=str,
                ),
            }
        ]

        table_override = self._config.resolve_table(stream)
        self._emitter.persist_events(rows, table_name=table_override)

        if self._bus_publisher is not None:
            event_payload = json.dumps(
                {
                    "stream": stream,
                    "topic": self._config.resolve_topic(stream),
                    "updates": buffer,
                },
                sort_keys=True,
                default=str,
            )
            bus_event = {
                "ts": self._now_ns(),
                "agent_id": self._config.agent_id,
                "session_id": self._config.session_id or "",
                "event": self._config.resolve_event(stream),
                "details_json": event_payload,
            }
            self._bus_publisher(bus_event)

        self._buffers[stream] = []

    def flush(self) -> None:
        """Flush all buffered stream updates."""

        for stream in list(self._buffers):
            self._flush_stream(stream)

    def close(self) -> None:
        """Flush buffered telemetry and release all subscriptions."""

        try:
            self.flush()
        finally:
            self._stack.close()
            self._subscriptions.clear()

    def __enter__(self) -> "MCPStreamSubscriber":  # pragma: no cover - convenience
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # pragma: no cover - convenience
        self.close()

    @staticmethod
    def _now_ns() -> int:
        return int(datetime.now(timezone.utc).timestamp() * 1_000_000_000)
