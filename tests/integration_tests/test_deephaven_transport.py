"""Integration tests for the Deephaven transport."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Callable, Mapping

import pytest

from deepagents import AgentSessionConfig, create_agent_session, create_deep_agent


class _MockSubscription:
    def __init__(self, remove: Callable[[], None]) -> None:
        self._remove = remove
        self.closed = False

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        self._remove()


@dataclass
class _MockDeephavenSession:
    tables: dict[str, list[Mapping[str, Any]]]
    subscribers: dict[str, list[tuple[Callable[[Mapping[str, Any]], None], Mapping[str, Any] | None]]]

    def __init__(self) -> None:
        self.tables = defaultdict(list)
        self.subscribers = defaultdict(list)

    def publish(self, table: str, data: Mapping[str, Any]) -> None:
        row = dict(data)
        self.tables[table].append(row)
        for callback, where in list(self.subscribers[table]):
            if where is None or all(row.get(key) == value for key, value in where.items()):
                callback(row)

    def subscribe(
        self,
        table: str,
        callback: Callable[[Mapping[str, Any]], None],
        *,
        where: Mapping[str, Any] | None = None,
    ) -> _MockSubscription:
        filter_copy = dict(where) if where else None
        self.subscribers[table].append((callback, filter_copy))

        # Replay existing rows that match the filter so subscriptions receive a snapshot.
        for row in self.tables.get(table, []):
            if filter_copy is None or all(row.get(key) == value for key, value in filter_copy.items()):
                callback(row)

        def _remove() -> None:
            try:
                self.subscribers[table].remove((callback, filter_copy))
            except ValueError:
                pass

        return _MockSubscription(_remove)


@pytest.fixture()
def deephaven_session() -> _MockDeephavenSession:
    return _MockDeephavenSession()


def test_deephaven_transport_registration(deephaven_session: _MockDeephavenSession) -> None:
    agent = create_deep_agent()
    session = create_agent_session(
        agent,
        AgentSessionConfig(transport={"backend": "deephaven", "session": deephaven_session}),
    )
    assert session.transport.__class__.__name__ == "DeephavenTransport"


def test_deephaven_publish_subscribe_round_trip(deephaven_session: _MockDeephavenSession) -> None:
    agent = create_deep_agent()
    session = create_agent_session(
        agent,
        AgentSessionConfig(transport={"backend": "deephaven", "session": deephaven_session}),
    )

    message = {
        "topic": "planning",
        "session_id": "abc123",
        "payload_json": "{\"content\": \"Plan\"}",
    }

    with session.subscribe_messages(filters={"topic": "planning"}) as subscription:
        session.publish_message(message)
        received = subscription.get(timeout=0.1)

    assert received == message
    assert deephaven_session.tables["agent_messages"][0] == message


def test_deephaven_events_and_metrics_persist(deephaven_session: _MockDeephavenSession) -> None:
    agent = create_deep_agent()
    session = create_agent_session(
        agent,
        AgentSessionConfig(transport={"backend": "deephaven", "session": deephaven_session}),
    )

    session.emit_event({"event": "claimed", "agent_id": "agent-1"})
    session.record_metrics({"messages_processed": 1, "agent_id": "agent-1"})

    assert deephaven_session.tables["agent_events"][0]["event"] == "claimed"
    assert deephaven_session.tables["agent_metrics"][0]["messages_processed"] == 1
