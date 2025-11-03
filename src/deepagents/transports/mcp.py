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

