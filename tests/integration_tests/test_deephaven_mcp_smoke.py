"""Optional smoke tests for a live Deephaven MCP deployment."""

from __future__ import annotations

import os
import urllib.request

import pytest

HEALTHCHECK_URL = os.getenv("DEEPHAVEN_MCP_HEALTHCHECK_URL")

pytestmark = pytest.mark.skipif(
    not HEALTHCHECK_URL,
    reason="DEEPhaven MCP healthcheck URL not configured; skipping live smoke test.",
)


def test_deephaven_mcp_healthcheck_endpoint() -> None:
    """Simple HTTP-based smoke test for a running deephaven-mcp instance."""

    with urllib.request.urlopen(HEALTHCHECK_URL, timeout=5) as response:  # noqa: S310 (test-only HTTP call)
        assert 200 <= response.status < 300
