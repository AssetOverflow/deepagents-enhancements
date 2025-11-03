"""In-memory message transport implementation."""

from __future__ import annotations

from typing import Any, Mapping

from deepagents.transports.base import QueueBackedTransport, TransportSubscription


class InMemoryTransport(QueueBackedTransport):
    """Simple message transport that stores payloads in local memory."""

    def __init__(self) -> None:
        super().__init__()
        self._messages: list[Mapping[str, Any]] = []
        self._events: list[Mapping[str, Any]] = []
        self._metrics: list[Mapping[str, Any]] = []

    @property
    def messages(self) -> list[Mapping[str, Any]]:
        """Expose the accumulated messages for tests and diagnostics."""

        return list(self._messages)

    @property
    def events(self) -> list[Mapping[str, Any]]:
        return list(self._events)

    @property
    def metrics(self) -> list[Mapping[str, Any]]:
        return list(self._metrics)

    def publish_message(self, message: Mapping[str, Any]) -> None:
        self._messages.append(dict(message))
        self._broadcast(message)

    def publish_event(self, event: Mapping[str, Any]) -> None:
        self._events.append(dict(event))

    def publish_metrics(self, metrics: Mapping[str, Any]) -> None:
        self._metrics.append(dict(metrics))

    def subscribe_messages(self, *, filters: Mapping[str, Any] | None = None) -> TransportSubscription:
        return self._create_subscription(filters=filters, replay=self._messages)
