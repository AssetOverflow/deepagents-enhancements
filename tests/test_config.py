"""Tests for Deephaven configuration helpers."""

from __future__ import annotations

import os

import pytest

from deepagents.config import (
    DEFAULT_EVENT_TABLE,
    DEFAULT_MESSAGE_TABLE,
    DEFAULT_METRIC_TABLE,
    DEFAULT_UPDATE_GRAPH,
    DeephavenAuthSettings,
    DeephavenMCPSettings,
    DeephavenSettings,
    DeephavenTableSettings,
    load_deephaven_mcp_settings,
    load_deephaven_settings,
)


def test_load_deephaven_settings_from_nested_config() -> None:
    settings = load_deephaven_settings(
        {
            "deephaven": {
                "uri": "grpc://deephaven:10000",
                "update_graph": "graph_highfreq",
                "auth": {"method": "psk", "api_key": "secret"},
                "tables": {
                    "messages": "custom_messages",
                    "events": "custom_events",
                    "metrics": "custom_metrics",
                },
            }
        }
    )

    assert settings == DeephavenSettings(
        uri="grpc://deephaven:10000",
        update_graph="graph_highfreq",
        auth=DeephavenAuthSettings(method="psk", api_key="secret"),
        tables=DeephavenTableSettings(
            messages="custom_messages",
            events="custom_events",
            metrics="custom_metrics",
        ),
        mcp_telemetry=DeephavenMCPTelemetrySettings(),
    )


def test_load_deephaven_settings_environment_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEEPAGENTS_DEEPHAVEN_URI", "grpc://localhost:10000")
    monkeypatch.delenv("DEEPAGENTS_DEEPHAVEN_UPDATE_GRAPH", raising=False)
    settings = load_deephaven_settings(env=os.environ)

    assert settings.uri == "grpc://localhost:10000"
    assert settings.update_graph == DEFAULT_UPDATE_GRAPH
    assert settings.tables == DeephavenTableSettings(
        messages=DEFAULT_MESSAGE_TABLE,
        events=DEFAULT_EVENT_TABLE,
        metrics=DEFAULT_METRIC_TABLE,
    )
    assert settings.mcp_telemetry == DeephavenMCPTelemetrySettings()


def test_load_deephaven_settings_with_mcp_telemetry_section() -> None:
    settings = load_deephaven_settings(
        {
            "deephaven": {
                "uri": "grpc://deephaven:10000",
                "mcp_telemetry": {
                    "enabled": True,
                    "inbound_buffer_size": 5,
                    "outbound_buffer_size": 7,
                    "stream_topics": {"alerts": "bus.alerts"},
                    "stream_tables": {"alerts": "alerts_table"},
                },
            }
        }
    )

    assert settings.mcp_telemetry == DeephavenMCPTelemetrySettings(
        enabled=True,
        inbound_buffer_size=5,
        outbound_buffer_size=7,
        stream_topics={"alerts": "bus.alerts"},
        stream_tables={"alerts": "alerts_table"},
    )


def test_load_deephaven_settings_returns_none_without_uri() -> None:
    assert load_deephaven_settings({}) is None
    with pytest.raises(ValueError, match="must be provided"):
        load_deephaven_settings({}, require_uri=True)


def test_load_deephaven_mcp_settings_from_config() -> None:
    settings = load_deephaven_mcp_settings(
        {
            "deephaven_mcp": {
                "url": "https://mcp.example.com",
                "token": "secret-token",
                "use_tls": False,
                "subscription_dir": "/tmp/subscriptions",
            }
        },
        require_url=True,
    )

    assert settings == DeephavenMCPSettings(
        url="https://mcp.example.com",
        token="secret-token",
        use_tls=False,
        subscription_dir="/tmp/subscriptions",
    )


def test_load_deephaven_mcp_settings_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEEPAGENTS_DEEPHAVEN_MCP_URL", "https://env-mcp")
    monkeypatch.setenv("DEEPAGENTS_DEEPHAVEN_MCP_TOKEN", "env-token")
    monkeypatch.setenv("DEEPAGENTS_DEEPHAVEN_MCP_USE_TLS", "0")
    monkeypatch.setenv("DEEPAGENTS_DEEPHAVEN_MCP_SUBSCRIPTION_DIR", "/var/mcp")

    settings = load_deephaven_mcp_settings(env=os.environ, require_url=True)

    assert settings.url == "https://env-mcp"
    assert settings.token == "env-token"
    assert settings.use_tls is False
    assert settings.subscription_dir == "/var/mcp"


def test_load_deephaven_mcp_settings_requires_token() -> None:
    with pytest.raises(ValueError, match="token must be provided"):
        load_deephaven_mcp_settings(
            {
                "deephaven_mcp": {
                    "url": "https://missing-token",
                }
            },
            require_url=True,
        )


@pytest.mark.parametrize(
    "method,kwargs,expected_error",
    [
        ("psk", {"api_key": None}, "api_key"),
        ("token", {"token": None}, "token"),
        ("userpass", {"username": None, "password": "secret"}, "username"),
        ("invalid", {}, "must be one of"),
    ],
)
def test_deephaven_auth_settings_validation(method: str, kwargs: dict[str, str | None], expected_error: str) -> None:
    auth = DeephavenAuthSettings(method=method, **kwargs)
    with pytest.raises(ValueError, match=expected_error):
        DeephavenSettings(uri="grpc://example", auth=auth)
