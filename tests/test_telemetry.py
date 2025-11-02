"""Tests for Deephaven telemetry emitters."""

from __future__ import annotations

from collections.abc import Sequence
from contextlib import AbstractContextManager
from datetime import datetime, timezone
import json
from typing import Any

import pytest

from deepagents.telemetry import ColumnSpec, DeephavenTelemetryEmitter, DEFAULT_EVENT_SCHEMA, DEFAULT_METRIC_SCHEMA


class RecordingWriter(AbstractContextManager["RecordingWriter"]):
    """In-memory Deephaven writer used for testing."""

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


def build_writer_factory(sink: list[RecordingWriter]):
    def _factory(table_name: str, column_names: Sequence[str], column_types: Sequence[Any]) -> RecordingWriter:
        return RecordingWriter(table_name, column_names, column_types, sink)

    return _factory


def test_emit_event_batches_and_uses_schema() -> None:
    sink: list[RecordingWriter] = []
    emitter = DeephavenTelemetryEmitter(
        session=object(),
        agent_events_table="agent_events",
        agent_metrics_table="agent_metrics",
        batch_size=2,
        writer_factory=build_writer_factory(sink),
    )

    ts = datetime(2024, 1, 1, tzinfo=timezone.utc)
    emitter.emit_event(
        timestamp=ts,
        agent_id="agent-1",
        event_type="started",
        payload={"state": "booting", "attempt": 1},
    )

    assert not sink

    emitter.emit_event(
        timestamp=ts,
        agent_id="agent-1",
        event_type="completed",
        run_id="run-123",
        payload={"result": "ok"},
    )

    assert len(sink) == 1
    writer = sink[0]
    assert writer.table_name == "agent_events"
    assert writer.column_names == [column.name for column in DEFAULT_EVENT_SCHEMA]
    assert writer.column_types == [column.dtype for column in DEFAULT_EVENT_SCHEMA]
    assert len(writer.rows) == 2
    first_payload = json.loads(writer.rows[0][4])
    second_payload = json.loads(writer.rows[1][4])
    assert first_payload == {"attempt": 1, "state": "booting"}
    assert second_payload == {"result": "ok"}
    assert writer.rows[1][3] == "run-123"


def test_emit_metric_flushes_on_demand() -> None:
    sink: list[RecordingWriter] = []
    custom_schema = (
        ColumnSpec("timestamp", "Instant"),
        ColumnSpec("agent_id", "String"),
        ColumnSpec("metric_name", "String"),
        ColumnSpec("metric_value", "Double"),
        ColumnSpec("labels_json", "String"),
    )

    emitter = DeephavenTelemetryEmitter(
        session=object(),
        agent_events_table="agent_events",
        agent_metrics_table="agent_metrics",
        batch_size=5,
        metric_schema=custom_schema,
        writer_factory=build_writer_factory(sink),
    )

    ts = datetime(2024, 2, 2, tzinfo=timezone.utc)
    emitter.emit_metric(
        timestamp=ts,
        agent_id="agent-42",
        metric_name="latency_ms",
        metric_value=12.5,
        labels={"stage": "plan", "status": "ok"},
    )

    assert not sink

    emitter.flush()

    assert len(sink) == 1
    writer = sink[0]
    assert writer.table_name == "agent_metrics"
    assert writer.column_names == [column.name for column in custom_schema]
    assert writer.column_types == [column.dtype for column in custom_schema]
    assert writer.rows == [
        (
            ts,
            "agent-42",
            "latency_ms",
            pytest.approx(12.5),
            json.dumps({"stage": "plan", "status": "ok"}, sort_keys=True),
        )
    ]


def test_close_idempotent_flushes_remaining_rows() -> None:
    sink: list[RecordingWriter] = []
    emitter = DeephavenTelemetryEmitter(
        session=object(),
        agent_events_table="agent_events",
        agent_metrics_table="agent_metrics",
        batch_size=10,
        writer_factory=build_writer_factory(sink),
    )

    ts = datetime.now(tz=timezone.utc)
    emitter.emit_event(timestamp=ts, agent_id="a", event_type="heartbeat")
    emitter.emit_metric(timestamp=ts, agent_id="a", metric_name="cpu", metric_value=0.5)

    emitter.close()
    emitter.close()

    assert len(sink) == 2
    event_writer, metric_writer = sink
    assert event_writer.table_name == "agent_events"
    assert metric_writer.table_name == "agent_metrics"
    assert event_writer.rows[0][0] == ts
    assert metric_writer.rows[0][3] == pytest.approx(0.5)
