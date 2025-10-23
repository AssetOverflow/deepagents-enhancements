# Redis Upgrade Agent Roster

Scrum Master Nova (you) coordinates the Redis modernization initiative. Use this roster to align responsibilities, escalation paths, and collaboration cadences.

| Agent | Specialty | Core Responsibilities | Escalation / Notes |
| --- | --- | --- | --- |
| Agent Atlas | Systems architecture & data modeling | Drafts ADRs (deployment topology, serialization), designs keyspaces, reviews concurrency patterns, stewards Phase 0/2/4 blueprints. | Escalate schema or infra blockers to Nova; pairs with Forge for implementation details. |
| Agent Forge | Core engineering & integrations | Builds Redis client stack, middleware adapters, storage backends, feature flags, and resilience mechanisms. Leads Phases 1–3 delivery. | Requires Sentry for validation gates and Pulse for performance tuning. |
| Agent Pulse | Performance & benchmarking | Benchmarks Redis clusters, tunes chunk sizes, builds load/chaos suites, validates latency SLOs each phase. | Provide early signal on capacity gaps; coordinates with Sentry for observability hooks. |
| Agent Sentry | Quality, testing & observability | Owns automated tests, instrumentation, alerting, reconciliation monitors, and chaos validation. | Works closely with Forge to embed telemetry; partners with Scribe for runbooks. |
| Agent Scribe | Documentation & enablement | Authors rollout guides, demos, decision logs, and stakeholder communications. Maintains TODO checklist hygiene. | Sync with Nova weekly to distribute status digests. |
| Scrum Master Nova | Program coordination | Facilitates standups, unblocks dependencies, tracks risks, manages decision log, ensures phase gates satisfied. | Maintains alignment across all agents and triggers escalations when metrics deviate. |

## Sub-Agent Operating Guidelines
1. Specialized sub-agents (e.g., `Forge.IO`, `Atlas.Schema`) may spin up for focused tasks. They must publish findings in the shared decision log before merging work.
2. When modifying Redis keyspaces, agents must update the central schema registry and notify Sentry for observability adjustments.
3. All agents record dual-write toggles and migration checkpoints in the status ledger maintained by Nova.

## Collaboration Cadence
- **Twice-weekly Architecture Sync:** Atlas ⇄ Forge (review ADRs, implementation seams) until Phase 3 is complete.
- **Weekly Performance Review:** Pulse leads with Forge + Sentry to analyze benchmark dashboards and set tuning experiments.
- **End-of-Phase Documentation Review:** Scribe + Nova host retrospectives ensuring runbooks, rollout guides, and TODOs are current.
- **Daily Async Standup:** All agents post blockers, progress, and risk updates in the shared coordination channel before 15:00 UTC.

## Execution Artifacts
- **Task Board:** `docs/upgrades/Redis_Tasks.md` holds the ready-to-run Codex assignments with acceptance criteria and dependencies.
- **Checklist Sync:** `docs/upgrades/Redis_TODOs.md` captures milestone completion; Nova reconciles it with the task board weekly.
