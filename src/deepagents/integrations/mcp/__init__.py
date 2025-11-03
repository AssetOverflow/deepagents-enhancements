"""Lightweight MCP integration utilities for Deepagents.

This package currently focuses on shared client abstractions that are reused by
both production code and test harnesses.  The implementation intentionally keeps
surface area small so it can be exercised with deterministic mocks inside the
unit test suite.
"""

from .client import MCPClient, MCPTool, MCPTransport

__all__ = ["MCPClient", "MCPTool", "MCPTransport"]
