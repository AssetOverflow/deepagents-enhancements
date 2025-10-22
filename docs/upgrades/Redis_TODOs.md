# Redis Upgrade Delivery Checklist

Use this checklist to track execution of the Redis program. Each item links to the blueprint phases and records responsible agents plus dependencies. Pair this view with the detailed Codex task board in `docs/upgrades/Redis_Tasks.md` for execution-ready tickets.

## Legend
- **Owner** — Primary agent accountable for delivery.
- **Support** — Secondary collaborators.
- **Deps** — Blocking prerequisites or artifacts.

## Phase 0 — Research & Foundations
- [ ] Redis deployment decision memo (standalone vs cluster, managed vs self-hosted). **Owner:** Agent Atlas. **Support:** Agent Pulse. **Deps:** Benchmark sandbox.
- [ ] Serialization + schema contract ADR covering MessagePack, JSON fallbacks, and version tagging. **Owner:** Agent Atlas. **Support:** Agent Forge. **Deps:** Redis client factory spike.
- [ ] Redis client factory with retry/backoff defaults landed in `src/deepagents/redis/client.py`. **Owner:** Agent Forge. **Support:** Agent Sentry. **Deps:** ADR approval.
- [ ] Migration CLI skeleton checked into `src/deepagents/cli/redis_migrate.py`. **Owner:** Agent Forge. **Support:** Agent Scribe. **Deps:** Client factory.

## Phase 1 — Cache Enablement (`redis_cache`)
- [ ] Implement `RedisBaseCache` satisfying LangChain `BaseCache`. **Owner:** Agent Forge. **Support:** Agent Atlas. **Deps:** Redis client factory.
- [ ] `create_deep_agent` config plumbing and feature flag toggles (env + kwargs). **Owner:** Agent Forge. **Support:** Agent Scribe. **Deps:** RedisBaseCache.
- [ ] Benchmark harness + report comparing cache hit/miss latencies. **Owner:** Agent Pulse. **Support:** Agent Sentry. **Deps:** Flagged agent build.
- [ ] Observability instrumentation (hit/miss counters, error logs). **Owner:** Agent Sentry. **Support:** Agent Forge. **Deps:** RedisBaseCache.

## Phase 2 — Todo & Plan Persistence (`redis_todos`)
- [ ] `RedisTodoRepository` with Lua-backed atomic ops and optimistic locking. **Owner:** Agent Forge. **Support:** Agent Atlas. **Deps:** Serialization ADR.
- [ ] Middleware adapter layering Redis on top of existing todo reducer. **Owner:** Agent Forge. **Support:** Agent Pulse. **Deps:** Repository implementation.
- [ ] Background reconciliation worker + alerting story. **Owner:** Agent Sentry. **Support:** Agent Pulse. **Deps:** Middleware adapter.
- [ ] Migration tooling to backfill in-memory todo state. **Owner:** Agent Forge. **Support:** Agent Scribe. **Deps:** Migration CLI skeleton.

## Phase 3 — Filesystem Persistence (`redis_fs`)
- [ ] Define `StorageBackend` protocol and update `FilesystemMiddleware` to consume it. **Owner:** Agent Forge. **Support:** Agent Atlas. **Deps:** ADR update.
- [ ] Redis-backed storage implementation (chunking, TTL, spillover to disk/S3). **Owner:** Agent Forge. **Support:** Agent Pulse. **Deps:** StorageBackend protocol.
- [ ] Conflict resolution & dual-write documentation. **Owner:** Agent Scribe. **Support:** Agent Sentry. **Deps:** Redis backend implementation.
- [ ] Load tests covering 10MB+ artifacts and concurrent writers. **Owner:** Agent Pulse. **Support:** Agent Sentry. **Deps:** Redis backend implementation.

## Phase 4 — Coordination & Pub/Sub (`redis_coord`)
- [ ] Event envelope schema + channel taxonomy ADR. **Owner:** Agent Atlas. **Support:** Agent Forge. **Deps:** Foundations complete.
- [ ] Pub/sub listener integration in `SubAgentMiddleware`. **Owner:** Agent Forge. **Support:** Agent Pulse. **Deps:** Event schema ADR.
- [ ] Backpressure, dedupe, and retry strategy implementation. **Owner:** Agent Forge. **Support:** Agent Sentry. **Deps:** Listener integration.
- [ ] Multi-agent collaboration demo + documentation. **Owner:** Agent Scribe. **Support:** Agent Pulse. **Deps:** Listener integration.

## Phase 5 — Observability & Hardening
- [ ] OpenTelemetry metrics/tracing instrumentation for Redis operations. **Owner:** Agent Sentry. **Support:** Agent Forge. **Deps:** Client factory + cache/todo integrations.
- [ ] Resilience features (circuit breakers, health checks, connection pooling). **Owner:** Agent Forge. **Support:** Agent Sentry. **Deps:** Prior phases.
- [ ] Chaos + load test suite with automated reporting. **Owner:** Agent Pulse. **Support:** Agent Sentry. **Deps:** Resilience features.
- [ ] Runbook + rollout playbook publication in `docs/operations/redis.md`. **Owner:** Agent Scribe. **Support:** Scrum Master Nova. **Deps:** Chaos test results.

## Program Management
- [ ] Weekly status digest distributed to stakeholders. **Owner:** Scrum Master Nova. **Support:** Agent Scribe. **Deps:** Inputs from all streams.
- [ ] Cross-agent design/implementation review cadence maintained. **Owner:** Scrum Master Nova. **Support:** All agents. **Deps:** Calendar invites.
- [ ] GA readiness checklist signed off (tests, docs, on-call). **Owner:** Scrum Master Nova. **Support:** Agent Sentry. **Deps:** All prior phases complete.
