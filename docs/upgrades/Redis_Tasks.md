# Redis Modernization — Codex Agent Task Board

This board enumerates the execution-ready tasks that each Codex agent (and their sub-agents) can immediately pick up. Every task includes acceptance criteria, dependency notes, and required outputs so work can proceed asynchronously. Scrum Master Nova owns prioritization and status updates.

## Sprint 0 — Foundations Ready-To-Run Tasks (Week 1)

### Agent Atlas — Architecture & Schema
- [ ] **Author Redis Topology Decision Memo**
  - *Objective:* Compare managed Redis (e.g., Upstash, AWS Elasticache) versus self-hosted cluster for staging + prod.
  - *Inputs:* Benchmark sandbox metrics, security requirements, budget guardrails.
  - *Acceptance Criteria:* Decision log committed under `docs/adr/redis-topology.md` with pros/cons, cost estimates, and recommended path.
  - *Handoff:* Notify Agent Scribe to broadcast summary in next status digest.
- [ ] **Draft Serialization Contract ADR**
  - *Objective:* Lock in MessagePack primary encoding with JSON fallback and schema version tags.
  - *Dependencies:* Redis client factory spike output (Agent Forge).
  - *Acceptance Criteria:* ADR merged with key examples for todos, file manifests, and event envelopes; backward compatibility guidelines documented.
  - *Handoff:* Share with Agent Forge & Sentry before enabling cache integration.

### Agent Forge — Core Engineering
- [ ] **Redis Client Factory Implementation**
  - *Objective:* Ship `src/deepagents/redis/client.py` factory encapsulating connection pooling, retry/backoff, TLS config, and tracing hooks.
  - *Dependencies:* Atlas decision memo for topology endpoints.
  - *Acceptance Criteria:* Unit tests covering retry logic, configuration overrides, and connection errors; documented usage snippet in `docs/upgrades/Redis.md`.
  - *Handoff:* Provide factory interface notes to Atlas and Sentry.
- [ ] **Migration CLI Skeleton**
  - *Objective:* Introduce `src/deepagents/cli/redis_migrate.py` scaffolding with `init`, `dual-write`, and `verify` subcommands.
  - *Dependencies:* Client factory module.
  - *Acceptance Criteria:* CLI runs with `--help`, includes TODO markers for future sub-commands, and is wired into `pyproject.toml` entry points.
  - *Handoff:* Ping Agent Scribe for documentation updates once merged.

### Agent Pulse — Performance & Benchmarking
- [ ] **Benchmark Harness Setup**
  - *Objective:* Establish reproducible benchmark harness referencing `examples/` workflows to measure cache hit/miss latency.
  - *Dependencies:* Redis client factory, feature flag toggles from Forge.
  - *Acceptance Criteria:* Script committed under `tests/perf/test_redis_cache.py` (or similar) with baseline metrics recorded in `docs/upgrades/benchmarks/redis_cache_v0.md`.
  - *Handoff:* Share metrics with Nova for rollout gating.

### Agent Sentry — QA & Observability
- [ ] **Observability Spike**
  - *Objective:* Outline tracing/metrics requirements for Redis operations.
  - *Dependencies:* Client factory interface.
  - *Acceptance Criteria:* Checklist committed under `docs/operations/redis_observability.md` specifying counters, histograms, and alert thresholds.
  - *Handoff:* Align with Pulse before benchmark sprint.

### Agent Scribe — Documentation & Enablement
- [ ] **Status Digest Template**
  - *Objective:* Prepare weekly status digest template summarizing progress, blockers, and next steps.
  - *Dependencies:* Inputs from Nova + roster.
  - *Acceptance Criteria:* Markdown template stored at `docs/upgrades/Redis_StatusDigest_Template.md` with sections for metrics, risks, decisions.
  - *Handoff:* Provide template to Nova for first distribution.

## Sprint 1 — Cache Enablement Tasks (Week 2)

### Agent Forge
- [ ] **RedisBaseCache Implementation**
  - *Objective:* Build `RedisBaseCache` conforming to LangChain `BaseCache` with configurable TTLs and serialization via Atlas contract.
  - *Dependencies:* Serialization ADR approved, client factory stable.
  - *Acceptance Criteria:* Unit + integration tests verifying get/set/delete, TTL expiration, and error handling; feature flag integration in `create_deep_agent`.
  - *Handoff:* Coordinate with Pulse for benchmarks and Sentry for instrumentation.
- [ ] **Feature Flag Plumbing**
  - *Objective:* Add `redis_cache` flag to `create_deep_agent` and propagate to middleware constructors.
  - *Dependencies:* RedisBaseCache implementation.
  - *Acceptance Criteria:* Configuration documented in README section; toggles accessible via env + kwargs; default remains off.

### Agent Pulse
- [ ] **Cache Latency Benchmark Run**
  - *Objective:* Execute harness to capture hit/miss latency improvements and produce comparative charts.
  - *Dependencies:* RedisBaseCache merged, instrumentation toggles available.
  - *Acceptance Criteria:* Report stored at `docs/upgrades/benchmarks/redis_cache_report_v1.md` with raw data artifact link.

### Agent Sentry
- [ ] **Cache Observability Instrumentation**
  - *Objective:* Integrate hit/miss counters, error logs, and tracing spans.
  - *Dependencies:* RedisBaseCache API stable.
  - *Acceptance Criteria:* Metrics exported via configured backend, failing tests for missing instrumentation prevented.

### Agent Scribe
- [ ] **Cache Rollout Guide**
  - *Objective:* Document enablement steps, rollback instructions, and support contacts.
  - *Dependencies:* Feature flag plumbing, observability instrumentation.
  - *Acceptance Criteria:* Guide added to `docs/operations/redis_cache_rollout.md` and referenced in TODO checklist.

## Coordination Protocols
- **Standup Updates:** Each agent posts daily updates using template: `Yesterday / Today / Blockers / Help Needed` referencing the task checkbox above.
- **Status Tracking:** Scrum Master Nova mirrors task status into `docs/upgrades/Redis_TODOs.md` weekly, ensuring alignment between high-level checklist and detailed task board.
- **Escalations:** Blockers >24h escalate to Nova, then to platform leadership if unresolved after 48h.

## Ready-To-Launch Criteria
Before closing Sprint 1, Nova verifies:
1. All Sprint 0 tasks checked off with linked artifacts.
2. Cache feature flag toggles validated in staging and documented runbooks approved by Scribe + Sentry.
3. Benchmark deltas meet success criteria (≥30% latency improvement) or follow-up experiment backlog created for Pulse.

Use this board to seed Codex agent workflows—each checkbox can translate directly into an autonomous execution ticket.
