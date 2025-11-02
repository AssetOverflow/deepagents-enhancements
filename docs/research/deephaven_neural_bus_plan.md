# Deephaven Neural Bus Integration Plan for Deepagents

## Vision & Objectives
- **Neural Bus Concept**: Establish Deephaven as the shared, real-time data plane powering message exchange, telemetry, and coordination between Deepagents components and subagents.
- **Strategic Goals**:
  1. Deliver a transport abstraction (`DeephavenBus`) that maps Deepagents' message model onto Deephaven ticking tables.
  2. Leverage Deephaven's compute-on-deltas DAG to enable reactive planning, backpressure management, and metrics collection at scale.
  3. Provide durable ingress/egress pathways (Kafka, snapshots) so agent conversations and outcomes can be replayed, audited, and analyzed offline.
  4. Maintain operational guardrails (auth, isolation, observability) aligned with production readiness.

## Core Table Schemas (Bus Primitives)
Treat tables as topics and materialized views as subscriptions. Provision the following canonical schemas during bootstrap (idempotent deployment script):

### `agent_messages` (mutable, ticking)
| Column | Type | Notes |
| --- | --- | --- |
| `ts` | long (epoch ns) | Source timestamp supplied by publishers. |
| `ingest_ts` | long (epoch ns) | Server arrival timestamp (auto-populated). |
| `topic` | string | Logical routing channel (e.g., `planning`, `retrieval`, `control`). |
| `session_id` | string | Conversation scope; supports multi-tenant isolation. |
| `task_id` | string | Granular linkage to Deepagents TODO entries. |
| `agent_id` | string | Originating or target agent identifier. |
| `role` | string enum (`system`,`user`,`agent`) | Aligns with LLM conversation roles. |
| `msg_type` | string enum (`text`,`json`,`binary`,`embedding_ref`,`signal`) | Indicates payload semantics. |
| `payload_json` | string | Primary payload for structured/text messages. |
| `payload_blob_ref` | string | Optional pointer to object storage for large artifacts. |
| `priority` | int | Higher values claimable first. |
| `ttl_ms` | int | Visibility timeout; expired rows can be reclaimed. |
| `lease_owner` | string | Agent currently processing the message. |
| `lease_expires_ts` | long | Absolute expiration of the active lease. |
| `status` | string enum (`queued`,`processing`,`done`,`error`,`expired`) | Stateful lifecycle column updated atomically. |

### `agent_events` (append-only)
| Column | Type | Notes |
| --- | --- | --- |
| `ts` | long | Event time. |
| `agent_id` | string | Actor emitting the event. |
| `session_id` | string | Optional correlation scope. |
| `event` | string enum | (`claimed`,`ack`,`nack`,`heartbeat`,`timeout`, etc.). |
| `details_json` | string | Structured metadata enabling idempotency checks and audit trails. |

### `agent_metrics` (ticking aggregates)
| Column | Type | Notes |
| --- | --- | --- |
| `window_start` | long | Bucket lower bound (e.g., 1m tumbling). |
| `agent_id` | string | Metric dimension. |
| `session_id` | string | Optional dimension. |
| `messages_processed` | long | Count within window. |
| `avg_latency_ms` | double | Rolling average from enqueue to completion. |
| `errors` | long | Failure count. |
| `token_usage` | long | Optional aggregated cost metric. |
| `last_update_ts` | long | Tick timestamp for consumers. |

## System Architecture
1. **Deephaven Server Layer**
   - Deploy core server with Barrage streaming enabled and persistent storage for snapshots.
   - Configure authentication (PSK or username/password) and TLS termination via ingress proxy.
   - Define multiple Update Graphs: dedicate `graph_default` for control-plane traffic, `graph_highfreq` for high-throughput agents.
2. **Deepagents Integration Layer**
   - Implement `DeephavenBus` adapter respecting the existing bus interface (publish, subscribe, claim/lease, ack, nack, extend lease).
   - Maintain a session pool (`pydeephaven.Session`) with configurable size and heartbeat monitoring.
   - Provide schema bootstrapper invoked at application startup to create missing tables and indices via Deephaven scripts.
3. **Agent Runtime Layer**
   - Each agent registers a filtered view (e.g., `where(topic == "planning" && status == "queued")`).
   - A subscriber loop listens to Barrage ticks, attempts atomic lease acquisition, and updates `status` using Deephaven's `update_by` or `Table.update` semantics.
   - Emitted results publish follow-up messages and append to `agent_events` for audit.
4. **Observability & Ops**
   - Mirror critical tables to Kafka topics for durability / replay (leveraging Deephaven's Kafka connector).
   - Schedule periodic Flight exports (Parquet) to object storage for historical analysis.
   - Surface dashboards via Deephaven JS API showing live `agent_messages` backlog, per-agent metrics, and Barrage health indicators.

## Implementation Roadmap

### Phase 0 – Foundations
1. **Dependency Packaging**: Add `pydeephaven` and security-related dependencies to Deepagents runtime; ensure compatibility with existing packaging (uv/poetry).
2. **Configuration Schema**: Extend Deepagents config to include Deephaven endpoint, auth credentials, table names, update graph assignments, and optional Kafka bridge settings.
3. **Bootstrap Scripts**: Author Deephaven Python/Java scripts to declare input tables, ticking tables, and initial indexes. Provide CLI entry point (`deepagents deephaven-bootstrap`).

### Phase 1 – Core Bus Adapter
1. **Session Pooling Utility**
   - Create asynchronous pool with max/min sessions, heartbeat pings, automatic reconnection, and metrics exposure.
   - Support PSK and username/password auth flows.
2. **Publish Path**
   - Implement `publish(message)` using `TablePublisher` or `DynamicTableWriter` to append rows to `agent_messages`.
   - Enforce server-side defaults (`ingest_ts`, TTL fallback) via Deephaven update expressions.
3. **Subscribe & Lease Management**
   - Materialize filtered view per subscription; expose async iterator delivering delta batches.
   - Implement optimistic lease acquisition by updating `status`, `lease_owner`, and `lease_expires_ts` with a conditional update (e.g., `where_in` + `update` script) to prevent double processing.
   - Provide `ack` (set status `done`, log event), `nack` (reset to `queued` with incremented retry counter), and `extend_lease` operations.
4. **Backpressure Controls**
   - Monitor queue depth and per-agent throughput; inject new planning tasks when thresholds exceeded.
   - Support priority-aware claim (order by `priority DESC, ts ASC`).

### Phase 2 – Metrics & Telemetry
1. **Metrics Aggregator**
   - Implement Deephaven query DAG that rolls up `agent_messages` transitions into `agent_metrics` using `update_by` and windowed aggregations.
   - Stream metrics to Deepagents observability stack (Prometheus, logs) via client subscriber.
2. **Event Audit Trail**
   - Ensure every lifecycle change appends to `agent_events`; provide tooling to reconcile duplicates and detect stuck leases.
3. **Health Dashboards**
   - Build lightweight JS dashboard (React or Deephaven JS API) embedded in Deepagents UI exposing queue states, processing latencies, and error rates.

### Phase 3 – Durability & Advanced Features
1. **Kafka Bridge Enablement**
   - Configure Deephaven <-> Kafka synchronization for `agent_messages` and `agent_events`, enabling external analytics and disaster recovery.
   - Document replay procedure (seed Deephaven tables from Kafka partitions).
2. **Snapshot & Replay Services**
   - Provide CLI/agent tool to trigger Arrow Flight exports for offline debugging, and importers to rehydrate sessions for regression tests.
3. **Multi-Tenant Isolation**
   - Map `session_id` or dedicated tenant column to separate Update Graphs; enforce quota policies via Deephaven query guards.
4. **Adaptive Planning Hooks**
   - Integrate Deephaven alerts (e.g., queue depth > threshold) with Deepagents TODO middleware to inject remediation tasks automatically.

## Deliverables & Documentation
- **Architecture Specification** (this document) stored in `docs/research` and linked from `docs/_sidebar.md`.
- **Configuration Guide** covering auth setup, environment variables, and bootstrap commands.
- **Operational Runbooks** for monitoring Barrage metrics, handling lease expirations, and managing Kafka bridges.
- **Acceptance Tests** simulating multiple agents publishing/subscribing concurrently, validating lease semantics and backpressure behavior.

## Risk Assessment & Mitigations
| Risk | Impact | Mitigation |
| --- | --- | --- |
| Session churn under load | Message loss or latency spikes | Implement connection pooling with exponential backoff and proactive heartbeats. |
| Lease contention / race conditions | Duplicate processing | Use Deephaven update scripts with conditional filters to ensure atomic claims; maintain idempotency via `agent_events`. |
| Barrage consumer lag | Stale agent decisions | Track consumer offsets and trigger alerts when lag exceeds SLA; dynamically scale agent replicas. |
| Schema drift | Runtime failures | Version schemas, enforce migrations via bootstrap script, and add compatibility checks during startup. |
| Security misconfiguration | Unauthorized access | Mandate PSK/UN+PW in prod, integrate with secrets manager, audit Deephaven access logs. |

## Success Metrics
- **Latency**: < 200 ms median end-to-end from `queued` to `processing` for standard workloads.
- **Throughput**: Sustain 10k messages/sec with < 5% duplicate claims across agent fleets.
- **Reliability**: Zero data loss during planned restarts; automated recovery within 60s for unplanned failures.
- **Observability**: Real-time dashboards showing backlog, error rate, and lease health with < 5s freshness.

## Next Steps
1. Socialize this plan with Deepagents maintainers and secure agreement on schemas and API surface.
2. Prototype `DeephavenBus` against a local Deephaven server to validate lease mechanics.
3. Iterate on metrics queries and dashboards in collaboration with Ops/ML teams.
4. Prepare phased rollout strategy (dev ➝ staging ➝ prod) with clear exit criteria per phase.

