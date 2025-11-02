"""Core abstractions for Deepagents message transports.

This module defines the interfaces shared by the various transport
implementations.  Transports expose a small surface area tailored to the
Deepagents runtime – publishing routed messages, emitting lifecycle events,
recording metrics, and subscribing to message streams.  The contracts are kept
light-weight so they can be implemented by both in-memory transports (useful
for tests) and production-grade backends such as Deephaven.
"""

from __future__ import annotations

from dataclasses import dataclass
from queue import Empty, Queue
from threading import Lock
from typing import Any, Callable, Iterable, Mapping, Protocol


class TransportError(RuntimeError):
    """Raised when an operation against a transport fails."""


class TransportSubscriptionProtocol(Protocol):
    """Protocol describing a disposable subscription returned by transports."""

    def close(self) -> None:
        """Cancel the subscription and release any allocated resources."""


class MessageTransport(Protocol):
    """Contract implemented by message bus adapters."""

    def publish_message(self, message: Mapping[str, Any]) -> None:
        """Publish a routed message to the transport."""

    def publish_event(self, event: Mapping[str, Any]) -> None:
        """Emit a lifecycle event describing work performed by the agent."""

    def publish_metrics(self, metrics: Mapping[str, Any]) -> None:
        """Persist aggregated metrics describing agent performance."""

    def subscribe_messages(self, *, filters: Mapping[str, Any] | None = None) -> "TransportSubscription":
        """Subscribe to a stream of routed messages."""

    def close(self) -> None:
        """Dispose of the transport and release held resources."""


@dataclass(slots=True)
class _QueueWatcher:
    """Internal helper representing a queue tied to a subscription filter."""

    queue: Queue[Mapping[str, Any]]
    filter_predicate: Callable[[Mapping[str, Any]], bool]

    def push(self, message: Mapping[str, Any]) -> None:
        """Push a message onto the queue when it passes the predicate."""

        if self.filter_predicate(message):
            self.queue.put(message)


class TransportSubscription:
    """A context-managed wrapper around a subscription queue."""

    def __init__(self, queue: Queue[Mapping[str, Any]], on_close: Callable[[], None] | None = None) -> None:
        self._queue = queue
        self._on_close = on_close
        self._closed = False

    def __enter__(self) -> "TransportSubscription":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # pragma: no cover - standard context protocol
        self.close()

    def __iter__(self) -> Iterable[Mapping[str, Any]]:
        while True:
            yield self.get()

    def get(self, timeout: float | None = None) -> Mapping[str, Any]:
        """Retrieve the next message, optionally waiting up to ``timeout`` seconds."""

        if self._closed:
            raise TransportError("Subscription already closed")
        try:
            return self._queue.get(timeout=timeout)
        except Empty as exc:  # pragma: no cover - exercised indirectly in tests
            msg = "Timed out waiting for a message"
            raise TimeoutError(msg) from exc

    def close(self) -> None:
        """Close the subscription and notify the transport."""

        if self._closed:
            return
        self._closed = True
        if self._on_close is not None:
            self._on_close()


def build_filter_predicate(filters: Mapping[str, Any] | None) -> Callable[[Mapping[str, Any]], bool]:
    """Create a predicate function for filtering routed messages."""

    if not filters:
        return lambda message: True

    def _predicate(message: Mapping[str, Any]) -> bool:
        for key, expected in filters.items():
            if message.get(key) != expected:
                return False
        return True

    return _predicate


class QueueBackedTransport(MessageTransport):
    """Utility base class for transports that multiplex onto in-memory queues."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._watchers: list[_QueueWatcher] = []

    def _broadcast(self, message: Mapping[str, Any]) -> None:
        with self._lock:
            watchers_snapshot = list(self._watchers)
        for watcher in watchers_snapshot:
            watcher.push(message)

    def _create_subscription(
        self,
        *,
        filters: Mapping[str, Any] | None = None,
        on_close: Callable[[Queue[Mapping[str, Any]]], None] | None = None,
        replay: Iterable[Mapping[str, Any]] | None = None,
    ) -> TransportSubscription:
        queue: Queue[Mapping[str, Any]] = Queue()
        predicate = build_filter_predicate(filters)
        watcher = _QueueWatcher(queue=queue, filter_predicate=predicate)

        def _remove() -> None:
            with self._lock:
                if watcher in self._watchers:
                    self._watchers.remove(watcher)
            if on_close is not None:
                on_close(queue)

        with self._lock:
            self._watchers.append(watcher)

        subscription = TransportSubscription(queue, on_close=_remove)

        if replay is not None:
            for message in replay:
                if predicate(message):
                    queue.put(dict(message))

        return subscription

    def close(self) -> None:  # pragma: no cover - default noop, overridable
        with self._lock:
            self._watchers.clear()
