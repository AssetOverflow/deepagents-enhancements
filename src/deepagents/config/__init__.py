"""Configuration helpers for Deephaven-enabled DeepAgents deployments."""

from __future__ import annotations

from dataclasses import dataclass, field
import os
from typing import Any, Mapping, MutableMapping

DEFAULT_MESSAGE_TABLE = "agent_messages"
DEFAULT_EVENT_TABLE = "agent_events"
DEFAULT_METRIC_TABLE = "agent_metrics"
DEFAULT_UPDATE_GRAPH = "graph_default"

_ENV_PREFIX = "DEEPAGENTS_DEEPHAVEN_"


def _coerce_mapping(value: Mapping[str, Any] | None, *, section: str) -> MutableMapping[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        msg = f"'{section}' configuration must be a mapping"
        raise TypeError(msg)
    return dict(value)


@dataclass(slots=True)
class DeephavenAuthSettings:
    """Authentication configuration for Deephaven sessions."""

    method: str = "none"
    api_key: str | None = None
    token: str | None = None
    username: str | None = None
    password: str | None = None

    def validate(self) -> None:
        allowed = {"none", "psk", "token", "userpass"}
        if self.method not in allowed:
            msg = (
                "DeephavenAuthSettings.method must be one of 'none', 'psk', 'token', "
                "or 'userpass'"
            )
            raise ValueError(msg)
        if self.method == "psk" and not self.api_key:
            raise ValueError("api_key is required when auth method is 'psk'")
        if self.method == "token" and not self.token:
            raise ValueError("token is required when auth method is 'token'")
        if self.method == "userpass" and (not self.username or not self.password):
            raise ValueError("username and password are required when auth method is 'userpass'")


@dataclass(slots=True)
class DeephavenTableSettings:
    """Names of Deephaven tables consumed by DeepAgents."""

    messages: str = DEFAULT_MESSAGE_TABLE
    events: str = DEFAULT_EVENT_TABLE
    metrics: str = DEFAULT_METRIC_TABLE

    def validate(self) -> None:
        for attr, value in ("messages", self.messages), ("events", self.events), ("metrics", self.metrics):
            if not value or not value.strip():
                raise ValueError(f"{attr} table name must be a non-empty string")


@dataclass(slots=True)
class DeephavenSettings:
    """Aggregate Deephaven runtime configuration."""

    uri: str
    auth: DeephavenAuthSettings = field(default_factory=DeephavenAuthSettings)
    update_graph: str = DEFAULT_UPDATE_GRAPH
    tables: DeephavenTableSettings = field(default_factory=DeephavenTableSettings)

    def __post_init__(self) -> None:  # pragma: no cover - dataclass safety
        if not self.uri or not self.uri.strip():
            raise ValueError("DeephavenSettings.uri must be provided")
        self.auth.validate()
        self.tables.validate()
        if not self.update_graph or not self.update_graph.strip():
            raise ValueError("update_graph must be a non-empty string")


def load_deephaven_settings(
    config: Mapping[str, Any] | None = None,
    *,
    env: Mapping[str, str] | None = None,
    require_uri: bool = False,
) -> DeephavenSettings | None:
    """Materialize :class:`DeephavenSettings` from mappings and environment variables.

    Args:
        config: Optional nested mapping containing a ``deephaven`` section.
        env: Environment mapping used for fallbacks. Defaults to ``os.environ``.
        require_uri: When ``True``, raise :class:`ValueError` if the Deephaven URI
            is not configured.

    Returns:
        A populated :class:`DeephavenSettings` instance when configuration data is
        available, otherwise ``None``.
    """

    env = dict(env or os.environ)
    root_config = _coerce_mapping(config, section="deephaven")
    if "deephaven" in root_config:
        deephaven_section = _coerce_mapping(root_config["deephaven"], section="deephaven")
    else:
        deephaven_section = root_config

    uri = str(
        deephaven_section.get("uri")
        or env.get(f"{_ENV_PREFIX}URI")
        or ""
    )
    if not uri:
        if require_uri:
            raise ValueError("Deephaven connection URI must be provided via configuration or environment")
        return None

    update_graph = str(
        deephaven_section.get("update_graph")
        or env.get(f"{_ENV_PREFIX}UPDATE_GRAPH")
        or DEFAULT_UPDATE_GRAPH
    )

    auth_section = _coerce_mapping(deephaven_section.get("auth"), section="auth")
    auth_method = str(
        auth_section.get("method")
        or deephaven_section.get("auth_method")
        or env.get(f"{_ENV_PREFIX}AUTH_METHOD")
        or "none"
    )
    auth = DeephavenAuthSettings(
        method=auth_method,
        api_key=auth_section.get("api_key")
        or env.get(f"{_ENV_PREFIX}API_KEY"),
        token=auth_section.get("token")
        or env.get(f"{_ENV_PREFIX}TOKEN"),
        username=auth_section.get("username")
        or env.get(f"{_ENV_PREFIX}USERNAME"),
        password=auth_section.get("password")
        or env.get(f"{_ENV_PREFIX}PASSWORD"),
    )

    tables_section = _coerce_mapping(deephaven_section.get("tables"), section="tables")
    tables = DeephavenTableSettings(
        messages=str(
            tables_section.get("messages")
            or env.get(f"{_ENV_PREFIX}MESSAGES_TABLE")
            or DEFAULT_MESSAGE_TABLE
        ),
        events=str(
            tables_section.get("events")
            or env.get(f"{_ENV_PREFIX}EVENTS_TABLE")
            or DEFAULT_EVENT_TABLE
        ),
        metrics=str(
            tables_section.get("metrics")
            or env.get(f"{_ENV_PREFIX}METRICS_TABLE")
            or DEFAULT_METRIC_TABLE
        ),
    )

    return DeephavenSettings(uri=uri, auth=auth, update_graph=update_graph, tables=tables)


__all__ = [
    "DEFAULT_EVENT_TABLE",
    "DEFAULT_MESSAGE_TABLE",
    "DEFAULT_METRIC_TABLE",
    "DEFAULT_UPDATE_GRAPH",
    "DeephavenAuthSettings",
    "DeephavenSettings",
    "DeephavenTableSettings",
    "load_deephaven_settings",
]
