# Redis Upgrade Blueprint

## Repository Deep Dive
- **Agent Entry Point:** `create_deep_agent` orchestrates graph assembly, layering in middleware such as `TodoListMiddleware`, `FilesystemMiddleware`, and `SubAgentMiddleware`. It already accepts optional feature toggles (interrupts, human-in-the-loop) that we can mirror for Redis flags. 【F:src/deepagents/graph.py†L24-L139】
- **Todo Handling:** Todos currently live exclusively in LangGraph reducer state (`TodoListMiddleware`). No persistence bridge exists, so Redis must become the authoritative store with optional in-memory mirrors for latency-sensitive reads. 【F:src/deepagents/graph.py†L88-L119】
- **Filesystem Tools:** `FilesystemMiddleware` mixes LangGraph store usage and direct disk I/O for file reads/writes. It exposes reducer helpers (`_file_data_reducer`, `_create_file_data`) that we can wrap with Redis-backed serialization. 【F:src/deepagents/middleware/filesystem.py†L1-L230】
- **Sub-agent Coordination:** `SubAgentMiddleware` dynamically spawns sub-agents but relies on shared reducers and the todo list for cross-agent state. There is no dedicated coordination channel; Redis pub/sub can fill this gap. 【F:src/deepagents/middleware/subagents.py†L300-L470】
- **Configuration Surface:** There is no global settings object today. Redis connectivity should be plumbed through `create_deep_agent` parameters and propagated into middleware constructors to avoid global state.

## Target Architecture
```
+-------------------+        +----------------------+        +-------------------+
| Agent Runtime     |        | Redis Interface      |        | External Systems |
|  (LangGraph)      |<------>|  (Client + Schema)   |<------>|  CLI / UI / S3    |
+-------------------+        +----------------------+        +-------------------+
        ^                             ^     ^                          ^
        |                             |     |                          |
        |                             |     |                          |
        |                     +-------+     +-------+
        |                     |                     |
   Todo Middleware     Filesystem Middleware   Sub-agent Middleware
```
Redis becomes the primary persistence layer for:
1. **Operational State:** Todos, plan metadata, and file manifests are stored as Redis-native structures with optimistic concurrency controls.
2. **Artifact Storage:** Small/medium file contents and tool outputs remain in Redis; large blobs spill over to disk or object storage referenced by Redis metadata.
3. **Coordination Fabric:** Pub/sub channels propagate events so agents and future UI surfaces receive near-real-time updates.
4. **Caching & Rate Limiting:** TTL-backed caches capture expensive tool responses while per-resource locks prevent conflicting writes.

## Data Model (Draft)
| Concern | Redis Structure | Key Pattern | Notes |
| --- | --- | --- | --- |
| Todos | Sorted Set (`ZADD`) | `deepagents:{workspace}:todos` | Score encodes priority or created timestamp. |
| Todo Metadata | Hash (`HSET`) | `deepagents:{workspace}:todo:{id}` | Tracks description, status, owner, timestamps. |
| File Index | Hash | `deepagents:{workspace}:files:{path}` | Metadata, content_version, checksum, size, storage_tier. |
| File Chunks | Stream/List | `deepagents:{workspace}:files:{path}:chunk:{n}` | Allows chunked writes with ETag-style versioning. |
| Tool Cache | String + TTL | `deepagents:{workspace}:cache:{tool}:{hash}` | Supports codec negotiation (JSON vs MessagePack). |
| Event Bus | Pub/Sub Channel | `deepagents:{workspace}:events` | Envelope `{type, resource, actor, payload}`. |
| Locks | Redlock Key | `deepagents:{workspace}:lock:{resource}` | Use bounded TTL + fencing tokens. |
| Metrics | TimeSeries/Counter | `deepagents:metrics:{metric}` | Optional; could use RedisTimeSeries module when available. |

## Progressive Delivery Plan
### Phase 0 — Foundations
1. Stand up shared Redis client factory (`redis.asyncio.Redis`) with retry/backoff defaults.
2. Define serialization contracts (MessagePack primary; JSON fallback) and versioned schema helpers.
3. Establish keyspace naming conventions and linting (CI rule to catch un-namespaced keys).
4. Author migration CLI skeleton to orchestrate opt-in/out during rollout.

### Phase 1 — Cache Enablement (Feature Flag: `redis_cache`)
- Provide `RedisBaseCache` implementing LangChain `BaseCache`. Wire into `create_deep_agent(cache=...)` with minimal surface changes.
- Add benchmark harness comparing cache hit/miss latencies vs in-memory baseline using `examples/` workflows.
- Instrument cache hit rates via metrics hook to validate ROI prior to wider rollout.

### Phase 2 — Todo & Plan State (Feature Flag: `redis_todos`)
- Build `RedisTodoRepository` exposing atomic CRUD via Lua scripts (`EVALSHA`) to avoid race conditions.
- Replace `TodoListMiddleware` state reducer with an adapter that syncs with Redis while keeping an in-memory snapshot for read speed.
- Supply background reconciliation worker to detect divergence and emit alerts (leverages `Agent Sentry`).
- Extend migration CLI to backfill existing sessions and validate data integrity (checksum comparison).

### Phase 3 — Filesystem Persistence (Feature Flag: `redis_fs`)
- Introduce `StorageBackend` protocol so existing `FilesystemMiddleware` can swap between disk and Redis-backed implementations without invasive refactors.
- Implement Redis storage with chunked uploads, streaming reads, and TTL policies. For large files, persist metadata in Redis and stream bodies to disk/S3 with signed URLs recorded in metadata.
- Add version vectors for optimistic locking and conflict detection when dual-writing to disk.

### Phase 4 — Sub-agent Coordination & Pub/Sub (Feature Flag: `redis_coord`)
- Define event envelope schema and register channel subscriptions during `SubAgentMiddleware` initialization.
- Implement pub/sub listener tasks to hydrate agent state on events (todos updated, files changed, migrations running, etc.).
- Provide debouncing/backoff strategies to avoid thrashing and ensure idempotent event handling.

### Phase 5 — Observability & Hardening
- Integrate metrics/tracing using OpenTelemetry exporters (latency, throughput, error rates) and log structured audit trails for key changes.
- Add resilience patterns: connection pooling, exponential backoff, circuit breakers, health checks surfaced through CLI.
- Conduct load and chaos tests: simulate Redis failovers, high-throughput workloads, and network partitions. Document outcomes and mitigations.

## Migration & Rollout Strategy
1. **Dual Writes:** Start phases with dual write/read-verify to Redis while retaining existing persistence, gating production use until parity validated.
2. **Feature Flags:** Each phase is gated behind configuration toggles cascading from `create_deep_agent`. Provide environment variable overrides for quick disable.
3. **Rollback Plan:** Maintain ability to fall back to disk/in-memory by snapshotting state pre-cutover and ensuring replay scripts from Redis to legacy stores.
4. **Documentation & Training:** Deliver operator guides for running Redis, diagnosing issues, and interpreting telemetry.

## Risks & Mitigations
- **Operational Complexity:** Managed Redis or orchestrated clusters reduce ops burden; provide Terraform/Terragrunt snippets for reproducible infrastructure.
- **Consistency Guarantees:** Employ Lua scripts + Redlock for multi-key operations, and store version counters to detect lost updates.
- **Memory Pressure:** Implement eviction policies, periodic archival for stale todos/files, and warn when approaching thresholds.
- **Security:** Enforce TLS/AUTH, configure ACLs per workspace, and audit access through central logging.

## Success Criteria
- Redis-backed cache reduces average tool-response latency by ≥30% relative to baseline.
- Todo updates remain consistent under concurrent multi-agent edits with <1% reconciliation drift.
- File operations support >10 MB artifacts without exceeding 95th percentile latency SLO (configurable per deployment).
- Pub/sub enables sub-agent awareness with <2s propagation delay during coordinated tasks.
- Operators report <5m mean time to recovery for simulated Redis outages with documented runbooks.
