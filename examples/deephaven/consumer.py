"""Example Deephaven consumer for the Deepagents transport."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from typing import Any, List

try:  # pragma: no cover - example script
    from pydeephaven import DHError, Session
except Exception as exc:  # pragma: no cover - dependency not installed in CI
    Session = None  # type: ignore[assignment]
    DHError = Exception  # type: ignore[misc]
    _IMPORT_ERROR = exc
else:
    _IMPORT_ERROR = None


CLAIM_TEMPLATE = """
from deephaven import merge, new_table
from deephaven.column import long_col, string_col
import time

_now = time.time_ns()
_pending = agent_messages.where({topic_filter}).head({limit})
_claimed = _pending.update([
    "status = `processing`",
    "payload_json = payload_json",
    "payload_blob_ref = payload_blob_ref",
    {lease_owner_expr},
    {lease_expiry_expr},
])
_remaining = agent_messages.where_not_in(_pending, on=["ts", "session_id", "task_id"])
agent_messages = merge([_remaining, _claimed])
__claimed__ = _claimed
"""


ACK_TEMPLATE = """
from deephaven import merge, new_table
from deephaven.column import long_col, string_col
import time

_condition = {condition}
_now = time.time_ns()
agent_messages = agent_messages.update([
    f"status = iif({_condition}, `done`, status)",
    f"lease_owner = iif({_condition}, \"\", lease_owner)",
    f"lease_expires_ts = iif({_condition}, 0L, lease_expires_ts)",
])
agent_events = merge([
    agent_events,
    new_table([
        long_col("ts", [_now]),
        string_col("agent_id", [{agent_id!s}]),
        string_col("session_id", [{session_id!s}]),
        string_col("event", [{event!s}]),
        string_col("details_json", [{details_json!s}]),
    ]),
])
"""


RELEASE_TEMPLATE = """
from deephaven import merge
_condition = {condition}
agent_messages = agent_messages.update([
    f"status = iif({_condition}, `queued`, status)",
    f"lease_owner = iif({_condition}, \"\", lease_owner)",
    f"lease_expires_ts = iif({_condition}, 0L, lease_expires_ts)",
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
    _require_session()
    kwargs: dict[str, Any] = {
        "host": cfg.host,
        "port": cfg.port,
        "use_https": cfg.use_tls,
    }
    if cfg.token:
        kwargs["auth_token"] = cfg.token
    return Session(**kwargs)


def _fetch_rows(session: Session, table_name: str) -> List[dict[str, Any]]:
    table = session.open_table(table_name)
    try:
        if hasattr(table, "to_arrow"):
            return table.to_arrow().to_pylist()
        if hasattr(session, "fetch_table"):
            return session.fetch_table(table).to_arrow().to_pylist()
        raise RuntimeError("Session does not expose an arrow fetch API")
    finally:
        release = getattr(session, "release_table", None)
        if callable(release):
            try:
                release(table)
            except TypeError:
                release(table_name)


def claim_messages(
    session: Session,
    *,
    topic: str,
    session_id: str | None,
    limit: int,
    lease_owner: str,
    lease_timeout_s: int,
) -> List[dict[str, Any]]:
    filters: List[str] = [f"topic == {json.dumps(topic)}", "status == `queued`"]
    if session_id:
        filters.append(f"session_id == {json.dumps(session_id)}")
    filter_expr = " && ".join(filters)
    script = CLAIM_TEMPLATE.format(
        topic_filter=json.dumps(filter_expr),
        limit=limit,
        lease_owner_expr=f"\"lease_owner = `{lease_owner}`\"",
        lease_expiry_expr=f"\"lease_expires_ts = _now + {lease_timeout_s * 1_000_000_000}\"",
    )
    session.run_script(script)
    return _fetch_rows(session, "__claimed__")


def ack_message(
    session: Session,
    *,
    ts: int,
    session_id: str,
    task_id: str,
    agent_id: str,
    event: str = "ack",
) -> None:
    condition = json.dumps(
        " && ".join(
            [
                f"ts == {ts}",
                f"session_id == {json.dumps(session_id)}",
                f"task_id == {json.dumps(task_id)}",
            ]
        )
    )
    script = ACK_TEMPLATE.format(
        condition=condition,
        agent_id=json.dumps(agent_id),
        session_id=json.dumps(session_id),
        event=json.dumps(event),
        details_json=json.dumps(json.dumps({"task_id": task_id})),
    )
    session.run_script(script)


def release_message(session: Session, *, ts: int, session_id: str, task_id: str) -> None:
    condition = json.dumps(
        " && ".join(
            [
                f"ts == {ts}",
                f"session_id == {json.dumps(session_id)}",
                f"task_id == {json.dumps(task_id)}",
            ]
        )
    )
    session.run_script(RELEASE_TEMPLATE.format(condition=condition))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=os.getenv("DEEPHAVEN_HOST", "localhost"))
    parser.add_argument("--port", type=int, default=int(os.getenv("DEEPHAVEN_PORT", "10000")))
    parser.add_argument("--api-token", default=os.getenv("DEEPHAVEN_API_TOKEN"))
    parser.add_argument("--use-tls", action="store_true", default=os.getenv("DEEPHAVEN_USE_TLS") == "1")
    parser.add_argument("--topic", default="planning")
    parser.add_argument("--session-id", dest="session_id", default=os.getenv("DEEPHAVEN_SESSION_ID"))
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--lease-owner", default="deephaven-demo-consumer")
    parser.add_argument("--lease-timeout", type=int, default=300)
    parser.add_argument("--poll-interval", type=float, default=1.5)
    parser.add_argument("--health-check", action="store_true")
    parser.add_argument("--force-release", action="store_true")
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
            if args.health_check:
                session.run_script("assert 'agent_messages' in globals()")
                print("Deephaven transport tables reachable.")
                return 0

            print(
                f"Consuming Deephaven messages on topic={args.topic!r}, lease_owner={args.lease_owner!r}"
            )
            while True:
                rows = claim_messages(
                    session,
                    topic=args.topic,
                    session_id=args.session_id,
                    limit=args.limit,
                    lease_owner=args.lease_owner,
                    lease_timeout_s=args.lease_timeout,
                )
                if not rows:
                    time.sleep(args.poll_interval)
                    continue

                for row in rows:
                    payload = json.loads(row["payload_json"] or "{}")
                    print(f"Processing task={row['task_id']} payload={payload}")
                    if args.force_release:
                        release_message(
                            session,
                            ts=row["ts"],
                            session_id=row["session_id"],
                            task_id=row["task_id"],
                        )
                        print("Released lease back to queue.")
                    else:
                        ack_message(
                            session,
                            ts=row["ts"],
                            session_id=row["session_id"],
                            task_id=row["task_id"],
                            agent_id=args.lease_owner,
                        )
                        print("Acknowledged message.")
    except DHError as err:
        print(f"Deephaven error: {err}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:  # pragma: no cover - interactive example
        print("Interrupted; exiting.")
        return 0
    except Exception as err:  # pragma: no cover - diagnostics
        print(f"Unexpected error: {err}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover - script entry point
    sys.exit(main())
