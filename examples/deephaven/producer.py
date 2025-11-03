"""Example Deephaven producer for the Deepagents transport."""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict

try:  # pragma: no cover - example script
    from pydeephaven import DHError, Session
except Exception as exc:  # pragma: no cover - dependency not installed in CI
    Session = None  # type: ignore[assignment]
    DHError = Exception  # type: ignore[misc]
    _IMPORT_ERROR = exc
else:
    _IMPORT_ERROR = None


BOOTSTRAP_SCRIPT = """
from deephaven import new_table, merge
from deephaven.column import int_col, long_col, string_col

if "agent_messages" not in globals():
    agent_messages = new_table([
        long_col("ts", []),
        long_col("ingest_ts", []),
        string_col("topic", []),
        string_col("session_id", []),
        string_col("task_id", []),
        string_col("agent_id", []),
        string_col("role", []),
        string_col("msg_type", []),
        string_col("payload_json", []),
        string_col("payload_blob_ref", []),
        int_col("priority", []),
        int_col("ttl_ms", []),
        string_col("lease_owner", []),
        long_col("lease_expires_ts", []),
        string_col("status", []),
    ])
if "agent_events" not in globals():
    agent_events = new_table([
        long_col("ts", []),
        string_col("agent_id", []),
        string_col("session_id", []),
        string_col("event", []),
        string_col("details_json", []),
    ])
if "agent_metrics" not in globals():
    agent_metrics = new_table([
        long_col("window_start", []),
        string_col("agent_id", []),
        string_col("session_id", []),
        long_col("messages_processed", []),
        long_col("avg_latency_ms", []),
        long_col("errors", []),
        long_col("token_usage", []),
        long_col("last_update_ts", []),
    ])
"""


MESSAGE_TEMPLATE = """
from deephaven import merge, new_table
from deephaven.column import int_col, long_col, string_col
import time

_now = time.time_ns()
_new_rows = new_table([
    long_col("ts", [{ts}]),
    long_col("ingest_ts", [_now]),
    string_col("topic", [{topic!s}]),
    string_col("session_id", [{session_id!s}]),
    string_col("task_id", [{task_id!s}]),
    string_col("agent_id", [{agent_id!s}]),
    string_col("role", [{role!s}]),
    string_col("msg_type", [{msg_type!s}]),
    string_col("payload_json", [{payload_json!s}]),
    string_col("payload_blob_ref", [{payload_blob_ref!s}]),
    int_col("priority", [{priority}]),
    int_col("ttl_ms", [{ttl_ms}]),
    string_col("lease_owner", [""]]),
    long_col("lease_expires_ts", [0]),
    string_col("status", ["queued"]),
])
agent_messages = merge([agent_messages, _new_rows]) if "agent_messages" in globals() else _new_rows
agent_events = merge([
    agent_events,
    new_table([
        long_col("ts", [_now]),
        string_col("agent_id", [{agent_id!s}]),
        string_col("session_id", [{session_id!s}]),
        string_col("event", ["publish"]),
        string_col("details_json", [{details_json!s}]),
    ]),
]) if "agent_events" in globals() else new_table([
    long_col("ts", [_now]),
    string_col("agent_id", [{agent_id!s}]),
    string_col("session_id", [{session_id!s}]),
    string_col("event", ["publish"]),
    string_col("details_json", [{details_json!s}]),
])
"""


@dataclass(slots=True)
class DeephavenConfig:
    host: str
    port: int
    token: str | None
    use_tls: bool


def _require_session() -> None:
    if Session is None:
        raise RuntimeError(
            "pydeephaven is required to run the Deephaven examples."
        ) from _IMPORT_ERROR


def open_session(cfg: DeephavenConfig) -> Session:
    """Open a Deephaven session using the supplied configuration."""

    _require_session()
    kwargs: Dict[str, Any] = {
        "host": cfg.host,
        "port": cfg.port,
        "use_https": cfg.use_tls,
    }
    if cfg.token:
        kwargs["auth_token"] = cfg.token
    return Session(**kwargs)


def bootstrap(session: Session) -> None:
    """Ensure the canonical transport tables exist."""

    session.run_script(BOOTSTRAP_SCRIPT)


def publish_message(session: Session, *, payload: Dict[str, Any]) -> None:
    """Append a new message row to `agent_messages` and record an audit event."""

    ts = int(payload.get("ts", datetime.now(tz=timezone.utc).timestamp() * 1_000_000_000))
    script = MESSAGE_TEMPLATE.format(
        ts=ts,
        topic=json.dumps(payload["topic"]),
        session_id=json.dumps(payload["session_id"]),
        task_id=json.dumps(payload.get("task_id", "")),
        agent_id=json.dumps(payload.get("agent_id", "producer")),
        role=json.dumps(payload.get("role", "agent")),
        msg_type=json.dumps(payload.get("msg_type", "text")),
        payload_json=json.dumps(payload.get("payload_json", "{}")),
        payload_blob_ref=json.dumps(payload.get("payload_blob_ref", "")),
        priority=int(payload.get("priority", 0)),
        ttl_ms=int(payload.get("ttl_ms", 300_000)),
        details_json=json.dumps(json.dumps({"task_id": payload.get("task_id", "") })),
    )
    session.run_script(script)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=os.getenv("DEEPHAVEN_HOST", "localhost"))
    parser.add_argument("--port", type=int, default=int(os.getenv("DEEPHAVEN_PORT", "10000")))
    parser.add_argument("--api-token", default=os.getenv("DEEPHAVEN_API_TOKEN"))
    parser.add_argument("--use-tls", action="store_true", default=os.getenv("DEEPHAVEN_USE_TLS") == "1")
    parser.add_argument("--session-id", default="demo-session")
    parser.add_argument("--task-id", default="demo-task")
    parser.add_argument("--topic", default="planning")
    parser.add_argument("--message", default="Hello from Deepagents!")
    parser.add_argument("--priority", type=int, default=0)
    parser.add_argument("--bootstrap-only", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    cfg = DeephavenConfig(
        host=args.host,
        port=args.port,
        token=args.api_token,
        use_tls=args.use_tls,
    )

    try:
        with open_session(cfg) as session:
            bootstrap(session)
            if args.bootstrap_only:
                print("Bootstrap complete; exiting.")
                return 0

            payload = {
                "topic": args.topic,
                "session_id": args.session_id,
                "task_id": args.task_id,
                "agent_id": "deephaven-demo-producer",
                "role": "agent",
                "msg_type": "text",
                "payload_json": json.dumps({"message": args.message}),
                "priority": args.priority,
            }
            publish_message(session, payload=payload)
            print("Published message to Deephaven bus.")
    except DHError as err:
        print(f"Deephaven error: {err}", file=sys.stderr)
        return 2
    except Exception as err:  # pragma: no cover - example diagnostics
        print(f"Unexpected error: {err}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover - script entry point
    sys.exit(main())
