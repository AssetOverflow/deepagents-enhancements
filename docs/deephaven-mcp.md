# Deephaven MCP Operations Guide

Deephaven's Model Context Protocol (MCP) server turns live Deephaven tables into a first-class data plane for Deepagents. This guide walks through deploying the server, authenticating clients, mapping configuration into Deepagents, and exercising the transport/tooling layers that ship with the Deephaven integration.

## 1. Deploy the Deephaven MCP Server

### 1.1 Local and CI Environments

1. **Launch Deephaven Core** – run the standard Docker image with gRPC + Arrow Flight enabled:
   ```bash
   docker run \
     -p 10000:10000 \
     -e JAVA_TOOL_OPTIONS="-Ddeephaven.console.type=python" \
     ghcr.io/deephaven/server:latest
   ```
2. **Add the MCP façade** – layer the `assetoverflow/deephaven-mcp` service next to the core engine. Point it at the Deephaven host, reuse the same secrets, and expose the WebSocket endpoint your agents will dial.
3. **Seed transport tables** – call the bundled CLI once connectivity is verified:
   ```bash
   python -m deepagents.tools.init_deephaven --host localhost --port 10000
   ```
   The CLI uses `pydeephaven` behind the scenes, so ensure the optional dependency is installed via the `deephaven` extra.【F:src/deepagents/tools/init_deephaven.py†L8-L45】

### 1.2 Production Hardening

- Front the MCP endpoint with TLS. Set `DEEPHAVEN_MCP_USE_TLS=true` for downstream clients to enforce encrypted channels.【F:docs/research/deephaven_mcp_integration.md†L217-L223】
- Store tokens in your orchestrator's secrets manager and inject them at runtime; never bake them into container images.【F:docs/research/deephaven_mcp_integration.md†L241-L248】
- Mirror Deephaven transport tables into external analytics (Kafka, object storage) if you require replayable history or disaster recovery, as outlined in the integration blueprint.【F:docs/research/deephaven_mcp_integration.md†L96-L125】

## 2. Authenticate Clients

Deepagents exposes typed settings to standardize authentication flows. Choose one of the supported methods when populating `DeephavenAuthSettings` or the equivalent environment variables.【F:src/deepagents/config/__init__.py†L27-L118】

| Method | Required Fields | Typical Use |
| --- | --- | --- |
| `none` | – | Development clusters or air-gapped CI.
| `psk` | `api_key` | Shared secret distributed to each agent runner.
| `token` | `token` | OAuth/JWT-style bearer token issued by an identity provider.
| `userpass` | `username`, `password` | Legacy deployments without token brokers.

When bootstrapping from environment variables, set:

```bash
export DEEPAGENTS_DEEPHAVEN_URI="grpc://localhost:10000"
export DEEPAGENTS_DEEPHAVEN_AUTH_METHOD="psk"
export DEEPAGENTS_DEEPHAVEN_API_KEY="change-me"
```

The loader returns `None` when no Deephaven settings are detected, allowing you to keep MCP optional in dev sandboxes.【F:docs/integrations/deephaven.md†L25-L41】

## 3. Configuration Variables

Deepagents reads the following keys from mappings or environment variables to configure the transport layer.【F:docs/integrations/deephaven.md†L31-L57】 Combine them with the MCP-specific overrides from the integration blueprint.【F:docs/research/deephaven_mcp_integration.md†L214-L233】

| Purpose | Variable | Description |
| --- | --- | --- |
| Deephaven session | `DEEPAGENTS_DEEPHAVEN_URI` | gRPC/Flight URI consumed by PyDeephaven. |
| Authentication | `DEEPAGENTS_DEEPHAVEN_AUTH_METHOD` | One of `none`, `psk`, `token`, `userpass`. |
| Authentication secret | `DEEPAGENTS_DEEPHAVEN_API_KEY` / `DEEPAGENTS_DEEPHAVEN_TOKEN` / `DEEPAGENTS_DEEPHAVEN_USERNAME` / `DEEPAGENTS_DEEPHAVEN_PASSWORD` | Provide the credential matching your selected method. |
| Table routing | `DEEPAGENTS_DEEPHAVEN_MESSAGES_TABLE`, `DEEPAGENTS_DEEPHAVEN_EVENTS_TABLE`, `DEEPAGENTS_DEEPHAVEN_METRICS_TABLE` | Customize canonical transport table names. |
| Update graph | `DEEPAGENTS_DEEPHAVEN_UPDATE_GRAPH` | Assign sessions to a Deephaven update graph. |
| MCP endpoint | `DEEPHAVEN_MCP_URL` | WebSocket or HTTP URL for the MCP façade.【F:docs/research/deephaven_mcp_integration.md†L217-L233】 |
| MCP auth | `DEEPHAVEN_MCP_TOKEN` | Bearer token presented to the MCP layer.【F:docs/research/deephaven_mcp_integration.md†L217-L233】 |
| MCP TLS toggle | `DEEPHAVEN_MCP_USE_TLS` | Opt into TLS when your MCP endpoint sits behind HTTPS.【F:docs/research/deephaven_mcp_integration.md†L217-L233】 |
| Subscription storage | `DEEPHAVEN_MCP_SUBSCRIPTION_DIR` | Filesystem directory where long-lived streams write checkpoints.【F:docs/research/deephaven_mcp_integration.md†L217-L233】 |

## 4. Specialist Agent Example

The repository ships an asynchronous specialist showcasing how to wire Deephaven MCP tools into a Deepagents planner: [`examples/deephaven_mcp/specialist_agent.py`](../examples/deephaven_mcp/specialist_agent.py). The script registers the MCP server, hydrates tools, and streams responses back to the terminal.【F:examples/deephaven_mcp/specialist_agent.py†L1-L55】

To run it:

```bash
export DEEPHAVEN_MCP_URL="wss://deephaven-mcp.example.com/ws"
export DEEPHAVEN_MCP_TOKEN="<secret>"
uv pip install deephaven-mcp langchain-mcp-adapters
python examples/deephaven_mcp/specialist_agent.py
```

## 5. Working with Transports and Tools

### 5.1 DeephavenBus for Real-Time Message Flow

```python
from deepagents.transports.deephaven_bus import DeephavenBus, DeephavenBusConfig

bus = DeephavenBus(
    DeephavenBusConfig(host="deephaven", port=10000, table_namespace="deepagents")
)
bus.publish({"topic": "planner", "payload_json": json.dumps({"status": "ok"})})
subscription = bus.subscribe(filter_expr="topic == 'planner'", callback=print)
```

`DeephavenBus` handles session retries, message leases, and table bootstrapping automatically when constructed with either a host/port pair or a custom session factory.【F:src/deepagents/transports/deephaven_bus.py†L45-L226】【F:src/deepagents/transports/deephaven_bus.py†L381-L446】 Remember to close subscriptions when finished to stop the background polling thread.【F:src/deepagents/transports/deephaven_bus.py†L61-L104】

### 5.2 DeephavenTransport in Agent Sessions

```python
from deepagents.transports import DeephavenTransport

transport = DeephavenTransport(session=pydeephaven_session)
messages = transport.list_messages(session_id="abc123")
```

The transport ensures schemas exist at initialization and exposes helper accessors over the canonical tables.【F:src/deepagents/transports/deephaven_transport.py†L1-L27】 Pair it with `bootstrap_deephaven_tables` when you need to seed tables outside of agent startup routines.【F:src/deepagents/transports/deephaven_schema.py†L200-L236】

### 5.3 CLI Table Bootstrapper

```bash
python -m deepagents.tools.init_deephaven --host deephaven --port 10000 --auth-token "$DEEPHAVEN_TOKEN"
```

The CLI wraps `bootstrap_deephaven_tables`, closing sessions on completion and exiting with status `0` when schemas are healthy.【F:src/deepagents/tools/init_deephaven.py†L8-L45】

## 6. Troubleshooting Connectivity

| Symptom | Likely Cause | Resolution |
| --- | --- | --- |
| `RuntimeError: Failed to establish Deephaven session` when instantiating `DeephavenBus`. | PyDeephaven cannot connect or authenticate. | Verify `DEEPAGENTS_DEEPHAVEN_URI`, credentials, and that the server is reachable; the bus retries with exponential backoff but eventually raises if the session never comes up.【F:src/deepagents/transports/deephaven_bus.py†L435-L452】 |
| Messages remain in `queued` status. | Lease heartbeats are not updating or TTL expired. | Adjust `default_ttl_ms`/`heartbeat_interval_s` in `DeephavenBusConfig` and ensure worker loops call `heartbeat` while processing.【F:src/deepagents/transports/deephaven_bus.py†L45-L193】 |
| `SchemaBootstrapError` during table bootstrap. | Existing tables have mismatched column types. | Inspect the reported columns, drop/recreate the tables, or run the CLI with `--replace` logic by re-running `bootstrap_deephaven_tables` to enforce the canonical schema.【F:src/deepagents/transports/deephaven_schema.py†L200-L236】 |
| `pydeephaven package is required` error when invoking the CLI. | Optional dependency not installed. | Install the `deephaven` extra (`uv pip install deepagents[deephaven]`) before retrying.【F:src/deepagents/tools/init_deephaven.py†L8-L33】 |
| MCP requests return HTTP 401. | Missing/invalid token in MCP headers. | Set `DEEPHAVEN_MCP_TOKEN` and confirm the specialist example injects it via the Authorization header.【F:examples/deephaven_mcp/specialist_agent.py†L17-L45】 |

With these practices, Deephaven MCP becomes a resilient, observable transport surface for Deepagents' long-running, data-intensive workflows.
