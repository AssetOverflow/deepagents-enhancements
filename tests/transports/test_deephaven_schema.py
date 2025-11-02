from __future__ import annotations

from dataclasses import dataclass

import pytest

from deepagents.transports.deephaven_schema import (
    ColumnSpec,
    SchemaBootstrapError,
    TableSpec,
    bootstrap_deephaven_tables,
)


@dataclass
class FakeColumn:
    name: str
    data_type: str


@dataclass
class FakeTable:
    columns: tuple[FakeColumn, ...]


class FakeSession:
    def __init__(self) -> None:
        self.tables: dict[str, FakeTable] = {}

    def open_table(self, name: str) -> FakeTable:
        if name not in self.tables:
            raise KeyError(name)
        return self.tables[name]


BASIC_SPEC = TableSpec(
    name="agent_messages",
    columns=(
        ColumnSpec("ts", "Instant"),
        ColumnSpec("topic", "String"),
    ),
)


def _install_table(session: FakeSession, spec: TableSpec) -> None:
    session.tables[spec.name] = FakeTable(
        tuple(FakeColumn(column.name, column.dtype) for column in spec.columns)
    )


def test_bootstrap_creates_missing_tables() -> None:
    session = FakeSession()
    calls: list[tuple[str, bool]] = []

    def publisher_factory(session: FakeSession, spec: TableSpec, *, replace: bool) -> None:
        calls.append((spec.name, replace))
        _install_table(session, spec)

    result = bootstrap_deephaven_tables(session, table_specs=(BASIC_SPEC,), publisher_factory=publisher_factory)

    assert result == (
        # created once, no updates necessary
        type(result[0])(spec=BASIC_SPEC, created=True, updated=False),
    )
    assert calls == [(BASIC_SPEC.name, False)]


def test_bootstrap_is_idempotent_when_schema_matches() -> None:
    session = FakeSession()
    _install_table(session, BASIC_SPEC)
    calls: list[tuple[str, bool]] = []

    def publisher_factory(session: FakeSession, spec: TableSpec, *, replace: bool) -> None:
        calls.append((spec.name, replace))
        _install_table(session, spec)

    result = bootstrap_deephaven_tables(session, table_specs=(BASIC_SPEC,), publisher_factory=publisher_factory)

    assert result == (
        type(result[0])(spec=BASIC_SPEC, created=False, updated=False),
    )
    assert calls == []


def test_bootstrap_updates_missing_columns() -> None:
    session = FakeSession()
    session.tables[BASIC_SPEC.name] = FakeTable((FakeColumn("ts", "Instant"),))
    calls: list[tuple[str, bool]] = []

    def publisher_factory(session: FakeSession, spec: TableSpec, *, replace: bool) -> None:
        calls.append((spec.name, replace))
        _install_table(session, spec)

    result = bootstrap_deephaven_tables(session, table_specs=(BASIC_SPEC,), publisher_factory=publisher_factory)

    assert result == (
        type(result[0])(spec=BASIC_SPEC, created=False, updated=True),
    )
    assert calls == [(BASIC_SPEC.name, True)]


def test_bootstrap_raises_on_mismatched_type() -> None:
    session = FakeSession()
    session.tables[BASIC_SPEC.name] = FakeTable((FakeColumn("ts", "String"), FakeColumn("topic", "String")))

    with pytest.raises(SchemaBootstrapError):
        bootstrap_deephaven_tables(session, table_specs=(BASIC_SPEC,), publisher_factory=lambda *args, **kwargs: None)


def test_bootstrap_wraps_non_missing_error() -> None:
    class ErrorSession(FakeSession):
        def open_table(self, name: str) -> FakeTable:
            raise RuntimeError("permission denied")

    session = ErrorSession()

    with pytest.raises(SchemaBootstrapError) as excinfo:
        bootstrap_deephaven_tables(session, table_specs=(BASIC_SPEC,), publisher_factory=lambda *args, **kwargs: None)

    assert "permission denied" in str(excinfo.value.__cause__)
