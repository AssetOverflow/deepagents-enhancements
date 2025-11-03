"""Pre-built configuration blueprints for Deepagents deployments."""

from .deephaven_specialist import (
    DEFAULT_DEEPHAVEN_GOALS,
    DEEPHAVEN_ANALYST_SUBAGENT_PROMPT,
    DEEPHAVEN_SPECIALIST_PROMPT_TEMPLATE,
    build_deephaven_analysis_subagent,
    build_deephaven_specialist_agent,
    build_deephaven_specialist_prompt,
    make_guarded_deephaven_query_tool,
)

__all__ = [
    "DEFAULT_DEEPHAVEN_GOALS",
    "DEEPHAVEN_ANALYST_SUBAGENT_PROMPT",
    "DEEPHAVEN_SPECIALIST_PROMPT_TEMPLATE",
    "build_deephaven_analysis_subagent",
    "build_deephaven_specialist_agent",
    "build_deephaven_specialist_prompt",
    "make_guarded_deephaven_query_tool",
]
