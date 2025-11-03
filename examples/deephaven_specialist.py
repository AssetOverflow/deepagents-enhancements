"""Executable example showcasing the Deephaven specialist blueprint."""

from __future__ import annotations

from pprint import pprint
from typing import Any, Sequence

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from deepagents.config.presets import (
    build_deephaven_analysis_subagent,
    build_deephaven_specialist_agent,
    make_guarded_deephaven_query_tool,
)


def docsearch(query: str, *, limit: int = 3) -> list[dict[str, Any]]:
    """Tiny in-memory docsearch stub used for the example."""

    corpus = [
        {
            "title": "Session pooling guidance",
            "url": "https://docs.example.com/deephaven/session-pooling",
            "summary": "Reuse Deephaven sessions and prefer read-only scripts where possible.",
        },
        {
            "title": "Update graph primer",
            "url": "https://docs.example.com/deephaven/update-graph",
            "summary": "Explains how incremental queries propagate through the update graph.",
        },
        {
            "title": "Table safety checklist",
            "url": "https://docs.example.com/deephaven/table-safety",
            "summary": "Always secure approval before running drop or delete operations in production.",
        },
    ]
    query_lower = query.lower()
    matches = [entry for entry in corpus if query_lower in entry["summary"].lower()]
    return matches[:limit]


def execute_query(script: str, *, table: str | None = None) -> dict[str, Any]:
    """Simulated Deephaven query interface returning canned results."""

    if "head(" in script:
        return {
            "table": table or "prices",
            "schema": {"symbol": "string", "price": "double"},
            "rows": [
                {"symbol": "AAPL", "price": 192.42},
                {"symbol": "MSFT", "price": 410.36},
            ],
        }
    return {"table": table or "prices", "script": script, "message": "query executed"}


def demonstrate_guardrail(guarded_tool: Any) -> None:
    """Show how the mutation guard prevents unsafe scripts."""

    print("\nAttempting read-only query:\n---------------------------")
    pprint(guarded_tool("table.head(2)", table="prices"))

    print("\nAttempting mutation without approval:\n--------------------------------------")
    try:
        guarded_tool("table.dropColumns(['temp'])")
    except ValueError as exc:  # pragma: no cover - demonstration output
        print(f"Guard blocked mutation: {exc}")

    print("\nExecuting approved mutation:\n-----------------------------")
    pprint(
        guarded_tool(
            "table.dropColumns(['temp'])",
            allow_write=True,
            table="prices",
        )
    )


class _DeterministicChatModel(BaseChatModel):
    """Minimal chat model that returns canned responses and supports tool binding."""

    def __init__(self, responses: Sequence[str]) -> None:
        super().__init__()
        self._responses = list(responses)

    @property
    def _llm_type(self) -> str:  # pragma: no cover - simple metadata
        return "deterministic"

    def bind_tools(self, tools: Any, **kwargs: Any) -> "_DeterministicChatModel":  # pragma: no cover - passthrough
        return self

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: Sequence[str] | None = None,
        run_manager: Any | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        content = self._responses.pop(0) if self._responses else "Demo complete. Review printed guardrail output."
        generation = ChatGeneration(message=AIMessage(content=content))
        return ChatResult(generations=[generation], llm_output={})

    @property
    def _identifying_params(self) -> dict[str, Any]:  # pragma: no cover - metadata hook
        return {"responses": tuple(self._responses)}


def main() -> None:
    model = _DeterministicChatModel(responses=["Demo complete. Review printed guardrail output."])

    guarded_query = make_guarded_deephaven_query_tool(execute_query)
    subagent_spec = build_deephaven_analysis_subagent(
        docsearch_tool=docsearch,
        query_tool=guarded_query,
    )

    agent = build_deephaven_specialist_agent(
        model=model,
        docsearch_tool=docsearch,
        query_tool=execute_query,
        subagent_overrides=[subagent_spec],
    )

    demonstrate_guardrail(guarded_query)

    print("\nInvoking orchestrator with placeholder model:\n----------------------------------------------")
    result = agent.invoke({"messages": [HumanMessage(content="Summarise the live prices table.")]})
    pprint(result["messages"][-1].content)


if __name__ == "__main__":
    main()
