# Memory Architecture Overview

This mini-guide summarizes how Deep Agents orchestrate short-term and long-term
memory today, and introduces a blueprint for an optimized upgrade path. It is
intended as the hub for the memory documentation set.

## Current architecture snapshot

Deep Agents ship with a filesystem middleware that manages an in-memory
mock filesystem as short-term memory and can optionally project files into a
persistent LangGraph store when long-term memory is enabled. The
`create_deep_agent` helper wires this middleware into the root agent as well as
into all spawned sub-agents so that both layers share consistent semantics.

- **Short-term memory (STM)** lives inside the middleware state reducer where
  file mutations are merged into an ephemeral `FilesystemState`. These objects
  persist only for the lifetime of the execution.
- **Long-term memory (LTM)** is opt-in and depends on a `BaseStore` provided by
  the LangGraph runtime. When enabled the middleware transparently mirrors file
  writes into the store under a `/memories/` namespace and loads them back on
  demand.
- **Propagation to sub-agents** happens because the same middleware stack is
  injected into the sub-agent template inside `SubAgentMiddleware`, with the
  long-term flag passed through from the parent configuration.

## Design documents

| Document | Purpose |
| --- | --- |
| [short_term_memory.md](./short_term_memory.md) | Captures the STM data model and control flow and outlines optimization opportunities. |
| [long_term_memory.md](./long_term_memory.md) | Details the LTM design, persistence requirements, and evolution path. |
| [optimization_research.md](./optimization_research.md) | Surveys open-source techniques and libraries that can power the proposed improvements. |

## Next steps

Each document contains concrete action items and references. When combined they
provide a roadmap for building a robust, observable, and scalable memory stack
for Deep Agents and their sub-agents.
