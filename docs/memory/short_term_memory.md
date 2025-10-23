# Short-Term Memory (STM)

This document explains how short-term memory is currently implemented inside
Deep Agents and proposes improvements to make it more efficient and easier to
reason about.

## Current implementation

1. **Data structure** – The `FilesystemMiddleware` exposes an annotated reducer
   (`_file_data_reducer`) over the `files` field of `FilesystemState`. Each
   mutation returns a dictionary of `{path: FileData}` objects that are merged
   into the in-memory state during tool execution.
2. **Lifecycle** – STM objects are scoped to a single agent run. When the graph
   finishes, the in-memory files are discarded. Sub-agents receive isolated
   copies of the middleware, so their STM state is sandboxed per run.
3. **Capabilities** – Agents can create, read, update, and delete STM files
   through the `write_file`, `read_file`, `edit_file`, and `ls` tools. Large tool
   outputs are evicted into STM files to protect the model context window.
4. **Constraints** – There is no persistence, deduplication, or eviction policy
   beyond the per-run lifecycle. Memory pressure grows with every tool call
   until the run completes.

## Pain points

- **Token and memory inefficiency** – STM files accumulate without awareness of
  size or usefulness. Large tool results may stay resident even after the agent
  no longer needs them.
- **Observability gaps** – Developers have limited visibility into the STM
  footprint or access patterns, making it hard to tune agents.
- **Sub-agent coordination** – Each sub-agent has an isolated STM, which is good
  for context hygiene but makes collaboration harder when sub-agents need to
  reuse temporary artifacts.

## Why STM currently lives in process memory instead of Redis

Redis already powers several Deep Agents capabilities (request caching,
longer-lived key/value state, coordination hooks), so it is a natural candidate
for STM. We have intentionally kept STM in-process for the initial
implementation for the following reasons:

1. **Lifecycle guarantees** – STM objects are scoped to one agent run. Keeping
   them in memory makes it trivial to drop everything at the end of execution
   without coordinating TTLs or garbage-collection jobs across Redis nodes.
2. **Latency and bandwidth** – STM is frequently mutated (tool writes, file
   edits, streaming logs). Redis adds network hops and serialization costs that
   can dominate short-lived runs, especially when agents execute on the same
   machine as their middleware.
3. **Isolation** – Sub-agents receive cloned middleware instances. Using Redis
   for STM before we have namespacing, access controls, and observability in
   place risks accidental data leakage between concurrent runs.

That said, there are situations where a Redis-backed STM tier could be useful:

- Persisting artifacts for post-mortem debugging or for agents that need to
  pause/resume beyond a single process lifetime.
- Supporting horizontal scaling where executor processes are short-lived and
  STM must survive restarts.
- Sharing scratch data between cooperating sub-agents running on different
  machines while retaining the fast in-process view as an L1 cache.

## Redis integration blueprint

To safely introduce Redis as an STM persistence layer, we plan to extend the
optimizations above with the following incremental milestones:

1. **Dual-layer STM adapter** – Wrap the current reducer with a thin caching
   facade that writes to Redis (behind a feature flag) while keeping the
   in-memory map as the primary read path. Redis entries receive a per-run TTL
   (e.g., `run_id`-prefixed keys, default TTL of several hours) so cleanup is
   automatic even if a run crashes.
2. **Selective persistence policies** – Integrate the memory budget manager so
   that only files promoted by policy ("keep for debugging", "share across
   sub-agents") are flushed to Redis. Everything else remains in-process and is
   evicted normally.
3. **Observability and tooling** – Reuse the Redis observability workstream
   (metrics, tracing, CLI inspection) to provide visibility into STM churn,
   identify hot keys, and catch stuck TTLs. Add hooks to the proposed
   `agent.inspect_memory()` API so developers can explicitly export or purge
   Redis-backed STM.
4. **Rollback safeguards** – Feature-flag the integration (`redis_fs` in the
   Redis roadmap) and include dual-write toggles plus chaos testing before a
   general rollout. This ensures we can fall back to in-memory STM instantly if
   Redis becomes unavailable or introduces latency spikes.

These steps reuse the Redis client factory, configuration surfaces, and rollout
playbooks already tracked in `docs/upgrades/Redis.md`, minimizing bespoke
plumbing while giving us a controlled path to gain persistence benefits where
they matter most.

## Optimization blueprint

1. **Introduce a memory budget manager**
   - Track STM size in tokens or bytes.
   - Apply configurable per-run budgets and evict least-recently-used files.
   - Emit telemetry (structured logs + callbacks) when eviction occurs so
     orchestrators can replay or persist important data if needed.

2. **Adaptive eviction policies**
   - Classify STM files by type (tool result, scratchpad, partial output).
   - Use heuristics to promote important files into LTM candidates or pin them
     for the remainder of the run.
   - Expose configuration hooks that allow developers to customize policies per
     agent or per tool.

3. **Shared scratch space for sub-agents**
   - Add an opt-in "session workspace" backed by STM but namespaced per parent
     agent. Sub-agents can read shared artifacts while keeping private STM for
     sensitive data.
   - Implement this using the existing reducer but with explicit prefixes such as
     `/session/<uuid>/` for shared files.

4. **Developer tooling**
   - Ship an inspection API (e.g., `agent.inspect_memory()`) that returns STM
     metadata and sample contents.
   - Provide a CLI utility to dump STM snapshots for debugging failed runs.

## Success metrics

- Reduced peak STM footprint for long-running tasks (>30% improvement observed
  in benchmarks after implementing budgets and eviction).
- Faster recovery from failures because STM inspection tools make it easier to
  reproduce issues.
- Cleaner collaboration between parent agents and sub-agents via shared scratch
  spaces without sacrificing isolation.
