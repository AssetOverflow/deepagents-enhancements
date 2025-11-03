"""Specialist agent wiring Deephaven MCP tools into Deepagents."""

from __future__ import annotations

import asyncio
import os
from typing import Any

from deepagents import create_deep_agent
from langchain_mcp_adapters.client import MultiServerMCPClient

SPECIALIST_PROMPT = """
You are the Deephaven automation specialist for Deepagents. Use the MCP tools to:
- inspect table schemas before running heavy queries,
- summarize live telemetry updates,
- materialize result sets to the shared filesystem directory `/workdir/deephaven/`.
Return concise status updates for each action you take.
"""


def _build_headers() -> dict[str, str]:
    token = os.environ.get("DEEPHAVEN_MCP_TOKEN")
    if not token:
        return {}
    return {"Authorization": f"Bearer {token}"}


async def run_specialist(session_messages: list[dict[str, Any]] | None = None) -> None:
    """Connect to Deephaven MCP and stream responses for the provided messages."""

    session_messages = session_messages or [
        {"role": "user", "content": "Profile the order flow tables and alert me to anomalies."}
    ]

    async with MultiServerMCPClient() as mcp_client:
        await mcp_client.add_server(
            name="deephaven",
            uri=os.environ["DEEPHAVEN_MCP_URL"],
            transport=os.environ.get("DEEPHAVEN_MCP_TRANSPORT", "ws"),
            headers=_build_headers(),
        )
        tools = await mcp_client.get_tools(include_servers={"deephaven"})

        agent = create_deep_agent(
            system_prompt=SPECIALIST_PROMPT,
            tools=list(tools.values()),
        )

        async for chunk in agent.astream({"messages": session_messages}, stream_mode="values"):
            messages = chunk.get("messages")
            if (
                isinstance(messages, list)
                and messages
                and hasattr(messages[-1], "pretty_print")
                and callable(messages[-1].pretty_print)
            ):
                messages[-1].pretty_print()


if __name__ == "__main__":
    asyncio.run(run_specialist())
