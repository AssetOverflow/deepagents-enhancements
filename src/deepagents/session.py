"""Agent session helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from deepagents.transports import get_transport
from deepagents.transports.base import MessageTransport, TransportSubscription


@dataclass(slots=True)
class AgentSessionConfig:
    """Configuration options when creating an agent session."""

    transport: Mapping[str, Any] | None = None


class AgentSession:
    """Wraps a Deepagents graph instance with transport-backed helpers."""

    def __init__(self, agent: Any, transport: MessageTransport) -> None:
        self._agent = agent
        self._transport = transport

    @property
    def agent(self) -> Any:
        """Expose the underlying LangGraph agent."""

        return self._agent

    @property
    def transport(self) -> MessageTransport:
        return self._transport

    def publish_message(self, message: Mapping[str, Any]) -> None:
        self._transport.publish_message(message)

    def emit_event(self, event: Mapping[str, Any]) -> None:
        self._transport.publish_event(event)

    def record_metrics(self, metrics: Mapping[str, Any]) -> None:
        self._transport.publish_metrics(metrics)

    def subscribe_messages(self, *, filters: Mapping[str, Any] | None = None) -> TransportSubscription:
        return self._transport.subscribe_messages(filters=filters)

    def close(self) -> None:
        self._transport.close()


def create_agent_session(agent: Any, config: AgentSessionConfig | None = None) -> AgentSession:
    """Create an :class:`AgentSession` for ``agent`` using the supplied ``config``."""

    transport = get_transport(config.transport if config else None)
    return AgentSession(agent, transport)


__all__ = ["AgentSession", "AgentSessionConfig", "create_agent_session"]
