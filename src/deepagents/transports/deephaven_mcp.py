"""Transport adapter backed by the Deephaven MCP server."""

from __future__ import annotations

from typing import Any, Mapping

from deepagents.config import DeephavenMCPSettings
from deepagents.transports.base import MessageTransport, TransportSubscription
from deepagents.transports.memory import InMemoryTransport

__all__ = ["DeephavenMCPTransport"]


class DeephavenMCPTransport(MessageTransport):
    """Thin wrapper that records Deephaven MCP connection settings."""

    def __init__(
        self,
        *,
        settings: DeephavenMCPSettings,
        delegate: MessageTransport | None = None,
    ) -> None:
        self._settings = settings
        self._delegate: MessageTransport = delegate or InMemoryTransport()

    @property
    def settings(self) -> DeephavenMCPSettings:
        """Expose the structured settings used to configure the transport."""

        return self._settings

    def publish_message(self, message: Mapping[str, Any]) -> None:
        self._delegate.publish_message(message)

    def publish_event(self, event: Mapping[str, Any]) -> None:
        self._delegate.publish_event(event)

    def publish_metrics(self, metrics: Mapping[str, Any]) -> None:
        self._delegate.publish_metrics(metrics)

    def subscribe_messages(self, *, filters: Mapping[str, Any] | None = None) -> TransportSubscription:
        return self._delegate.subscribe_messages(filters=filters)

    def close(self) -> None:
        self._delegate.close()
