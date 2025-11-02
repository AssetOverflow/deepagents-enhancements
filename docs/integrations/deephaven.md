# Deephaven Integration Configuration

DeepAgents can connect to a Deephaven server to stream agent telemetry and
messages. The integration is optional and controlled through the
`deepagents.config` helpers introduced for this release.

## Python Configuration Helpers

Use the dataclasses in `deepagents.config` to build strongly-typed settings:

```python
from deepagents.config import (
    DeephavenAuthSettings,
    DeephavenSettings,
    DeephavenTableSettings,
)

settings = DeephavenSettings(
    uri="grpc://deephaven:10000",
    auth=DeephavenAuthSettings(method="psk", api_key="change-me"),
    tables=DeephavenTableSettings(
        messages="agent_messages",
        events="agent_events",
        metrics="agent_metrics",
    ),
)
```

`load_deephaven_settings` reads dictionaries and environment variables, making
it easy to hydrate configuration from LangGraph's `get_config()` metadata or
12-factor style deployments. When no Deephaven connection details are present
the helper returns `None`, allowing the integration to remain optional:

```python
from deepagents.config import load_deephaven_settings

settings = load_deephaven_settings({
    "deephaven": {
        "uri": "grpc://deephaven:10000",
        "auth": {"method": "userpass", "username": "bot", "password": "secret"},
    }
})
```

## Supported Settings

| Setting | Environment Variable | Description | Default |
| --- | --- | --- | --- |
| `uri` | `DEEPAGENTS_DEEPHAVEN_URI` | Connection URI for Barrage/Flight. Required. | _none_ |
| `update_graph` | `DEEPAGENTS_DEEPHAVEN_UPDATE_GRAPH` | Deephaven update graph used by the session. | `graph_default` |
| `tables.messages` | `DEEPAGENTS_DEEPHAVEN_MESSAGES_TABLE` | Message queue table name. | `agent_messages` |
| `tables.events` | `DEEPAGENTS_DEEPHAVEN_EVENTS_TABLE` | Audit/event log table. | `agent_events` |
| `tables.metrics` | `DEEPAGENTS_DEEPHAVEN_METRICS_TABLE` | Metrics aggregate table. | `agent_metrics` |
| `auth.method` | `DEEPAGENTS_DEEPHAVEN_AUTH_METHOD` | `none`, `psk`, `token`, or `userpass`. | `none` |
| `auth.api_key` | `DEEPAGENTS_DEEPHAVEN_API_KEY` | Pre-shared key when `method="psk"`. | _none_ |
| `auth.token` | `DEEPAGENTS_DEEPHAVEN_TOKEN` | Bearer token when `method="token"`. | _none_ |
| `auth.username` | `DEEPAGENTS_DEEPHAVEN_USERNAME` | Username when `method="userpass"`. | _none_ |
| `auth.password` | `DEEPAGENTS_DEEPHAVEN_PASSWORD` | Password when `method="userpass"`. | _none_ |

## Validation Rules

- The URI must be provided either by configuration or by environment
  variable.
- Authentication requirements are enforced based on the selected method.
- Table names and the update graph must be non-empty strings.

## Quickstart

1. Install the optional client dependency:
   ```bash
   uv pip install pydeephaven
   ```
2. Export the minimum environment variables:
   ```bash
   export DEEPAGENTS_DEEPHAVEN_URI="grpc://localhost:10000"
   export DEEPAGENTS_DEEPHAVEN_AUTH_METHOD="psk"
   export DEEPAGENTS_DEEPHAVEN_API_KEY="change-me"
   ```
3. Call `load_deephaven_settings()` during agent bootstrap to obtain a
   validated `DeephavenSettings` instance. If the function returns `None`,
   skip Deephaven initialization.

For production deployments, ensure the Deephaven server has the referenced
update graph and table names provisioned before starting DeepAgents instances.
