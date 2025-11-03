from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

import sys
import types

if "pydeephaven" not in sys.modules:
    stub_pydeephaven = types.ModuleType("pydeephaven")
    stub_pydeephaven.__path__ = []  # type: ignore[attr-defined]
    sys.modules["pydeephaven"] = stub_pydeephaven
if "pydeephaven.dtypes" not in sys.modules:
    stub_dtypes = types.ModuleType("pydeephaven.dtypes")
    stub_dtypes.Instant = object()
    stub_dtypes.string = object()
    stub_dtypes.double = object()
    sys.modules["pydeephaven.dtypes"] = stub_dtypes

from deepagents.transports.base import TransportError
from deepagents.transports.mcp import MCPTransport


class FakeClock:
    def __init__(self, *, start: float = 0.0) -> None:
        self._value = start

    def advance(self, delta: float) -> None:
        self._value += delta

    def __call__(self) -> float:
        return self._value


def test_open_performs_handshake_and_marks_connected() -> None:
    clock = FakeClock(start=10.0)
    client = AsyncMock()
    client.start_session.return_value = {"accepted": True, "session_id": "sess-123"}

    transport = MCPTransport(client, handshake_payload={"agent": "alpha"}, now=clock)

    asyncio.run(transport.open())

    client.start_session.assert_awaited_once_with(payload={"agent": "alpha"})
    assert transport.connected is True
    assert transport.session_id == "sess-123"


def test_tool_schema_cache_is_reused_until_expiry() -> None:
    clock = FakeClock()
    client = AsyncMock()
    client.start_session.return_value = {"accepted": True, "session_id": "s-1"}
    client.get_tools.return_value = [
        {"name": "alpha", "schema": {"type": "object"}},
        {"name": "beta", "schema": {"type": "object"}},
    ]

    transport = MCPTransport(client, tool_cache_ttl_s=30.0, now=clock)
    asyncio.run(transport.open())

    schema1 = asyncio.run(transport.get_tool_schema("alpha"))
    schema2 = asyncio.run(transport.get_tool_schema("alpha"))

    assert schema1 is schema2
    client.get_tools.assert_awaited_once_with(session_id="s-1")

    clock.advance(31.0)
    asyncio.run(transport.get_tool_schema("beta"))
    assert client.get_tools.await_count == 2


def test_heartbeat_updates_timestamp_and_detects_timeout() -> None:
    clock = FakeClock()
    client = AsyncMock()
    client.start_session.return_value = {"accepted": True, "session_id": "heartbeat"}
    transport = MCPTransport(client, heartbeat_timeout_s=5.0, now=clock)

    asyncio.run(transport.open())
    transport.ensure_alive()  # should not raise immediately after open

    clock.advance(2.0)
    asyncio.run(transport.heartbeat())
    client.send_heartbeat.assert_awaited_once_with(session_id="heartbeat")
    transport.ensure_alive()

    clock.advance(4.0)
    transport.ensure_alive()

    clock.advance(3.0)
    with pytest.raises(TransportError):
        transport.ensure_alive()


def test_handshake_rejection_raises_transport_error() -> None:
    client = AsyncMock()
    client.start_session.return_value = {"accepted": False, "reason": "invalid token"}

    transport = MCPTransport(client)

    with pytest.raises(TransportError) as excinfo:
        asyncio.run(transport.open())

    assert "invalid token" in str(excinfo.value)


def test_tool_fetch_errors_are_wrapped() -> None:
    clock = FakeClock()
    client = AsyncMock()
    client.start_session.return_value = {"accepted": True, "session_id": "tools"}
    client.get_tools.side_effect = RuntimeError("boom")

    transport = MCPTransport(client, now=clock)
    asyncio.run(transport.open())

    with pytest.raises(TransportError) as excinfo:
        asyncio.run(transport.get_tool_schema("alpha"))

    assert "Failed to fetch MCP tools" in str(excinfo.value)


def test_heartbeat_timeout_occurs_without_refresh() -> None:
    clock = FakeClock()
    client = AsyncMock()
    client.start_session.return_value = {"accepted": True, "session_id": "timeout"}

    transport = MCPTransport(client, heartbeat_timeout_s=1.5, now=clock)
    asyncio.run(transport.open())

    clock.advance(2.0)
    with pytest.raises(TransportError):
        transport.ensure_alive()
