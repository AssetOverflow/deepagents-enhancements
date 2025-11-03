"""DeepAgents package."""

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
from deepagents.graph import create_deep_agent
from deepagents.middleware.filesystem import FilesystemMiddleware
from deepagents.middleware.subagents import CompiledSubAgent, SubAgent, SubAgentMiddleware
from deepagents.session import AgentSession, AgentSessionConfig, create_agent_session

try:  # pragma: no cover - optional Deephaven telemetry dependency
    from deepagents.telemetry import ColumnSpec, DeephavenTelemetryEmitter, DEFAULT_EVENT_SCHEMA, DEFAULT_METRIC_SCHEMA
except ImportError:  # pragma: no cover - gracefully degrade when pydeephaven is unavailable
    ColumnSpec = None  # type: ignore[assignment]
    DeephavenTelemetryEmitter = None  # type: ignore[assignment]
    DEFAULT_EVENT_SCHEMA = None  # type: ignore[assignment]
    DEFAULT_METRIC_SCHEMA = None  # type: ignore[assignment]

__all__ = [
    "AgentSession",
    "AgentSessionConfig",
    "CompiledSubAgent",
    "FilesystemMiddleware",
    "SubAgent",
    "SubAgentMiddleware",
    "create_agent_session",
    "create_deep_agent",
]

if DeephavenTelemetryEmitter is not None:  # pragma: no cover - optional export
    __all__.extend(
        [
            "ColumnSpec",
            "DEFAULT_EVENT_SCHEMA",
            "DEFAULT_METRIC_SCHEMA",
            "DeephavenTelemetryEmitter",
        ]
    )
