"""Model Context Protocol backed transport primitives."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from queue import Queue
from threading import Event, Lock, Thread
from typing import Any, Callable, Mapping, Protocol

from deepagents.transports.base import (
    MessageTransport,
    TransportError,
    TransportSubscription,
    build_filter_predicate,
)

LOGGER = logging.getLogger(__name__)


class MCPSubscriptionHandle(Protocol):
    """Protocol describing a disposable handle returned by MCP subscriptions."""

    def close(self) -> None:  # pragma: no cover - simple protocol definition
        """Terminate the remote subscription."""


class MCPClientProtocol(Protocol):
    """Subset of the MCP client surface exercised by the transport."""

    def handshake(self) -> Mapping[str, Any]:
        """Perform the initial handshake with the MCP server."""

    def get_tool_schema(self, tool_name: str) -> Mapping[str, Any]:
        """Return the JSON schema describing ``tool_name``."""

    def invoke_tool(self, tool_name: str, arguments: Mapping[str, Any]) -> Mapping[str, Any]:
        """Execute ``tool_name`` with ``arguments`` on the MCP server."""

    def subscribe(
        self,
        tool_name: str,
        arguments: Mapping[str, Any],
        callback: Callable[[Mapping[str, Any]], None],
    ) -> MCPSubscriptionHandle:
        """Register ``callback`` for streaming updates produced by ``tool_name``."""

    def send_heartbeat(self) -> None:
        """Emit a heartbeat ping to keep the MCP session alive."""

    def close(self) -> None:
        """Close the underlying MCP connection."""


@dataclass(slots=True)
class DeephavenMCPTools:
    """Container describing MCP tool identifiers leveraged by the transport."""

    publish_message: str = "deephaven.messages.publish"
    publish_event: str = "deephaven.events.publish"
    publish_metrics: str = "deephaven.metrics.publish"
    subscribe_messages: str = "deephaven.messages.subscribe"
    heartbeat: str | None = "deephaven.heartbeat"


class DeephavenMCPTransport(MessageTransport):
    """Transport implementation that communicates via a Deephaven MCP client."""

    def __init__(
        self,
        client: MCPClientProtocol,
        *,
        tools: DeephavenMCPTools | None = None,
        heartbeat_interval: float = 30.0,
    ) -> None:
        self._client = client
        self._tools = tools or DeephavenMCPTools()
        self._heartbeat_interval = heartbeat_interval
        self._tool_cache: dict[str, Mapping[str, Any]] = {}
        self._subscriptions: dict[TransportSubscription, MCPSubscriptionHandle] = {}
        self._lock = Lock()
        self._closed = False
        self._heartbeat_stop = Event()
        self._heartbeat_thread: Thread | None = None
        self._handshake_metadata: Mapping[str, Any] | None = None

        self._perform_handshake()
        self._warm_tool_cache()
        self._start_heartbeat_loop()

    @property
    def handshake_metadata(self) -> Mapping[str, Any] | None:
        """Expose the handshake metadata returned by the MCP server."""

        return self._handshake_metadata

    def publish_message(self, message: Mapping[str, Any]) -> None:
        self._ensure_open()
        payload = dict(message)
        self._invoke(self._tools.publish_message, payload)

    def publish_event(self, event: Mapping[str, Any]) -> None:
        self._ensure_open()
        payload = dict(event)
        self._invoke(self._tools.publish_event, payload)

    def publish_metrics(self, metrics: Mapping[str, Any]) -> None:
        self._ensure_open()
        payload = dict(metrics)
        self._invoke(self._tools.publish_metrics, payload)

    def subscribe_messages(self, *, filters: Mapping[str, Any] | None = None) -> TransportSubscription:
        self._ensure_open()
        predicate = build_filter_predicate(filters)
        queue: Queue[Mapping[str, Any]] = Queue()

        def _callback(message: Mapping[str, Any]) -> None:
            try:
                if predicate(message):
                    queue.put(dict(message))
            except Exception:  # pragma: no cover - defensive safety for callbacks
                LOGGER.exception("Unhandled exception while processing MCP message callback")

        arguments: dict[str, Any] = {"filters": dict(filters) if filters else {}}
        handle = self._subscribe(self._tools.subscribe_messages, arguments, _callback)

        subscription: TransportSubscription | None = None

        def _on_close() -> None:
            try:
                handle.close()
            except Exception:  # pragma: no cover - remote close best-effort
                LOGGER.warning("Failed to close MCP subscription", exc_info=True)
            with self._lock:
                if subscription is not None:
                    self._subscriptions.pop(subscription, None)

        subscription = TransportSubscription(queue, on_close=_on_close)
        with self._lock:
            self._subscriptions[subscription] = handle
        return subscription

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._heartbeat_stop.set()
        if self._heartbeat_thread is not None:
            self._heartbeat_thread.join(timeout=self._heartbeat_interval or 0.1)
        with self._lock:
            subscriptions_snapshot = list(self._subscriptions.keys())
        for subscription in subscriptions_snapshot:
            subscription.close()
        with self._lock:
            self._subscriptions.clear()
        try:
            self._client.close()
        except Exception:  # pragma: no cover - best effort shutdown
            LOGGER.warning("Error while closing MCP client", exc_info=True)

    # Internal helpers -------------------------------------------------

    def _ensure_open(self) -> None:
        if self._closed:
            raise TransportError("DeephavenMCPTransport is closed")

    def _perform_handshake(self) -> None:
        try:
            self._handshake_metadata = self._client.handshake()
        except Exception as exc:  # pragma: no cover - handshake is validated by tests
            try:
                self._client.close()
            except Exception:  # pragma: no cover - best effort cleanup
                LOGGER.warning("Failed to close MCP client after handshake error", exc_info=True)
            raise TransportError("Failed to handshake with MCP server") from exc

    def _warm_tool_cache(self) -> None:
        for tool_name in self._iter_tool_names():
            self._get_tool_schema(tool_name)

    def _start_heartbeat_loop(self) -> None:
        if self._tools.heartbeat is None or self._heartbeat_interval <= 0:
            return

        def _loop() -> None:
            while not self._heartbeat_stop.wait(self._heartbeat_interval):
                try:
                    self._client.send_heartbeat()
                except Exception:
                    LOGGER.warning("MCP heartbeat failed", exc_info=True)

        self._heartbeat_thread = Thread(target=_loop, name="deephaven-mcp-heartbeat", daemon=True)
        self._heartbeat_thread.start()

    def _invoke(self, tool_name: str, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        try:
            return self._client.invoke_tool(tool_name, payload)
        except Exception as exc:
            msg = f"Failed to invoke MCP tool '{tool_name}'"
            raise TransportError(msg) from exc

    def _subscribe(
        self,
        tool_name: str,
        arguments: Mapping[str, Any],
        callback: Callable[[Mapping[str, Any]], None],
    ) -> MCPSubscriptionHandle:
        try:
            return self._client.subscribe(tool_name, arguments, callback)
        except Exception as exc:
            msg = f"Failed to subscribe using MCP tool '{tool_name}'"
            raise TransportError(msg) from exc

    def _get_tool_schema(self, tool_name: str) -> Mapping[str, Any]:
        with self._lock:
            cached = self._tool_cache.get(tool_name)
        if cached is not None:
            return cached
        try:
            schema = self._client.get_tool_schema(tool_name)
        except Exception as exc:
            msg = f"Failed to fetch schema for MCP tool '{tool_name}'"
            raise TransportError(msg) from exc
        with self._lock:
            self._tool_cache[tool_name] = schema
        return schema

    def _iter_tool_names(self) -> list[str]:
        tool_names = [
            self._tools.publish_message,
            self._tools.publish_event,
            self._tools.publish_metrics,
            self._tools.subscribe_messages,
        ]
        return [name for name in tool_names if name]


__all__ = ["DeephavenMCPTools", "DeephavenMCPTransport", "MCPClientProtocol", "MCPSubscriptionHandle"]
"""Model Context Protocol transport primitives."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping, MutableMapping

from deepagents.transports.base import TransportError

__all__ = ["HandshakeResult", "MCPTransport"]


@dataclass(slots=True)
class HandshakeResult:
    """Normalized handshake response returned by the MCP client."""

    accepted: bool
    session_id: str | None = None
    reason: str | None = None


def _normalize_handshake(value: Any) -> HandshakeResult:
    """Coerce ``value`` into :class:`HandshakeResult`."""

    if isinstance(value, HandshakeResult):
        return value
    if isinstance(value, Mapping):
        return HandshakeResult(
            accepted=bool(value.get("accepted")),
            session_id=value.get("session_id"),
            reason=value.get("reason"),
        )
    accepted = bool(getattr(value, "accepted", False))
    session_id = getattr(value, "session_id", None)
    reason = getattr(value, "reason", None)
    return HandshakeResult(accepted=accepted, session_id=session_id, reason=reason)


def _tool_name(tool: Any) -> str:
    """Return the string name for ``tool``."""

    if isinstance(tool, Mapping):
        return str(tool["name"])
    return str(getattr(tool, "name"))


class MCPTransport:
    """Async transport wrapper around an MCP client instance."""

    def __init__(
        self,
        client: Any,
        *,
        handshake_payload: Mapping[str, Any] | None = None,
        heartbeat_timeout_s: float = 60.0,
        tool_cache_ttl_s: float = 300.0,
        now: Callable[[], float] | None = None,
    ) -> None:
        self._client = client
        self._handshake_payload: Mapping[str, Any] = handshake_payload or {}
        self._heartbeat_timeout_s = heartbeat_timeout_s
        self._tool_cache_ttl_s = tool_cache_ttl_s
        self._now = now or time.monotonic

        self._session_id: str | None = None
        self._connected = False
        self._last_heartbeat_ts: float | None = None
        self._tool_cache: dict[str, Any] = {}
        self._tool_cache_expiry: float | None = None

    @property
    def session_id(self) -> str | None:
        """Return the current MCP session identifier."""

        return self._session_id

    @property
    def connected(self) -> bool:
        """Return ``True`` when the transport has an active session."""

        return self._connected

    def ensure_alive(self) -> None:
        """Raise :class:`TransportError` when the heartbeat has expired."""

        self._ensure_connected()
        if self._last_heartbeat_ts is None:
            return
        now = self._now()
        if now - self._last_heartbeat_ts > self._heartbeat_timeout_s:
            self._connected = False
            raise TransportError("MCP heartbeat timed out")

    async def open(self) -> None:
        """Perform the MCP handshake and establish a session."""

        try:
            result = await self._client.start_session(payload=self._handshake_payload)
        except Exception as exc:  # pragma: no cover - defensive guard
            raise TransportError("Failed to handshake with MCP server") from exc

        handshake = _normalize_handshake(result)
        if not handshake.accepted:
            reason = f": {handshake.reason}" if handshake.reason else ""
            raise TransportError(f"MCP handshake rejected{reason}")

        self._session_id = handshake.session_id
        self._connected = True
        self._last_heartbeat_ts = self._now()
        self._tool_cache.clear()
        self._tool_cache_expiry = None

    async def close(self) -> None:
        """Terminate the MCP session."""

        if not self._connected:
            return
        try:
            await self._client.close_session(session_id=self._session_id)
        finally:
            self._connected = False
            self._session_id = None
            self._tool_cache.clear()
            self._tool_cache_expiry = None

    async def heartbeat(self) -> None:
        """Send a heartbeat to the MCP server and update the timestamp."""

        self._ensure_connected()
        try:
            await self._client.send_heartbeat(session_id=self._session_id)
        except Exception as exc:  # pragma: no cover - defensive guard
            raise TransportError("Failed to send MCP heartbeat") from exc
        self._last_heartbeat_ts = self._now()

    async def get_tool_schema(self, name: str, *, refresh: bool = False) -> Any:
        """Return the cached schema for ``name``, fetching when necessary."""

        self._ensure_connected()
        now = self._now()
        needs_refresh = refresh or not self._tool_cache or (
            self._tool_cache_expiry is not None and now >= self._tool_cache_expiry
        )
        if needs_refresh:
            await self._refresh_tools()

        try:
            tool = self._tool_cache[name]
        except KeyError as exc:  # pragma: no cover - defensive guard
            raise TransportError(f"Unknown MCP tool: {name}") from exc
        return tool

    async def _refresh_tools(self) -> None:
        """Fetch tool definitions from the MCP client and update the cache."""

        try:
            tools: Iterable[Any] = await self._client.get_tools(session_id=self._session_id)
        except Exception as exc:
            raise TransportError("Failed to fetch MCP tools") from exc

        cache: MutableMapping[str, Any] = {}
        for tool in tools:
            cache[_tool_name(tool)] = tool
        self._tool_cache = dict(cache)
        self._tool_cache_expiry = self._now() + self._tool_cache_ttl_s

    def _ensure_connected(self) -> None:
        if not self._connected:
            raise TransportError("MCP transport is not connected")

