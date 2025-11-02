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
    DeephavenSettings,
    DeephavenTableSettings,
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


def test_load_deephaven_settings_returns_none_without_uri() -> None:
    assert load_deephaven_settings({}) is None
    with pytest.raises(ValueError, match="must be provided"):
        load_deephaven_settings({}, require_uri=True)


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
