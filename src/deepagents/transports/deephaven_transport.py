"""Deephaven transport primitives for Deepagents."""
from __future__ import annotations

from typing import Any, Iterable

from .deephaven_schema import DEFAULT_TABLE_SPECS, TableSpec, bootstrap_deephaven_tables

__all__ = ["DeephavenTransport"]


class DeephavenTransport:
    """Lightweight Deephaven transport that ensures schemas during initialization."""

    def __init__(
        self,
        session: Any,
        *,
        bootstrap: bool = True,
        table_specs: Iterable[TableSpec] = DEFAULT_TABLE_SPECS,
    ) -> None:
        self._session = session
        if bootstrap:
            bootstrap_deephaven_tables(session, table_specs=table_specs)

    @property
    def session(self) -> Any:
        """Return the underlying Deephaven session."""

        return self._session
