"""Deephaven-backed transport adapter for Deepagents."""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping, MutableMapping, Sequence

try:  # pragma: no cover - optional dependency at runtime
    from pydeephaven import DHError, Session
    from pydeephaven import table as dh_table
except Exception:  # pragma: no cover - fallback typing stubs when pydeephaven is absent
    DHError = Exception  # type: ignore[assignment]
    Session = Any  # type: ignore[assignment]
    dh_table = None  # type: ignore[assignment]

try:  # pragma: no cover - convert Deephaven tables to Arrow for polling
    import pyarrow as pa
except Exception:  # pragma: no cover
    pa = None  # type: ignore

try:  # pragma: no cover - optional pandas conversion for convenience
    import pandas as pd
except Exception:  # pragma: no cover
    pd = None  # type: ignore

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class _TableHandles:
    """Cached table and input table handles."""

    messages_table: Any
    messages_input: Any
    events_input: Any
    metrics_input: Any


@dataclass(frozen=True)
class DeephavenBusConfig:
    """Configuration controlling Deephaven bus behaviour."""

    host: str | None = None
    port: int = 10000
    use_https: bool = False
    session_factory: Callable[[], Session] | None = None
    table_namespace: str = ""
    default_ttl_ms: int = 5 * 60 * 1000
    lease_extension_ms: int = 60_000
    heartbeat_interval_s: float = 15.0
    reconnect_backoff: Sequence[float] = (0.25, 0.5, 1.0, 2.0, 5.0)
    max_reconnect_attempts: int | None = None
    poll_interval_s: float = 1.0


class DeephavenSubscription:
    """Subscription handle that continuously polls Deephaven for updates."""

    def __init__(
        self,
        bus: "DeephavenBus",
        *,
        filter_expr: str | None,
        queue_size: int = 0,
        callback: Callable[[list[dict[str, Any]]], None] | None = None,
        poll_interval_s: float | None = None,
    ) -> None:
        self._bus = bus
        self._filter_expr = filter_expr
        self._callback = callback
        self._poll_interval = poll_interval_s or bus.config.poll_interval_s
        from queue import Queue

        self._queue: "Queue[dict[str, Any]]" = Queue(maxsize=queue_size)
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._last_ingest_ns: int | None = None
        self._thread.start()

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                messages = self._bus._fetch_messages(self._filter_expr, self._last_ingest_ns)
                if messages:
                    self._last_ingest_ns = max(msg.get("ingest_ts", 0) or 0 for msg in messages) or self._last_ingest_ns
                    if self._callback:
                        try:
                            self._callback(messages)
                        except Exception:  # pragma: no cover - user callback failure
                            LOGGER.exception("Deephaven subscription callback raised an exception")
                    else:
                        for msg in messages:
                            self._queue.put(msg)
            except Exception:  # pragma: no cover - avoid crashing the subscription loop
                LOGGER.exception("Failed to poll Deephaven subscription")
            self._stop_event.wait(self._poll_interval)

    def get(self, timeout: float | None = None) -> dict[str, Any]:
        """Block until the next message is available."""

        item = self._queue.get(timeout=timeout)
        self._queue.task_done()
        return item

    def close(self, timeout: float | None = None) -> None:
        """Stop the background polling thread."""

        self._stop_event.set()
        self._thread.join(timeout)


class DeephavenBus:
    """Transport implementation backed by Deephaven ticking tables."""

    MESSAGE_SCHEMA: tuple[tuple[str, str], ...] = (
        ("message_id", "string"),
        ("ts", "long"),
        ("ingest_ts", "long"),
        ("topic", "string"),
        ("session_id", "string"),
        ("task_id", "string"),
        ("agent_id", "string"),
        ("role", "string"),
        ("msg_type", "string"),
        ("payload_json", "string"),
        ("payload_blob_ref", "string"),
        ("priority", "int"),
        ("ttl_ms", "int"),
        ("lease_owner", "string"),
        ("lease_expires_ts", "long"),
        ("status", "string"),
        ("heartbeat_ts", "long"),
        ("latency_ms", "double"),
        ("retry_count", "int"),
    )
    EVENT_SCHEMA: tuple[tuple[str, str], ...] = (
        ("ts", "long"),
        ("agent_id", "string"),
        ("session_id", "string"),
        ("event", "string"),
        ("details_json", "string"),
    )
    METRIC_SCHEMA: tuple[tuple[str, str], ...] = (
        ("window_start", "long"),
        ("agent_id", "string"),
        ("session_id", "string"),
        ("messages_processed", "long"),
        ("avg_latency_ms", "double"),
        ("errors", "long"),
        ("token_usage", "long"),
        ("last_update_ts", "long"),
    )

    def __init__(self, config: DeephavenBusConfig) -> None:
        self.config = config
        if not config.session_factory and not config.host:
            raise ValueError("Either session_factory or host must be supplied")

        self._lock = threading.RLock()
        self._session: Session | None = None
        self._tables: _TableHandles | None = None
        self._closed = False
        self._connect_with_retry()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def publish(self, message: Mapping[str, Any]) -> str:
        """Publish a message to the Deephaven bus."""

        msg = dict(message)
        message_id = msg.setdefault("message_id", uuid.uuid4().hex)
        now_ns = self._now_ns()
        msg.setdefault("ts", now_ns)
        msg.setdefault("ingest_ts", now_ns)
        msg.setdefault("priority", 0)
        msg.setdefault("ttl_ms", self.config.default_ttl_ms)
        msg.setdefault("lease_owner", "")
        msg.setdefault("lease_expires_ts", 0)
        msg.setdefault("status", "queued")
        msg.setdefault("heartbeat_ts", now_ns)
        msg.setdefault("latency_ms", 0.0)
        msg.setdefault("retry_count", 0)

        with self._lock:
            tables = self._ensure_tables()
            self._add_rows(tables.messages_input, [msg])
            self._append_event(
                tables,
                event="publish",
                agent_id=msg.get("agent_id"),
                session_id=msg.get("session_id"),
                details={"message_id": message_id, "topic": msg.get("topic")},
            )
        return message_id

    def subscribe(
        self,
        *,
        topic: str | None = None,
        session_id: str | None = None,
        agent_id: str | None = None,
        status: Iterable[str] | None = ("queued", "processing"),
        callback: Callable[[list[dict[str, Any]]], None] | None = None,
        queue_size: int = 0,
        poll_interval_s: float | None = None,
    ) -> DeephavenSubscription:
        """Subscribe to message ticks matching the supplied filters."""

        filters: list[str] = []
        if topic:
            filters.append(f"topic == `{topic}`")
        if session_id:
            filters.append(f"session_id == `{session_id}`")
        if agent_id:
            filters.append(f"agent_id == `{agent_id}`")
        if status:
            status_clause = " || ".join(f"status == `{value}`" for value in status)
            filters.append(f"({status_clause})")
        filter_expr = " && ".join(filters) if filters else None
        return DeephavenSubscription(
            self,
            filter_expr=filter_expr,
            callback=callback,
            queue_size=queue_size,
            poll_interval_s=poll_interval_s,
        )

    def claim(
        self,
        *,
        agent_id: str,
        lease_ms: int | None = None,
        topic: str | None = None,
        session_id: str | None = None,
    ) -> dict[str, Any] | None:
        """Attempt to claim the next available message for processing."""

        with self._lock:
            tables = self._ensure_tables()
            self._expire_leases(tables)
            where_clause = ["status == `queued`"]
            if topic:
                where_clause.append(f"topic == `{topic}`")
            if session_id:
                where_clause.append(f"session_id == `{session_id}`")
            candidates = self._fetch_messages(" && ".join(where_clause))
            if not candidates:
                return None
            candidates.sort(key=lambda row: (-int(row.get("priority", 0) or 0), int(row.get("ts", 0) or 0)))
            selected = candidates[0]
            ttl_ms = int(selected.get("ttl_ms") or self.config.default_ttl_ms)
            now_ns = self._now_ns()
            lease_duration_ms = lease_ms or self.config.lease_extension_ms
            lease_expiration_ns = now_ns + lease_duration_ms * 1_000_000
            selected.update(
                {
                    "status": "processing",
                    "lease_owner": agent_id,
                    "lease_expires_ts": lease_expiration_ns,
                    "heartbeat_ts": now_ns,
                    "ingest_ts": selected.get("ingest_ts", now_ns),
                }
            )
            if ttl_ms and now_ns > selected.get("ts", now_ns) + ttl_ms * 1_000_000:
                selected["status"] = "expired"
            self._add_rows(tables.messages_input, [selected])
            self._append_event(
                tables,
                event="claimed",
                agent_id=agent_id,
                session_id=selected.get("session_id"),
                details={"message_id": selected.get("message_id"), "topic": selected.get("topic")},
            )
            return dict(selected)

    def ack(self, message_id: str, *, agent_id: str | None = None, latency_ms: float | None = None) -> bool:
        """Acknowledge a claimed message."""

        with self._lock:
            tables = self._ensure_tables()
            record = self._get_message_by_id(message_id)
            if not record:
                return False
            record.update(
                {
                    "status": "done",
                    "lease_owner": "",
                    "lease_expires_ts": 0,
                    "heartbeat_ts": self._now_ns(),
                }
            )
            if latency_ms is not None:
                record["latency_ms"] = float(latency_ms)
            self._add_rows(tables.messages_input, [record])
            self._append_event(
                tables,
                event="ack",
                agent_id=agent_id or record.get("agent_id"),
                session_id=record.get("session_id"),
                details={"message_id": message_id},
            )
            self._record_metric(
                tables,
                agent_id=agent_id or record.get("agent_id"),
                session_id=record.get("session_id"),
                latency_ms=record.get("latency_ms"),
                success=True,
            )
            return True

    def nack(self, message_id: str, *, agent_id: str | None = None, reason: str | None = None) -> bool:
        """Return a claimed message to the queue."""

        with self._lock:
            tables = self._ensure_tables()
            record = self._get_message_by_id(message_id)
            if not record:
                return False
            record.update(
                {
                    "status": "queued",
                    "lease_owner": "",
                    "lease_expires_ts": 0,
                    "heartbeat_ts": self._now_ns(),
                    "retry_count": int(record.get("retry_count", 0) or 0) + 1,
                }
            )
            self._add_rows(tables.messages_input, [record])
            self._append_event(
                tables,
                event="nack",
                agent_id=agent_id or record.get("agent_id"),
                session_id=record.get("session_id"),
                details={"message_id": message_id, "reason": reason},
            )
            self._record_metric(
                tables,
                agent_id=agent_id or record.get("agent_id"),
                session_id=record.get("session_id"),
                latency_ms=record.get("latency_ms"),
                success=False,
            )
            return True

    def heartbeat(self, *, agent_id: str, message_id: str, lease_extension_ms: int | None = None) -> bool:
        """Extend the lease for an in-flight message."""

        with self._lock:
            tables = self._ensure_tables()
            record = self._get_message_by_id(message_id)
            if not record:
                return False
            if record.get("lease_owner") != agent_id:
                LOGGER.debug("Skipping heartbeat for %s: not lease owner", message_id)
                return False
            now_ns = self._now_ns()
            extension_ms = lease_extension_ms or self.config.lease_extension_ms
            record.update(
                {
                    "heartbeat_ts": now_ns,
                    "lease_expires_ts": now_ns + extension_ms * 1_000_000,
                }
            )
            self._add_rows(tables.messages_input, [record])
            self._append_event(
                tables,
                event="heartbeat",
                agent_id=agent_id,
                session_id=record.get("session_id"),
                details={"message_id": message_id, "lease_extension_ms": extension_ms},
            )
            return True

    def close(self) -> None:
        """Close the Deephaven session and stop background activity."""

        with self._lock:
            self._closed = True
            if self._session is not None:
                close_fn = getattr(self._session, "close", None)
                try:
                    if callable(close_fn):
                        close_fn()
                except Exception:  # pragma: no cover
                    LOGGER.exception("Failed to close Deephaven session")
            self._session = None
            self._tables = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _ensure_tables(self) -> _TableHandles:
        tables = self._tables
        if tables is not None:
            return tables
        session = self._ensure_session()
        messages_input, messages_table = self._open_or_create_table(
            session,
            name=f"{self.config.table_namespace}agent_messages",
            schema=self.MESSAGE_SCHEMA,
            key_columns=("message_id",),
        )
        events_input, _events_table = self._open_or_create_table(
            session,
            name=f"{self.config.table_namespace}agent_events",
            schema=self.EVENT_SCHEMA,
            key_columns=None,
        )
        metrics_input, _metrics_table = self._open_or_create_table(
            session,
            name=f"{self.config.table_namespace}agent_metrics",
            schema=self.METRIC_SCHEMA,
            key_columns=("window_start", "agent_id", "session_id"),
        )
        tables = _TableHandles(
            messages_table=messages_table,
            messages_input=messages_input,
            events_input=events_input,
            metrics_input=metrics_input,
        )
        self._tables = tables
        return tables

    def _ensure_session(self) -> Session:
        if self._session is not None and self._session_alive(self._session):
            return self._session
        self._connect_with_retry()
        if self._session is None:
            raise RuntimeError("Failed to establish Deephaven session")
        return self._session

    def _connect_with_retry(self) -> None:
        if self._closed:
            raise RuntimeError("DeephavenBus is closed")
        backoff = list(self.config.reconnect_backoff)
        attempt = 0
        while True:
            try:
                self._session = self._connect_once()
                LOGGER.debug("Connected to Deephaven server")
                self._tables = None
                return
            except Exception as exc:  # pragma: no cover - connection failures depend on environment
                attempt += 1
                LOGGER.warning("Failed to connect to Deephaven (attempt %s): %s", attempt, exc)
                if self.config.max_reconnect_attempts and attempt >= self.config.max_reconnect_attempts:
                    raise
                delay = backoff[min(attempt - 1, len(backoff) - 1)] if backoff else 1.0
                time.sleep(delay)

    def _connect_once(self) -> Session:
        if self.config.session_factory:
            return self.config.session_factory()
        kwargs: MutableMapping[str, Any] = {}
        if self.config.use_https:
            kwargs["use_https"] = True
        return Session(host=self.config.host, port=self.config.port, **kwargs)

    def _open_or_create_table(
        self,
        session: Session,
        *,
        name: str,
        schema: Sequence[tuple[str, str]],
        key_columns: Sequence[str] | None,
    ) -> tuple[Any, Any]:
        table_service = getattr(session, "table_service", None)
        if table_service is None:
            raise RuntimeError("pydeephaven Session.table_service is required")
        try:
            table = session.open_table(name)
            input_table = getattr(table_service, "input_table_for", None)
            if callable(input_table):
                input_handle = input_table(name)
            else:
                input_handle = None
            if input_handle is None:
                input_handle = self._create_input_table(table_service, name, schema, key_columns)
            return input_handle, table
        except DHError:
            input_table = self._create_input_table(table_service, name, schema, key_columns)
            table = session.open_table(name)
            return input_table, table

    def _create_input_table(
        self,
        table_service: Any,
        name: str,
        schema: Sequence[tuple[str, str]],
        key_columns: Sequence[str] | None,
    ) -> Any:
        if dh_table is None:
            raise RuntimeError("pydeephaven is required to create Deephaven tables")
        column_defs = []
        for column_name, column_type in schema:
            dtype = self._resolve_column_type(column_type)
            column_defs.append(dh_table.ColumnDefinition(name=column_name, data_type=dtype))
        table_def = dh_table.TableDefinition(columns=column_defs)
        kwargs: dict[str, Any] = {"table_def": table_def}
        if key_columns:
            kwargs["key_columns"] = list(key_columns)
        input_table_factory = getattr(table_service, "input_table", None)
        if not callable(input_table_factory):  # pragma: no cover - depends on pydeephaven version
            raise RuntimeError("Session.table_service.input_table is unavailable")
        input_table = input_table_factory(**kwargs)
        publish = getattr(table_service, "publish_table", None)
        if not callable(publish):  # pragma: no cover
            raise RuntimeError("Session.table_service.publish_table is unavailable")
        underlying = getattr(input_table, "table", input_table)
        publish(name=name, table=underlying)
        return input_table

    def _resolve_column_type(self, column_type: str) -> Any:
        mapping = {
            "string": getattr(dh_table.ColumnType, "STRING", None),
            "long": getattr(dh_table.ColumnType, "LONG", None),
            "int": getattr(dh_table.ColumnType, "INT32", None),
            "double": getattr(dh_table.ColumnType, "DOUBLE", None),
        }
        dtype = mapping.get(column_type)
        if dtype is None:
            raise ValueError(f"Unsupported column type: {column_type}")
        return dtype

    def _add_rows(self, input_table: Any, rows: Sequence[Mapping[str, Any]]) -> None:
        if not rows:
            return
        add_fn = getattr(input_table, "add", None)
        if callable(add_fn):
            add_fn(list(rows))
            return
        add_dicts = getattr(input_table, "add_dicts", None)
        if callable(add_dicts):  # pragma: no cover - compatibility path
            add_dicts(list(rows))
            return
        raise RuntimeError("InputTable does not support add operations")

    def _fetch_messages(self, filter_expr: str | None = None, min_ingest_ns: int | None = None) -> list[dict[str, Any]]:
        table = self._ensure_tables().messages_table
        filtered = table
        if filter_expr:
            where_fn = getattr(filtered, "where", None)
            if callable(where_fn):
                filtered = where_fn(filter_expr)
        static_snapshot = getattr(filtered, "snapshot", None)
        if callable(static_snapshot):
            snapshot = static_snapshot()
        else:
            snapshot = filtered
        records = self._table_to_dicts(snapshot)
        if min_ingest_ns is not None:
            records = [row for row in records if (row.get("ingest_ts") or 0) > min_ingest_ns]
        return records

    def _table_to_dicts(self, table: Any) -> list[dict[str, Any]]:
        if table is None:
            return []
        if hasattr(table, "to_arrow") and callable(table.to_arrow):
            arrow_table = table.to_arrow()
            if pa is not None and isinstance(arrow_table, pa.Table):
                return [dict(zip(arrow_table.column_names, row)) for row in arrow_table.to_pylist()]
            if hasattr(arrow_table, "to_pylist"):
                return [dict(zip(arrow_table.schema.names, row)) for row in arrow_table.to_pylist()]
        if hasattr(table, "to_pandas") and callable(table.to_pandas):
            df = table.to_pandas()
            if pd is not None and isinstance(df, pd.DataFrame):
                return df.to_dict(orient="records")
        if hasattr(table, "to_dict") and callable(table.to_dict):
            data = table.to_dict(orient="records")
            if isinstance(data, list):
                return data
        LOGGER.debug("Falling back to empty snapshot for Deephaven table conversion")
        return []

    def _get_message_by_id(self, message_id: str) -> dict[str, Any] | None:
        records = self._fetch_messages(filter_expr=f"message_id == `{message_id}`")
        return records[0] if records else None

    def _append_event(
        self,
        tables: _TableHandles,
        *,
        event: str,
        agent_id: str | None,
        session_id: str | None,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        payload = {
            "ts": self._now_ns(),
            "agent_id": agent_id or "",
            "session_id": session_id or "",
            "event": event,
            "details_json": json.dumps(details or {}),
        }
        self._add_rows(tables.events_input, [payload])

    def _record_metric(
        self,
        tables: _TableHandles,
        *,
        agent_id: str | None,
        session_id: str | None,
        latency_ms: float | None,
        success: bool,
    ) -> None:
        now_ns = self._now_ns()
        window_start = now_ns - (now_ns % (60_000_000_000))
        payload = {
            "window_start": window_start,
            "agent_id": agent_id or "",
            "session_id": session_id or "",
            "messages_processed": 1 if success else 0,
            "avg_latency_ms": float(latency_ms or 0.0),
            "errors": 0 if success else 1,
            "token_usage": 0,
            "last_update_ts": now_ns,
        }
        self._add_rows(tables.metrics_input, [payload])

    def _expire_leases(self, tables: _TableHandles) -> None:
        now_ns = self._now_ns()
        records = self._fetch_messages("status == `processing`")
        expired = [row for row in records if (row.get("lease_expires_ts") or 0) > 0 and row.get("lease_expires_ts") <= now_ns]
        for row in expired:
            row.update(
                {
                    "status": "expired",
                    "lease_owner": "",
                    "lease_expires_ts": 0,
                    "heartbeat_ts": now_ns,
                }
            )
        if expired:
            self._add_rows(tables.messages_input, expired)
            for row in expired:
                self._append_event(
                    tables,
                    event="timeout",
                    agent_id=row.get("agent_id"),
                    session_id=row.get("session_id"),
                    details={"message_id": row.get("message_id")},
                )

    def _session_alive(self, session: Session) -> bool:
        alive_fn = getattr(session, "is_alive", None)
        if callable(alive_fn):
            try:
                return bool(alive_fn())
            except Exception:  # pragma: no cover
                return False
        ping_fn = getattr(session, "ping", None)
        if callable(ping_fn):
            try:
                ping_fn()
                return True
            except Exception:  # pragma: no cover
                return False
        return True

    @staticmethod
    def _now_ns() -> int:
        return time.time_ns()
