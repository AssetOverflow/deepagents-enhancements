# AssetOverflow/deephaven-mcp Integration Blueprint for Deepagents

## Purpose and Scope
This document analyzes the open-source `AssetOverflow/deephaven-mcp` Model Context Protocol (MCP) server
and designs a practical integration plan that elevates it to a first-class subsystem inside Deepagents.
Because direct cloning of the upstream repository is blocked in this environment, the analysis combines
publicly documented MCP conventions with the deephaven research already captured in this repository to
produce an actionable, architecture-level plan. The focus is on maximizing efficiency, reliability, and
extensibility so that Deephaven capabilities become fundamental to Deepagents and can host future MCP
extensions with minimal incremental effort.

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
