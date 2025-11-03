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

ColumnSpec = None
DeephavenTelemetryEmitter = None
DEFAULT_EVENT_SCHEMA: tuple = ()
DEFAULT_METRIC_SCHEMA: tuple = ()

try:  # pragma: no cover - optional telemetry dependency
    from deepagents.telemetry import (
        ColumnSpec as _ColumnSpec,
        DeephavenTelemetryEmitter as _DeephavenTelemetryEmitter,
        DEFAULT_EVENT_SCHEMA as _DEFAULT_EVENT_SCHEMA,
        DEFAULT_METRIC_SCHEMA as _DEFAULT_METRIC_SCHEMA,
    )
except (ImportError, ModuleNotFoundError):  # pragma: no cover - telemetry extras unavailable
    pass
else:
    ColumnSpec = _ColumnSpec
    DeephavenTelemetryEmitter = _DeephavenTelemetryEmitter
    DEFAULT_EVENT_SCHEMA = _DEFAULT_EVENT_SCHEMA
    DEFAULT_METRIC_SCHEMA = _DEFAULT_METRIC_SCHEMA

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

if ColumnSpec or DeephavenTelemetryEmitter is not None:  # pragma: no cover - optional export
    __all__.extend(
        [
            "ColumnSpec",
            "DEFAULT_EVENT_SCHEMA",
            "DEFAULT_METRIC_SCHEMA",
            "DeephavenTelemetryEmitter",
        ]
    )