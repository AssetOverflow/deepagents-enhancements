"""Bootstrap Deephaven transport schemas from the command line."""
from __future__ import annotations

import argparse
import sys
from typing import Any

from deepagents.transports import bootstrap_deephaven_tables


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Initialize Deephaven transport tables.")
    parser.add_argument("--host", default="localhost", help="Deephaven host (default: localhost)")
    parser.add_argument("--port", default=10000, type=int, help="Deephaven port (default: 10000)")
    parser.add_argument(
        "--auth-token",
        dest="auth_token",
        help="Authentication token or password; behavior depends on Deephaven deployment",
    )
    parser.add_argument(
        "--use-https",
        action="store_true",
        help="Connect using HTTPS instead of HTTP",
    )
    return parser


def _connect_session(host: str, port: int, auth_token: str | None, use_https: bool) -> Any:
    try:
        from pydeephaven import Session
    except ModuleNotFoundError as exc:  # pragma: no cover - optional dependency
        raise SystemExit(
            "pydeephaven package is required for the Deephaven bootstrap CLI. Install the 'deephaven' extra."
        ) from exc

    protocol = "https" if use_https else "http"
    return Session(host=host, port=port, token=auth_token, http_scheme=protocol)


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    session = _connect_session(args.host, args.port, args.auth_token, args.use_https)
    try:
        bootstrap_deephaven_tables(session)
    finally:
        close = getattr(session, "close", None)
        if callable(close):
            close()
    return 0


if __name__ == "__main__":  # pragma: no cover - manual execution path
    sys.exit(main())
