# Optimization Research & Open-Source Inspirations

This survey highlights open-source projects, libraries, and academic work that
inspire the proposed STM and LTM improvements for Deep Agents.

## Memory state management

- **LangGraph Store API** – LangGraph's built-in `BaseStore` contract already
  supports namespaced items with metadata and is compatible with Redis, SQL, or
  custom backends. Leveraging its streaming API (`stream_changes`) enables
  incremental sync between STM and LTM. [[LangGraph Store](https://python.langchain.com/docs/langgraph/how-tos/memory/store/)]
- **MemGPT** – Demonstrates how agents can juggle STM and LTM by summarizing and
  pruning context dynamically. Its open-source implementation shows how to mix
  rule-based heuristics with embedding search for memory recall. [[MemGPT](https://github.com/cpacker/MemGPT)]
- **Mem0** – Provides a drop-in memory module for LLM agents with support for
  vector search, metadata filtering, and retention policies. Useful reference for
  designing the `MemoryBackend` protocol. [[mem0](https://github.com/n0code-ai/mem0)]

## Semantic retrieval

- **FAISS** – Facebook AI Similarity Search offers fast vector indexing and is a
  common choice for agent memory retrieval due to its speed and memory
  efficiency. [[FAISS](https://github.com/facebookresearch/faiss)]
- **Chroma** – A lightweight embedding database with an easy Python API that
  complements LangChain/LangGraph integrations. Suitable for both local and
  server deployments. [[Chroma](https://github.com/chroma-core/chroma)]
- **Milvus** – A distributed vector database optimized for large-scale memory
  workloads. Useful for scaling multi-agent deployments. [[Milvus](https://github.com/milvus-io/milvus)]

## Observability and governance

- **OpenTelemetry** – Vendor-neutral observability framework that can capture
  traces, metrics, and logs around memory operations. [[OpenTelemetry](https://opentelemetry.io/)]
- **Dagster Asset Checks** – Illustrates how data pipelines enforce quality and
  retention policies; similar techniques can be applied to memory lifecycles.
  [[Dagster](https://github.com/dagster-io/dagster)]
- **Temporal.io workflows** – Provide patterns for transactional state machines
  and retries. Referencing Temporal's workflow model informs the design of
  middleware-level transactions. [[Temporal](https://github.com/temporalio/temporal)]

## Implementation accelerators

- **Sentence Transformers** – Open-source embedding models with permissive
  licenses; `all-MiniLM-L6-v2` balances quality and speed for memory indexing.
  [[Sentence Transformers](https://github.com/UKPLab/sentence-transformers)]
- **sqlitedict** – Offers a simple key-value store on top of SQLite, suitable for
  local persistent LTM during development. [[sqlitedict](https://github.com/RaRe-Technologies/sqlitedict)]
- **Weaviate Client** – Provides Python bindings to the Weaviate vector database
  and includes hybrid search out of the box. [[Weaviate](https://github.com/weaviate/weaviate-python-client)]

These references demonstrate that the proposed memory roadmap aligns with
current best practices in the open-source agent ecosystem while maintaining the
flexibility to adopt the right backend for each deployment scenario.
