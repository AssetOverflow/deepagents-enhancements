"""Configuration helpers for Deephaven-enabled DeepAgents deployments."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from typing import Any, Mapping, MutableMapping

DEFAULT_MESSAGE_TABLE = "agent_messages"
DEFAULT_EVENT_TABLE = "agent_events"
DEFAULT_METRIC_TABLE = "agent_metrics"
DEFAULT_UPDATE_GRAPH = "graph_default"

_ENV_PREFIX = "DEEPAGENTS_DEEPHAVEN_"
_MCP_ENV_PREFIX = "DEEPAGENTS_DEEPHAVEN_MCP_"


def _coerce_mapping(value: Mapping[str, Any] | None, *, section: str) -> MutableMapping[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        msg = f"'{section}' configuration must be a mapping"
        raise TypeError(msg)
    return dict(value)


def _coerce_bool(value: Any, *, default: bool) -> bool:
    """Coerce ``value`` into a boolean while supporting string representations."""

    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    msg = "Boolean configuration values must be boolean-like (true/false, 1/0, yes/no)"
    raise ValueError(msg)


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
class DeephavenMCPTelemetrySettings:
    """Configuration controlling MCP stream telemetry fan-out."""

    enabled: bool = False
    inbound_buffer_size: int = 25
    outbound_buffer_size: int = 25
    stream_topics: MutableMapping[str, str] = field(default_factory=dict)
    stream_tables: MutableMapping[str, str] = field(default_factory=dict)

    def validate(self) -> None:
        if self.inbound_buffer_size <= 0:
            raise ValueError("inbound_buffer_size must be positive")
        if self.outbound_buffer_size <= 0:
            raise ValueError("outbound_buffer_size must be positive")


@dataclass(slots=True)
class DeephavenSettings:
    """Aggregate Deephaven runtime configuration."""

    uri: str
    auth: DeephavenAuthSettings = field(default_factory=DeephavenAuthSettings)
    update_graph: str = DEFAULT_UPDATE_GRAPH
    tables: DeephavenTableSettings = field(default_factory=DeephavenTableSettings)
    mcp_telemetry: DeephavenMCPTelemetrySettings = field(default_factory=DeephavenMCPTelemetrySettings)

    def __post_init__(self) -> None:  # pragma: no cover - dataclass safety
        if not self.uri or not self.uri.strip():
            raise ValueError("DeephavenSettings.uri must be provided")
        self.auth.validate()
        self.tables.validate()
        if not self.update_graph or not self.update_graph.strip():
            raise ValueError("update_graph must be a non-empty string")
        self.mcp_telemetry.validate()


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

    mcp_section = _coerce_mapping(deephaven_section.get("mcp_telemetry"), section="mcp_telemetry")
    env_mcp_prefix = f"{_ENV_PREFIX}MCP_TELEMETRY_"
    stream_topics = _coerce_mapping(
            mcp_section.get("stream_topics"),
            section="stream_topics",
        ) or _parse_mapping_string(env.get(f"{env_mcp_prefix}STREAM_TOPICS"), section="stream_topics")


    stream_tables = _coerce_mapping(
            mcp_section.get("stream_tables"),
            section="stream_tables",
        ) or _parse_mapping_string(env.get(f"{env_mcp_prefix}STREAM_TABLES"), section="stream_tables")


    env_enabled_raw = env.get(f"{env_mcp_prefix}ENABLED")
    env_enabled = _coerce_bool(env_enabled_raw, default=False) if env_enabled_raw is not None else False
    inbound_buffer_value = mcp_section.get("inbound_buffer_size")
    if inbound_buffer_value is None:
        inbound_buffer_value = env.get(f"{env_mcp_prefix}INBOUND_BUFFER_SIZE")
    outbound_buffer_value = mcp_section.get("outbound_buffer_size")
    if outbound_buffer_value is None:
        outbound_buffer_value = env.get(f"{env_mcp_prefix}OUTBOUND_BUFFER_SIZE")

    mcp_settings = DeephavenMCPTelemetrySettings(
        enabled=_coerce_bool(mcp_section.get("enabled"), default=env_enabled),
        inbound_buffer_size=int(inbound_buffer_value or 25),
        outbound_buffer_size=int(outbound_buffer_value or 25),
        stream_topics=stream_topics,
        stream_tables=stream_tables,
    )

    return DeephavenSettings(
        uri=uri,
        auth=auth,
        update_graph=update_graph,
        tables=tables,
        mcp_telemetry=mcp_settings,
    )


@dataclass(slots=True)
class DeephavenMCPSettings:
    """Configuration required to communicate with the Deephaven MCP server."""

    url: str
    token: str
    use_tls: bool = True
    subscription_dir: str | None = None

    def __post_init__(self) -> None:  # pragma: no cover - dataclass safety
        if not self.url or not self.url.strip():
            raise ValueError("DeephavenMCPSettings.url must be provided")
        if not self.token or not self.token.strip():
            raise ValueError("DeephavenMCPSettings.token must be provided")


def load_deephaven_mcp_settings(
    config: Mapping[str, Any] | None = None,
    *,
    env: Mapping[str, str] | None = None,
    require_url: bool = False,
) -> DeephavenMCPSettings | None:
    """Load Deephaven MCP settings from mappings and environment variables."""

    env = dict(env or os.environ)
    root_config = _coerce_mapping(config, section="deephaven_mcp")
    if "deephaven_mcp" in root_config:
        mcp_section = _coerce_mapping(root_config["deephaven_mcp"], section="deephaven_mcp")
    else:
        mcp_section = dict(root_config)
        mcp_section.pop("backend", None)

    url = str(mcp_section.get("url") or env.get(f"{_MCP_ENV_PREFIX}URL") or "")
    if not url:
        if require_url:
            raise ValueError("Deephaven MCP URL must be provided via configuration or environment")
        return None

    token_value = mcp_section.get("token") or env.get(f"{_MCP_ENV_PREFIX}TOKEN")
    if not token_value or not str(token_value).strip():
        raise ValueError("Deephaven MCP token must be provided via configuration or environment")
    token = str(token_value)

    if "use_tls" in mcp_section:
        use_tls_raw = mcp_section.get("use_tls")
    else:
        use_tls_raw = env.get(f"{_MCP_ENV_PREFIX}USE_TLS")
    use_tls = _coerce_bool(use_tls_raw, default=True)

    subscription_dir_value = mcp_section.get("subscription_dir") or env.get(
        f"{_MCP_ENV_PREFIX}SUBSCRIPTION_DIR"
    )
    subscription_dir = str(subscription_dir_value) if subscription_dir_value else None

    return DeephavenMCPSettings(
        url=url,
        token=token,
        use_tls=use_tls,
        subscription_dir=subscription_dir,
    )


__all__ = [
    "DEFAULT_EVENT_TABLE",
    "DEFAULT_MESSAGE_TABLE",
    "DEFAULT_METRIC_TABLE",
    "DEFAULT_UPDATE_GRAPH",
    "DeephavenAuthSettings",
    "DeephavenMCPTelemetrySettings",
    "DeephavenSettings",
    "DeephavenTableSettings",
    "DeephavenMCPSettings",
    "load_deephaven_settings",
    "load_deephaven_mcp_settings",
]
