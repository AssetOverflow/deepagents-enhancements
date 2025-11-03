# Deephaven Transport Integration Guide

This guide walks through installing, configuring, and operating the Deephaven-backed transport
(`DeephavenBus`) for Deepagents. Pair it with the architectural roadmap in
[Deephaven Neural Bus Integration Plan](../research/deephaven_neural_bus_plan.md) when you are
rolling the capability into production.

## Prerequisites
- **Deephaven Server** running with Barrage streaming enabled. A single-node deployment works for
  local testing; production clusters should follow the [Deephaven deployment docs](https://deephaven.io/core/docs/)
  with dedicated Update Graphs for control-plane and high-volume traffic.
- **Python 3.10+** environment for Deepagents.
- **Network access** from Deepagents runtimes to the Deephaven server over gRPC/Arrow Flight.
- Optional: **Kafka cluster** if you plan to mirror message tables for durability.

## Installation

### 1. Install Deephaven dependencies
Add the Deephaven extra when installing Deepagents so that the runtime includes `pydeephaven` and
companion packages.

```bash
# uv
uv add "deepagents[deephaven]"

# pip
pip install "deepagents[deephaven]"

# poetry
poetry add "deepagents[deephaven]"
```

If you manage dependencies manually, install the following packages directly:

```bash
pip install pydeephaven deephaven-core deephaven-py-client
```

### 2. Provision Deephaven resources
1. Start the Deephaven server (Docker, Kubernetes, or bare-metal) with persistent storage
   mounted at `/data`.
2. Create a service user or API token for Deepagents and grant permissions on the tables
   described below.
3. Optionally enable TLS via the reverse proxy or ingress controller that fronts the server.

### 3. Bootstrap transport tables
Run the bootstrap script once per environment to create the canonical tables used by the bus.
The script can be invoked via a CLI entry point or by running the example directly:

```bash
uv run python -m examples.deephaven.producer --bootstrap-only
```

The bootstrapper creates:
- `agent_messages`: ticking table used for message exchange and lease management.
- `agent_events`: append-only audit stream.
- `agent_metrics`: aggregated view refreshed via Deephaven queries.

## Configuration
The `DeephavenBus` reads configuration from environment variables or Deepagents' settings layer.
The following table summarizes the required and optional settings:

| Variable | Description | Default |
| --- | --- | --- |
| `DEEPHAVEN_HOST` | Deephaven server host or load balancer DNS name. | `localhost` |
| `DEEPHAVEN_PORT` | Barrage/Flight port (usually `10000`). | `10000` |
| `DEEPHAVEN_USE_TLS` | Set to `1` to enable TLS connections. | `0` |
| `DEEPHAVEN_API_TOKEN` | API token or password for authentication. | _required_ |
| `DEEPHAVEN_SESSION_POOL_SIZE` | Size of the `pydeephaven` session pool. | `4` |
| `DEEPHAVEN_AGENT_MESSAGES_TABLE` | Name of the primary message table. | `agent_messages` |
| `DEEPHAVEN_AGENT_EVENTS_TABLE` | Audit table name. | `agent_events` |
| `DEEPHAVEN_AGENT_METRICS_TABLE` | Aggregated metrics table name. | `agent_metrics` |
| `DEEPHAVEN_KAFKA_MIRROR_TOPIC` | Kafka topic for mirroring bus traffic. | _unset_ |
| `DEEPHAVEN_HEARTBEAT_S` | Interval for session heartbeat checks. | `30` |

Surface these variables through Deepagents' configuration management (e.g., `.env`, Kubernetes
Secrets, or HashiCorp Vault). For multi-tenant deployments, supply per-tenant prefixes and update
the bootstrap script to create isolated table namespaces.

## Operational Guidance

### Health checks
- Run the [health check example](../../examples/deephaven/consumer.py) with `--health-check` to
  verify connectivity, table presence, and streaming updates.
- Monitor Barrage connection health via the Deephaven console (`/ide`) or through exported metrics
  if you have integrated Prometheus.

### Runtime operations
1. **Producer agents** call `DeephavenBus.publish()` (see
   [examples/deephaven/producer.py](../../examples/deephaven/producer.py)) to enqueue messages
   into `agent_messages`. Ensure each payload includes a unique `task_id` and `session_id` so that
   consumers can filter precisely.
2. **Consumer agents** maintain subscriptions using filtered views and lease columns. The consumer
   example demonstrates how to claim, extend, and ack leases with atomic updates.
3. **Metrics ingestion** runs as a background task that reads from `agent_events`, computes rolling
   metrics, and publishes them to `agent_metrics` or your observability pipeline.

### Scaling & resilience
- Scale Deephaven vertically (more CPU/RAM) to improve tick processing latency; horizontally scale
  Deepagents workers to increase throughput.
- Use the session pool to amortize authentication cost. Configure `DEEPHAVEN_SESSION_POOL_SIZE`
  based on the expected concurrency per process.
- Mirror `agent_messages` and `agent_events` to Kafka using Deephaven connectors to guarantee
  durability. Document replay procedures as part of your operational runbook.

### Troubleshooting
- **Stale leases**: Inspect the `lease_expires_ts` column and use the consumer example's
  `--force-release` flag to reset stuck rows.
- **Auth failures**: Rotate the API token and ensure the updated secret propagates to all agents.
- **Schema drift**: Re-run the bootstrap command and compare table definitions against the
  canonical schema in the research plan.

## Next steps
- Implement the production `DeephavenBus` adapter within `src/deepagents/transports/deephaven/`.
- Wire the configuration surface into Deepagents settings and CLI.
- Extend your observability stack with dashboards for queue depth, lease churn, and error rates.

Once these steps are complete, Deepagents can treat Deephaven as a first-class transport for planning,
collaboration, and telemetry workloads.
