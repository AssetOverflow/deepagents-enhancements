# AssetOverflow/deephaven-mcp Integration Blueprint for Deepagents

> **Audience:** Deepagents platform engineers and operations owners responsible for
> shipping, hardening, and extending MCP tooling inside the Deepagents runtime.

## Purpose and Scope
This document analyzes the open-source `AssetOverflow/deephaven-mcp` Model Context Protocol (MCP) server
and designs a practical integration plan that elevates it to a first-class subsystem inside Deepagents.
Because direct cloning of the upstream repository is blocked in this environment, the analysis combines
publicly documented MCP conventions with the deephaven research already captured in this repository to
produce an actionable, architecture-level plan. The focus is on maximizing efficiency, reliability, and
extensibility so that Deephaven capabilities become fundamental to Deepagents and can host future MCP
extensions with minimal incremental effort.

## Table of Contents
- [Repository Overview](#repository-overview)
- [Integration Goals](#integration-goals)
- [Deepagents Architectural Touchpoints](#deepagents-architectural-touchpoints)
- [High-Level Architecture](#high-level-architecture)
- [Integration Plan](#integration-plan)
- [Implementation Blueprint inside Deepagents](#implementation-blueprint-inside-deepagents)
- [Configuration and Deployment Cookbook](#configuration-and-deployment-cookbook)
- [Quality Gates and Testing Strategy](#quality-gates-and-testing-strategy)
- [Runbook Artifacts to Produce](#runbook-artifacts-to-produce)
- [Pathway for Additional MCP Tools](#pathway-for-additional-mcp-tools)
- [Expected Outcomes](#expected-outcomes)

## Executive Summary
- **Elevate Deephaven MCP to a core Deepagents subsystem** by standardizing client packaging, configuration,
  and health checking so agents can rely on it for primary analytics workflows.
- **Ship a dedicated integration package** that wraps MCP tools into LangChain-ready helpers, pooling
  sessions and normalizing responses for planners, subagents, and middleware.
- **Operationalize Deephaven-first automation** through filesystem conventions, deployment cookbooks,
  comprehensive testing matrices, and runbooks that de-risk future MCP server onboarding.

## Repository Overview
`deephaven-mcp` exposes Deephaven analytics through MCP tools, enabling LLM agents to run server-side
scripts, inspect schemas, and subscribe to live table updates. The standard layout of Anthropic-style MCP
servers informs the inferred structure:

- `server.py` / `app.py`: Entry point that registers MCP tools and resources, typically bootstrapping a
  PyDeephaven session factory and exposing health checks.
- `tools/query.py`: Contains synchronous and asynchronous query execution utilities that accept Python or
  SQL-like scripts, execute them via PyDeephaven, and marshal responses into structured payloads.
- `tools/materialize.py`: Persists Deephaven tables to Arrow/Parquet snapshots, returning tickets or file
  references that downstream agents can reason about without streaming entire datasets.
- `tools/subscribe.py`: Implements streaming subscriptions using Deephaven's table listeners, mapping
  incremental updates into MCP events so Deepagents can react to live data.
- `session.py`: Provides connection pooling, credential management, and idle timeouts to keep Deephaven
  sessions healthy.
- `config.py`: Encapsulates environment variables (server URL, authentication tokens, table namespaces),
  aligning with MCP configuration expectations for human operators.

Even though the exact filenames may differ, the server's capability surface reliably includes **query
execution**, **materialization**, **schema inspection**, and **subscription management**, which are the key
primitives Deepagents must orchestrate.

## Integration Goals
1. **Treat Deephaven as a primary execution substrate** for data-heavy tasks, not an optional add-on.
2. **Provide ergonomic LangChain tools** that mirror MCP capabilities with context-rich responses tailored
   for Deepagents' planning and summarization middleware.
3. **Ensure reliability and observability** so that long-running Deephaven workflows can be monitored,
   retried, and audited inside Deepagents.
4. **Create an extensible MCP integration surface** that allows future Deephaven-specific or third-party
   MCP servers to be plugged in without structural refactoring.

## Deepagents Architectural Touchpoints
Deepagents already includes the following features that the MCP integration will leverage:

- **Planning via `TodoListMiddleware`** ensures complex Deephaven workflows are decomposed into safe,
  resumable steps.【F:src/deepagents/graph.py†L50-L135】
- **Filesystem middleware** provides scratch space and long-term memory for generated scripts, materialized
  tables, and audit logs.【F:src/deepagents/graph.py†L136-L183】
- **SubAgent middleware** allows specialization (e.g., "Deephaven Query Author", "Stream Monitor") while
  sharing MCP tools and Deephaven credentials.【F:src/deepagents/graph.py†L142-L177】
- **Summarization and prompt caching** protect context windows when streaming Deephaven output or
  subscription updates.【F:src/deepagents/graph.py†L148-L182】

The integration plan exploits these hooks to deliver deterministic, high-throughput interactions with the
`deephaven-mcp` server.

## High-Level Architecture
```
+--------------------+      MCP (gRPC/WebSocket)       +----------------------------+
| Deepagents Runner  | <-----------------------------> | deephaven-mcp MCP Server   |
|                    |                                 | (PyDeephaven-backed tools) |
|  - Agent Planner   |                                 |  - Query Execution         |
|  - MCP Tool Layer  |                                 |  - Table Materialization   |
|  - Redis Cache     |                                 |  - Stream Subscriptions    |
|  - Filesystem FS   |                                 |  - Schema Inspection       |
+---------+----------+                                 +----------------------------+
          |                                                       |
          | Materialized files / audit trails                     | Deephaven Core Engine
          v                                                       v
+-----------------------------+                         +---------------------------+
| `/workdir/deephaven/` FS    |                         | Deephaven Tables & Graphs |
+-----------------------------+                         +---------------------------+
```

### Data Flow Highlights
1. Agents authenticate against the MCP server using stored credentials.
2. Session middleware acquires or spawns a Deephaven connection ticket for the duration of a task.
3. Queries or subscriptions are issued through MCP tools; responses are summarized and cached.
4. Materialized artifacts are written to the Deepagents filesystem for downstream reasoning or sharing with
   other subagents.
5. Metrics, errors, and lineage metadata feed back into the planner to trigger follow-up actions.

## Integration Plan

### Phase 1 – Baseline Connectivity
1. **Dependency packaging**: Extend Deepagents deployment images with the `deephaven-mcp` Python package
   alongside `deephaven-core` and `pydeephaven`. Store configuration templates under `examples/` to simplify
   local development.
2. **Credential management**: Add environment variable conventions (e.g., `DEEPHAVEN_MCP_URL`,
   `DEEPHAVEN_MCP_TOKEN`) and document how to store them in deployment secrets.
3. **MCP client wrapper**: Implement a reusable LangChain tool harness that connects to any MCP server. For
   Deephaven, expose helpers like `deephaven_run_query`, `deephaven_materialize`, and `deephaven_subscribe`.
4. **Health checks**: Create a startup probe task that verifies connectivity, retrieves server metadata, and
   surfaces configuration issues before agents are deployed.

### Phase 2 – Deepagents Tooling Layer
1. **Structured responses**: Wrap MCP tool calls so they return JSON objects containing schema, sample rows,
   Deephaven tickets, and suggested follow-up actions. This aligns with Deepagents' planner expectations.
2. **Session lifecycle middleware**: Implement a shared session pool using asyncio locks to prevent thrashing
   Deephaven with rapid connect/disconnect cycles. Idle sessions should be recycled after configurable
   timeouts.
3. **Filesystem integration**: Define canonical directories (e.g., `/workdir/deephaven/materializations/`) and
   automatically persist artifacts generated by the MCP server. Update summarization prompts so agents note
   where outputs are stored.
4. **Observability hooks**: Capture MCP request/response metadata and log them through Deepagents' patch
   middleware so human overseers can audit actions.

### Phase 3 – Streaming Intelligence
1. **Subscription orchestrator**: Spawn dedicated subagents to manage long-lived stream subscriptions.
   Subagents translate streaming updates into summarized deltas and push actionable items onto the main
   agent's TODO list (e.g., "Investigate anomaly in `OrderBook` table").
2. **Trigger-based planning**: Integrate MCP stream callbacks with Todo middleware. When thresholds are
   crossed, automatically enqueue remediation or investigation tasks.
3. **Cache coordination**: Map Deephaven table tickets to Redis cache keys so repeated queries reuse existing
   summaries unless upstream data freshness requires refreshes.
4. **Alerting**: Expose MCP-based alert tools that notify human operators through Deepagents' interrupt
   middleware when critical conditions occur (schema drift, ingestion failure).

### Phase 4 – Governance and Multi-MCP Expansion
1. **Policy enforcement**: Introduce guardrail middleware that validates requested operations against a
   policy file (allowed tables, timeouts, resource quotas) before calling the MCP server.
2. **Reusable MCP harness**: Abstract common code so additional MCP servers (e.g., TimescaleDB MCP, Kafka
   MCP) can be onboarded by only defining tool descriptors and response schemas.
3. **Documentation generation**: Use Deepagents to auto-produce runbooks and architecture diagrams for each
   MCP integration, storing them in the filesystem middleware for auditing.
4. **Testing harness**: Build contract tests that mock the MCP server to validate tool interfaces without
   requiring live Deephaven instances.

## Implementation Blueprint inside Deepagents

The following map translates the phased plan into concrete code additions scoped to this repository.

| Workstream | Deepagents Touchpoints | Deliverables |
|------------|------------------------|--------------|
| **Package Integration** | `pyproject.toml`, `uv.lock`, Docker build contexts | Add `deephaven-mcp` + `pydeephaven` dependencies, pin versions, and provide editable extras for local dev containers. |
| **Tool Harness** | `src/deepagents/integrations/deephaven_mcp/` | Create a package exporting `DeephavenMCPClient`, LangChain-compatible `Tool` factories (`run_query_tool`, `subscribe_tool`, `materialize_tool`), and Pydantic response models. |
| **Middleware & Session Pool** | `src/deepagents/middleware/session_pool.py` (new), integrate in `graph.py` registration flow | Async context manager backed by `asyncio.Semaphore` for connection pooling, instrumentation hooks, configurable via `DeephavenMCPSettings`. |
| **Configuration Layer** | `src/deepagents/settings.py`, `.env.example`, docs | Extend settings object with `deephaven_mcp_url`, `deephaven_mcp_token`, optional TLS flags, and environment variable mapping. |
| **Filesystem Layout** | `src/deepagents/middleware/filesystem.py`, `README.md` | Introduce `deephaven/` namespace with standardized subdirectories (`materializations/`, `subscriptions/`, `logs/`). |
| **Observability** | `src/deepagents/instrumentation/mcp_logging.py` (new), integrate with existing patch middleware | Structured logging for each MCP call, correlation IDs, latency metrics, and failure classification for policy review. |
| **Orchestrator Subagents** | `examples/deephaven/stream_monitor.yaml`, `docs/runbooks/` | Provide sample LangGraph definitions demonstrating specialized Deephaven subagents and TODO triggers. |

### Module Skeletons

```python
# src/deepagents/integrations/deephaven_mcp/client.py
class DeephavenMCPClient:
    def __init__(self, settings: DeephavenMCPSettings, *, session_pool: MCPAsyncSessionPool):
        ...

    async def run_query(self, script: str, *, table: str | None = None, max_rows: int = 200) -> DeephavenQueryResult:
        ...

    async def materialize(self, table_ticket: str, *, destination: Path) -> DeephavenMaterializationResult:
        ...

    async def subscribe(self, table_ticket: str, *, sink: SubscriptionSink) -> SubscriptionHandle:
        ...
```

```python
# src/deepagents/integrations/deephaven_mcp/tools.py
deephaven_run_query = Tool.from_function(
    DeephavenMCPClient.run_query,
    name="deephaven_run_query",
    description="Execute a Deephaven script via MCP and return schema-aware summaries.",
)
```

### Integration Hooks
1. Register the Deephaven tool suite within `build_default_graph()` in `src/deepagents/graph.py` behind a
   feature flag (`settings.deephaven_mcp_enabled`).
2. Use dependency injection so subagents request the `DeephavenMCPClient` via the LangGraph state instead of
   rebuilding clients per call.
3. Surface summarized responses to the planner via the existing TODO middleware enrichment pattern so agents
   automatically annotate next steps.

## Configuration and Deployment Cookbook

```toml
# pyproject.toml excerpt
[project.optional-dependencies]
deephaven = [
    "deephaven-mcp>=0.1.0",
    "deephaven-core>=0.34.0",
    "pydeephaven>=0.32.0",
]
```

```env
# .env.example additions
DEEPHAVEN_MCP_URL=https://deephaven-mcp.internal:8080
DEEPHAVEN_MCP_TOKEN=replace-with-secret
DEEPHAVEN_MCP_USE_TLS=true
DEEPHAVEN_MCP_SUBSCRIPTION_DIR=/workdir/deephaven/subscriptions
```

```yaml
# k8s ConfigMap fragment
data:
  deephaven-mcp-settings.yaml: |
    url: ${DEEPHAVEN_MCP_URL}
    auth_token: ${DEEPHAVEN_MCP_TOKEN}
    request_timeout_seconds: 45
    session_pool:
      max_concurrent_sessions: 6
      idle_ttl_seconds: 900
    subscription_defaults:
      max_queue_size: 2048
      lag_alert_seconds: 30
```

Deployment Steps:
1. Build the Deepagents runtime image with the `deephaven` extra enabled; run smoke tests using
   `uv run python -m examples.deephaven.healthcheck`.
2. Store the MCP token in the platform's secrets manager and reference it in orchestrator manifests.
3. Provision a shared volume (or S3 bucket) mounted at `/workdir/deephaven/` for materializations and
   subscription logs; enforce lifecycle policies for large artifacts.
4. Configure observability exporters (OpenTelemetry / Prometheus) to scrape MCP metrics emitted by the new
   instrumentation module.

## Quality Gates and Testing Strategy

| Layer | Test Type | Description |
|-------|-----------|-------------|
| **Unit** | `pytest tests/integrations/deephaven/test_client.py` | Mock MCP transport to validate serialization, response parsing, and error normalization. |
| **Contract** | `pytest tests/integrations/deephaven/test_contract.py --record` | Replay golden MCP transcripts stored under `tests/fixtures/deephaven/` to ensure backward-compatible payloads. |
| **Integration** | `make test-deephaven` | Spin up a disposable Deephaven + MCP stack via docker-compose and run end-to-end tool exercises, verifying filesystem outputs. |
| **Smoke** | `uv run python examples/deephaven/healthcheck.py` | Verifies credentials, basic query execution, and subscription handshake on deploy. |
| **Load** | Locust / k6 scenario | Stress-check concurrent MCP queries and subscription fan-out using pooled sessions. |

Define CI workflows that execute unit + contract tests on every PR, optional integration tests behind a
feature flag, and smoke tests post-deploy.

## Runbook Artifacts to Produce

- **Health Check Guide** (`docs/runbooks/deephaven_mcp_healthcheck.md`): Troubleshooting steps for failed
  connectivity probes, credential expiry, and TLS issues.
- **Subscription Operations Manual** (`docs/runbooks/deephaven_subscription_ops.md`): Explains how to
  interpret summarized deltas, rotate stream monitors, and adjust alert thresholds.
- **Incident Response Cheat Sheet** (`docs/runbooks/deephaven_incidents.md`): Mapping of MCP error codes to
  Deephaven remediation actions and contact paths.
- **Extensibility Playbook** (`docs/runbooks/mcp_extension_playbook.md`): Template for onboarding new MCP
  servers using the same harness, including checklist items for security, testing, and documentation.

## Practical Implementation Guidance
- **Tool Definitions**: Provide thin wrappers that translate Deepagents' typed inputs into MCP requests. Use
  LangChain's async tooling interface to keep streaming interactions responsive.
- **Error Handling**: Normalize MCP errors (connection resets, Deephaven script failures) into structured
  exceptions with actionable remediation hints.
- **Prompt Engineering**: Extend the default system prompt to include Deephaven operational playbooks,
  including examples of how to request schema info before running heavy queries.
- **Subagent Templates**:
  - *Query Author*: writes and validates Deephaven scripts before execution.
  - *Stream Monitor*: watches subscriptions, summarizes anomalies, and triggers tasks.
  - *Materialization Steward*: manages file outputs, compresses old snapshots, and updates documentation.
- **Deployment Considerations**: Co-locate the MCP server and Deepagents runtime when possible to minimize
  latency. For distributed deployments, enable TLS and configure keep-alive parameters to maintain stable
  MCP channels.

## Pathway for Additional MCP Tools
1. **Common Registry**: Maintain a registry file (e.g., `src/deepagents/integrations/mcp_registry.py`) that
   maps MCP server identifiers to tool factories. Register `deephaven-mcp` as the first entry.
2. **Interface Contracts**: Define Pydantic models for request/response payloads so future MCP tools follow
   consistent schemas. Reuse these contracts to auto-generate documentation and tests.
3. **Extensibility Hooks**: Allow agents to discover available MCP servers at runtime and request
   capabilities dynamically. This enables multi-database orchestrations (Deephaven + warehouse + alerting).
4. **Security Baseline**: Document minimal security requirements (mutual TLS, API tokens, audit logging) that
   any MCP server must meet before being wired into production agents.

## Documentation Deliverables
- **Runbook**: Step-by-step guide for configuring Deephaven MCP credentials, running connectivity checks, and
  validating tool responses inside Deepagents.
- **Developer Guide**: Instructions for writing new MCP tool wrappers, extending prompts, and implementing
  contract tests.
- **Operations Playbook**: Procedures for monitoring subscriptions, rotating credentials, and responding to
  Deephaven incidents.
- **Architecture Diagram**: Updated diagram in `docs/research/deephaven_deepagents.md` referencing the MCP
  integration, keeping Deephaven front-and-center in the Deepagents ecosystem.

## Expected Outcomes
By following this blueprint, Deepagents will treat `deephaven-mcp` as a foundational capability:

- Agents can orchestrate streaming analytics autonomously while retaining guardrails and observability.
- Deephaven's strengths (incremental computation, live tables, lineage) become available to every Deepagent
  workflow without bespoke integration.
- Additional MCP servers can be layered on with predictable effort, compounding Deepagents' reach across
  enterprise data systems.

This plan transforms the Deephaven MCP server from an auxiliary integration into a core competency within
Deepagents, unlocking a powerful platform for autonomous, data-driven intelligence.
