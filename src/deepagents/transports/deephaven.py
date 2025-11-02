"""Deephaven-backed transport implementation."""

from __future__ import annotations

from dataclasses import dataclass
from queue import Queue
from typing import Any, Callable, Mapping, Protocol

from deepagents.transports.base import MessageTransport, TransportSubscription, build_filter_predicate


class DeephavenSubscription(Protocol):
    """Protocol describing the handle returned by Deephaven subscriptions."""

    def close(self) -> None:  # pragma: no cover - simple Protocol definition
        """Terminate the subscription."""


class DeephavenSession(Protocol):
    """Subset of ``pydeephaven.Session`` leveraged by the transport."""

    def publish(self, table: str, data: Mapping[str, Any]) -> None:
        """Append a single row to ``table``."""

    def subscribe(
        self,
        table: str,
        callback: Callable[[Mapping[str, Any]], None],
        *,
        where: Mapping[str, Any] | None = None,
    ) -> DeephavenSubscription:
        """Subscribe to updates on ``table`` and return a disposable handle."""


@dataclass(slots=True)
class DeephavenTables:
    """Configuration describing table names used by the transport."""

    messages: str = "agent_messages"
    events: str = "agent_events"
    metrics: str = "agent_metrics"


class DeephavenTransport(MessageTransport):
    """Transport that persists data to Deephaven tables."""

    def __init__(self, *, session: DeephavenSession, tables: DeephavenTables | None = None) -> None:
        self._session = session
        self._tables = tables or DeephavenTables()
        self._subscriptions: list[TransportSubscription] = []

    def publish_message(self, message: Mapping[str, Any]) -> None:
        self._session.publish(self._tables.messages, message)

    def publish_event(self, event: Mapping[str, Any]) -> None:
        self._session.publish(self._tables.events, event)

    def publish_metrics(self, metrics: Mapping[str, Any]) -> None:
        self._session.publish(self._tables.metrics, metrics)

    def subscribe_messages(self, *, filters: Mapping[str, Any] | None = None) -> TransportSubscription:
        predicate = build_filter_predicate(filters)
        queue: Queue[Mapping[str, Any]] = Queue()

        def _callback(message: Mapping[str, Any]) -> None:
            if predicate(message):
                queue.put(dict(message))

        subscription_handle = self._session.subscribe(
            self._tables.messages,
            _callback,
            where=filters,
        )

        subscription: TransportSubscription | None = None

        def _on_close() -> None:
            subscription_handle.close()
            if subscription is not None and subscription in self._subscriptions:
                self._subscriptions.remove(subscription)

        subscription = TransportSubscription(queue, on_close=_on_close)
        self._subscriptions.append(subscription)
        return subscription

    def close(self) -> None:
        for subscription in list(self._subscriptions):
            subscription.close()
        self._subscriptions.clear()
