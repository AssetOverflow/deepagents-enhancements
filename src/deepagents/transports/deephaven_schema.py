"""Utilities for bootstrapping Deephaven transport tables."""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

__all__ = [
    "ColumnSpec",
    "TableSpec",
    "SchemaBootstrapError",
    "TableBootstrapResult",
    "DEFAULT_TABLE_SPECS",
    "bootstrap_deephaven_tables",
]


class TableLike(Protocol):
    """Protocol representing the subset of Deephaven table attributes we rely on."""

    @property
    def columns(self) -> Iterable[Any]:  # pragma: no cover - protocol definition
        """Return an iterable of column metadata objects."""


@dataclass(frozen=True, slots=True)
class ColumnSpec:
    """Description of a Deephaven table column."""

    name: str
    dtype: str
    description: str | None = None


@dataclass(frozen=True, slots=True)
class TableSpec:
    """Definition of a table that should exist inside Deephaven."""

    name: str
    columns: tuple[ColumnSpec, ...]
    key_columns: tuple[str, ...] = ()
    description: str | None = None

    def column_types(self) -> Mapping[str, str]:
        """Return a mapping of column names to their expected Deephaven dtypes."""

        return {column.name: column.dtype for column in self.columns}


@dataclass(slots=True)
class TableBootstrapResult:
    """Result metadata returned for each processed table."""

    spec: TableSpec
    created: bool
    updated: bool


class SchemaBootstrapError(RuntimeError):
    """Raised when a schema bootstrap operation cannot be completed."""


DEFAULT_TABLE_SPECS: tuple[TableSpec, ...] = (
    TableSpec(
        name="agent_messages",
        description="Core message bus for Deepagents orchestration",
        columns=(
            ColumnSpec("ts", "Instant"),
            ColumnSpec("ingest_ts", "Instant"),
            ColumnSpec("topic", "String"),
            ColumnSpec("session_id", "String"),
            ColumnSpec("task_id", "String"),
            ColumnSpec("agent_id", "String"),
            ColumnSpec("role", "String"),
            ColumnSpec("msg_type", "String"),
            ColumnSpec("payload_json", "String"),
            ColumnSpec("payload_blob_ref", "String"),
            ColumnSpec("priority", "Int"),
            ColumnSpec("ttl_ms", "Int"),
            ColumnSpec("lease_owner", "String"),
            ColumnSpec("lease_expires_ts", "Instant"),
            ColumnSpec("status", "String"),
        ),
        key_columns=("session_id", "task_id", "ts"),
    ),
    TableSpec(
        name="agent_events",
        description="Append-only audit log of agent lifecycle events",
        columns=(
            ColumnSpec("ts", "Instant"),
            ColumnSpec("agent_id", "String"),
            ColumnSpec("session_id", "String"),
            ColumnSpec("event", "String"),
            ColumnSpec("details_json", "String"),
        ),
    ),
    TableSpec(
        name="agent_metrics",
        description="Rolling aggregates over agent activity",
        columns=(
            ColumnSpec("window_start", "Instant"),
            ColumnSpec("agent_id", "String"),
            ColumnSpec("session_id", "String"),
            ColumnSpec("messages_processed", "Long"),
            ColumnSpec("avg_latency_ms", "Double"),
            ColumnSpec("errors", "Long"),
            ColumnSpec("token_usage", "Long"),
            ColumnSpec("last_update_ts", "Instant"),
        ),
        key_columns=("window_start", "agent_id", "session_id"),
    ),
)


def _normalize_dtype(dtype: Any) -> str:
    """Normalize a Deephaven column type to the canonical string representation."""

    if dtype is None:
        return ""
    if isinstance(dtype, str):
        return dtype
    name = getattr(dtype, "name", None)
    if isinstance(name, str):
        return name
    return str(dtype)


def _table_column_types(table: TableLike) -> Mapping[str, str]:
    """Extract a mapping of column names to dtype strings from a Deephaven table."""

    results: dict[str, str] = {}
    for column in getattr(table, "columns", ()):  # pragma: no cover - simple iteration
        column_name = getattr(column, "name", None)
        if not isinstance(column_name, str):
            continue
        dtype = _normalize_dtype(getattr(column, "data_type", getattr(column, "type", None)))
        results[column_name] = dtype
    return results


class _PublisherFactory(Protocol):
    def __call__(self, session: Any, spec: TableSpec, *, replace: bool) -> None:  # pragma: no cover - protocol
        """Create or update a Deephaven table matching ``spec``."""


def _default_publisher_factory(session: Any, spec: TableSpec, *, replace: bool) -> None:
    """Create or update a Deephaven table using Deephaven's TablePublisher API."""

    try:  # pragma: no cover - exercised indirectly in tests through patching
        from deephaven import DHError
        from deephaven.table import ColumnDefinition, TableDefinition
        from deephaven.table.publisher import TablePublisher
    except ModuleNotFoundError as exc:  # pragma: no cover - environment dependent
        raise SchemaBootstrapError(
            "deephaven package is required to bootstrap tables; install the 'deephaven' extra"
        ) from exc

    try:
        column_defs = [ColumnDefinition.of(spec_column.name, spec_column.dtype) for spec_column in spec.columns]
        table_def = TableDefinition(column_defs)
        publisher = TablePublisher(table_definition=table_def, key_columns=list(spec.key_columns) or None)
        table = publisher.table
        if replace:
            session.table_service.replace_input_table(spec.name, table)
        else:
            session.table_service.publish_input_table(spec.name, table)
    except DHError as exc:  # pragma: no cover - depends on live Deephaven instance
        raise SchemaBootstrapError(f"Failed to {'update' if replace else 'create'} Deephaven table '{spec.name}'") from exc


def _is_missing_table_error(error: Exception) -> bool:
    """Heuristically detect whether an exception indicates a missing table."""

    if isinstance(error, KeyError):
        return True
    message = str(error).lower()
    return "not found" in message or "does not exist" in message


def _open_table(session: Any, table_name: str) -> TableLike | None:
    """Attempt to open a Deephaven table, returning ``None`` when it does not exist."""

    try:
        return session.open_table(table_name)
    except Exception as exc:  # pragma: no cover - execution goes through branches in tests
        if _is_missing_table_error(exc):
            return None
        raise SchemaBootstrapError(f"Failed to inspect Deephaven table '{table_name}'") from exc


def _ensure_table(
    session: Any,
    spec: TableSpec,
    publisher_factory: _PublisherFactory,
) -> TableBootstrapResult:
    existing = _open_table(session, spec.name)
    if existing is None:
        publisher_factory(session, spec, replace=False)
        return TableBootstrapResult(spec=spec, created=True, updated=False)

    column_types = _table_column_types(existing)
    expected = spec.column_types()
    missing_columns = [name for name in expected if name not in column_types]
    mismatched = [
        name for name in expected if name in column_types and column_types[name].lower() != expected[name].lower()
    ]

    if mismatched:
        mismatched_pairs = ", ".join(
            f"{name} (expected {expected[name]}, found {column_types[name]})" for name in mismatched
        )
        raise SchemaBootstrapError(
            f"Existing Deephaven table '{spec.name}' has incompatible columns: {mismatched_pairs}"
        )

    if missing_columns:
        publisher_factory(session, spec, replace=True)
        return TableBootstrapResult(spec=spec, created=False, updated=True)

    return TableBootstrapResult(spec=spec, created=False, updated=False)


def bootstrap_deephaven_tables(
    session: Any,
    *,
    table_specs: Iterable[TableSpec] = DEFAULT_TABLE_SPECS,
    publisher_factory: _PublisherFactory | None = None,
) -> tuple[TableBootstrapResult, ...]:
    """Ensure the canonical Deephaven transport tables exist.

    Args:
        session: A connected Deephaven session or compatible test double exposing
            ``open_table`` and ``table_service`` APIs.
        table_specs: Iterable of table specifications to ensure.
        publisher_factory: Factory responsible for creating or updating tables.
            When ``None`` the Deephaven ``TablePublisher`` implementation is used.

    Returns:
        Tuple with one :class:`TableBootstrapResult` per table.

    Raises:
        SchemaBootstrapError: When a table cannot be inspected or updated.
    """

    factory = publisher_factory or _default_publisher_factory
    results: list[TableBootstrapResult] = []
    for spec in table_specs:
        results.append(_ensure_table(session, spec, factory))
    return tuple(results)
