"""Blueprint configuration for Deephaven-focused Deepagents."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
import re
from textwrap import dedent
from typing import Any

from deepagents.graph import create_deep_agent

DEFAULT_DEEPHAVEN_GOALS: tuple[str, ...] = (
    "Continuously profile Deephaven tables to surface schema, lineage, and latency insights.",
    "Design, review, and execute Deephaven queries while preserving deterministic, incremental semantics.",
    "Document findings and recommended follow-up actions for human operators.",
)
"""Canonical mission goals for the Deephaven specialist."""

DEEPHAVEN_SPECIALIST_PROMPT_TEMPLATE = dedent(
    """# Deephaven Specialist Orchestrator

    You are an autonomous orchestrator embedded alongside a Deephaven analytics cluster.
    Leverage the provided docsearch corpus, query execution interface, filesystem tools,
    and task subagents to reason about live tables, author safe transformation plans, and
    prepare operator-ready briefings.

    ## Mission Goals
    {goals}

    ## Operating Principles
    - Always summarise table state, schema changes, and lineage impacts before proposing modifications.
    - Prefer incremental, composable query patterns that respect Deephaven's update graph semantics.
    - Never run table mutations unless the user explicitly authorises the change **and** you have validated the blast radius.
    - Archive intermediate notebooks, scripts, and reports using the filesystem middleware for auditability.
    - Use subagents liberally for deep research, query authoring, or safety reviews.

    ## Tooling Overview
    - `docsearch`: retrieve architecture notes, API documentation, and previous incident reports related to Deephaven usage.
    - `run_deephaven_query_guarded`: execute Deephaven scripts, enforcing mutation guardrails by default; set `allow_write=true` only after confirming approvals.
    - Filesystem middleware: persist notebooks, diagnostics, and operator runbooks.

    ## Workflow Expectations
    1. Break multi-part objectives into TODOs and spawn specialised subagents when deeper focus is required.
    2. Capture supporting evidence (schemas, sample rows, metrics) inside the filesystem before concluding.
    3. Provide a concise final report outlining actions taken, outstanding risks, and recommended next steps.
    """
)
"""System prompt template used by the Deephaven specialist orchestrator."""

DEEPHAVEN_ANALYST_SUBAGENT_PROMPT = dedent(
    """# Deephaven Query & Research Subagent

    You are a Deephaven analytics specialist engaged by the orchestrator to answer a focused question.
    Your toolkit includes:
    - `docsearch` for Deephaven documentation, runbook snippets, and prior analyses.
    - `run_deephaven_query_guarded` for executing **read-only** queries that return structured table insights.

    ## Guardrails
    - Treat all Deephaven sessions as production-facing. Mutations (drop, delete, update, merge, publish, write) are forbidden
      unless the orchestrator explicitly adds `allow_write=true` alongside a change management ticket or approval note.
    - When a modification is requested, draft the exact script, summarise the impact, and return it without execution unless
      `allow_write=true` is present. Call out any ambiguities.
    - Use docsearch to cite relevant Deephaven APIs or operational guidelines before running complex queries.

    ## Expected Output
    Provide a single report covering:
    - Key documentation excerpts or links that informed your work.
    - Queries executed, including table names, filters, and relevant parameters.
    - Structured findings (schema diffs, row counts, sample data) with clear implications for the orchestrator.
    - Explicit warnings when an operation was blocked by guardrails or requires human approval.
    """
)
"""System prompt used by the Deephaven specialist subagent."""

_MUTATION_PATTERN = re.compile(
    r"(?i)(?:delete|drop|merge|overwrite|publish|update|write|insert)\w*",
)
"""Regex used to detect potentially mutating Deephaven operations."""


def _format_goals(goals: Iterable[str]) -> str:
    return "\n".join(f"- {goal}" for goal in goals)


def build_deephaven_specialist_prompt(goals: Sequence[str] | None = None) -> str:
    """Render the orchestrator system prompt using provided goals."""

    active_goals = goals or DEFAULT_DEEPHAVEN_GOALS
    return DEEPHAVEN_SPECIALIST_PROMPT_TEMPLATE.format(goals=_format_goals(active_goals))


def make_guarded_deephaven_query_tool(
    query_tool: Callable[..., Any],
    *,
    mutation_pattern: re.Pattern[str] | None = None,
    name: str = "run_deephaven_query_guarded",
    description: str | None = None,
) -> Callable[..., Any]:
    """Wrap a Deephaven query callable with mutation guardrails."""

    compiled_pattern = mutation_pattern or _MUTATION_PATTERN

    def guarded_query(script: str, /, **kwargs: Any) -> Any:
        allow_write = bool(kwargs.pop("allow_write", False))
        if not allow_write and compiled_pattern.search(script):
            raise ValueError(
                "Potential Deephaven table mutation detected. Re-run with allow_write=True after recording approvals."
            )
        return query_tool(script=script, **kwargs)

    guarded_query.__name__ = name
    guarded_query.__doc__ = description or (
        "Execute Deephaven scripts with automatic mutation guardrails."
        " Pass allow_write=True only for approved data-changing operations."
    )
    return guarded_query


def build_deephaven_analysis_subagent(
    *,
    docsearch_tool: Callable[..., Any],
    query_tool: Callable[..., Any],
    name: str = "deephaven-query-analyst",
    description: str | None = None,
) -> dict[str, Any]:
    """Create the Deephaven research & query subagent specification."""

    subagent_description = description or (
        "Focused Deephaven researcher that gathers documentation context and runs guarded queries"
        " to answer a single investigative prompt."
    )
    return {
        "name": name,
        "description": subagent_description,
        "system_prompt": DEEPHAVEN_ANALYST_SUBAGENT_PROMPT,
        "tools": [docsearch_tool, query_tool],
    }


def build_deephaven_specialist_agent(
    *,
    docsearch_tool: Callable[..., Any],
    query_tool: Callable[..., Any],
    additional_tools: Sequence[Callable[..., Any]] | None = None,
    goals: Sequence[str] | None = None,
    system_prompt: str | None = None,
    subagent_overrides: Sequence[dict[str, Any]] | None = None,
    **agent_kwargs: Any,
):
    """Instantiate a Deephaven specialist agent with sensible defaults."""

    guarded_query_tool = make_guarded_deephaven_query_tool(query_tool)
    orchestrator_prompt = system_prompt or build_deephaven_specialist_prompt(goals)

    agent_tools: list[Callable[..., Any]]
    agent_tools = [docsearch_tool, guarded_query_tool]
    if additional_tools:
        agent_tools.extend(additional_tools)

    subagents = list(subagent_overrides or [])
    if not subagent_overrides:
        subagents.append(
            build_deephaven_analysis_subagent(
                docsearch_tool=docsearch_tool,
                query_tool=guarded_query_tool,
            )
        )

    return create_deep_agent(
        tools=agent_tools,
        system_prompt=orchestrator_prompt,
        subagents=subagents,
        **agent_kwargs,
    )
