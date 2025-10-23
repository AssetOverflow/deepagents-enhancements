# Long-Term Memory (LTM)

This document outlines how Deep Agents integrate persistent memory today and
proposes a robust upgrade path that emphasizes modularity, performance, and
observability.

## Current implementation

1. **Opt-in feature flag** – Callers pass `use_longterm_memory=True` when creating
   a deep agent. The flag is forwarded to both the root agent and all sub-agents
   through the shared middleware template.
2. **Persistence surface** – When LTM is active, the filesystem middleware expects
   a LangGraph `BaseStore` instance. Reads and writes are mirrored to the store
   using a `/memories/` prefix to avoid collisions with STM paths.
3. **Redis integration** – The `create_deep_agent` helper can auto-provision a
   `RedisStore` when Redis settings are supplied, providing an out-of-the-box
   durable backend. A matching Redis-based cache can be enabled for tool results.
4. **Failure handling** – If LTM is requested but no store is available, the
   middleware raises a validation error before the first model call to avoid
   silent data loss.
5. **Namespace isolation** – Store interactions include the assistant ID in the
   namespace when available so multiple assistants can coexist inside the same
   backend without clobbering each other.

## Pain points

- **Store-agnostic abstractions** – There is no first-class interface for
  differentiating between document, key-value, or vector stores. As a result the
  current design handles only verbatim file persistence.
- **Lack of retrieval intelligence** – Agents cannot rank or filter memories. The
  only supported operation is loading entire files by path.
- **Consistency guarantees** – Mirroring logic lives inside tool handlers, which
  makes it harder to reason about transactional integrity when multiple writes
  happen concurrently (e.g., from sub-agents).
- **Observability** – There is minimal insight into LTM utilization, hit rates,
  or latency when fetching from external stores.

## Optimization blueprint

1. **Abstract storage profiles**
   - Define a `MemoryBackend` protocol that wraps common operations: `put`,
     `get`, `search`, `delete`, and `stream_changes`.
   - Provide adapters for key-value stores (Redis, SQLite via `sqlitedict`),
     document databases (LiteLLM persistent store, MongoDB), and vector databases
     (FAISS, Chroma).
   - Allow mixing backends by registering multiple profiles, e.g., `artifact`
     (blob storage) versus `semantic` (vector store).

2. **Add semantic retrieval**
   - Store embeddings for each file revision using an open-source embedding model
     such as `sentence-transformers/all-MiniLM-L6-v2`.
   - Implement a retrieval API that lets agents query memories by natural
     language, optionally combining vector similarity with metadata filters.
   - Surface retrieval results through a dedicated `search_memories` tool that
     returns ranked matches.

3. **Versioned writes and transactions**
   - Wrap store mutations inside a middleware-level transaction context so that
     STM and LTM stay in sync when tool calls succeed or fail.
   - Support multi-writer coordination by attaching revision IDs to each file and
     performing optimistic concurrency checks on update.

4. **Lifecycle management**
   - Introduce retention policies (time-to-live, access-based pruning) that can
     be configured per namespace or per agent role.
   - Emit structured audit events for create/update/delete operations to support
     compliance logging.

5. **Observability toolkit**
   - Integrate OpenTelemetry spans around store operations.
   - Provide a dashboard-ready metrics adapter exposing latency, throughput, and
     cache hit rates (for Redis-backed setups).
   - Include CLI scripts to inspect stored memories and run maintenance tasks
     such as compaction or TTL sweeps.

## Upgrade milestones

1. **Foundations** – Implement the `MemoryBackend` protocol and migrate the
   existing filesystem middleware to use it for verbatim storage.
2. **Semantic search** – Add embedding-based retrieval with a background worker
   that processes new or updated memories.
3. **Governance** – Layer in retention policies, auditing, and observability once
   the storage abstractions are stable.

Delivering these milestones will unlock persistent, queryable institutional
memory for Deep Agents and their sub-agents without sacrificing modularity or
performance.
