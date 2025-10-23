"""Redis-backed implementation of the LangGraph :class:`BaseStore`.

The :class:`RedisStore` provided by this module implements LangGraph's
high-level store operations on top of Redis primitives.  Namespaces are
modelled using Redis sets to keep track of existing keys, and individual items
are stored as compact JSON payloads.  The store supports TTL refresh semantics
and is intentionally synchronous to maximize compatibility with the standard
``redis`` client.  Asynchronous entry points delegate the work to a background
executor.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import Any, Sequence

from langgraph.store.base import (
    BaseStore,
    GetOp,
    Item,
    ListNamespacesOp,
    MatchCondition,
    Op,
    PutOp,
    Result,
    SearchItem,
    SearchOp,
)


class RedisStore(BaseStore):
    """Durable store that persists agent state and files in Redis.

    The store keeps two categories of keys in Redis:

    ``deepagents:store:namespaces``
        A set containing every namespace token currently known to the store.
    ``deepagents:store:item:<namespace_token>:<key>``
        JSON-encoded payload storing the value and metadata for a single item.

    Namespace membership is modelled through dedicated Redis sets per namespace.
    Deletions automatically clean up the membership metadata when a namespace
    becomes empty.
    """

    supports_ttl = True

    def __init__(self, client: Any, *, prefix: str = "deepagents:store") -> None:
        """Create a new store wrapper around a Redis client."""

        self._client = client
        self._prefix = prefix.rstrip(":")
        self._namespaces_key = f"{self._prefix}:namespaces"

    def batch(self, ops: Iterable[Op]) -> list[Result]:
        """Execute store operations synchronously."""

        return [self._dispatch(op) for op in ops]

    async def abatch(self, ops: Iterable[Op]) -> list[Result]:
        """Execute store operations asynchronously."""

        return await asyncio.get_running_loop().run_in_executor(None, self.batch, list(ops))

    def _dispatch(self, op: Op) -> Result:
        """Route an operation to its concrete handler."""

        if isinstance(op, PutOp):
            self._handle_put(op)
            return None
        if isinstance(op, GetOp):
            return self._handle_get(op)
        if isinstance(op, SearchOp):
            return self._handle_search(op)
        if isinstance(op, ListNamespacesOp):
            return self._handle_list_namespaces(op)
        msg = f"Unsupported operation: {type(op)}"
        raise NotImplementedError(msg)

    # ------------------------------------------------------------------
    # Key helpers
    # ------------------------------------------------------------------

    def _namespace_token(self, namespace: Sequence[str]) -> str:
        """Convert a namespace sequence into a stable token."""

        return "/".join(namespace)

    def _namespace_members_key(self, namespace: Sequence[str]) -> str:
        """Return the Redis key that tracks members of ``namespace``."""

        token = self._namespace_token(namespace)
        return f"{self._prefix}:ns:{token}:keys"

    def _item_key(self, namespace: Sequence[str], key: str) -> str:
        """Return the Redis key storing the payload for ``(namespace, key)``."""

        token = self._namespace_token(namespace)
        return f"{self._prefix}:item:{token}:{key}"

    def _decode(self, value: Any) -> str:
        """Normalize Redis values to ``str``."""

        if isinstance(value, bytes):
            return value.decode("utf-8")
        return str(value)

    # ------------------------------------------------------------------
    # CRUD handlers
    # ------------------------------------------------------------------

    def _handle_put(self, op: PutOp) -> None:
        """Persist or delete items based on :class:`PutOp` instructions."""

        namespace = tuple(op.namespace)
        key = str(op.key)
        item_key = self._item_key(namespace, key)

        if op.value is None:
            self._client.delete(item_key)
            members_key = self._namespace_members_key(namespace)
            self._client.srem(members_key, key)
            if not self._client.smembers(members_key):
                self._client.srem(self._namespaces_key, self._namespace_token(namespace))
            return

        now = datetime.now(UTC)
        existing_payload = self._client.get(item_key)
        created_at = now
        if existing_payload is not None:
            parsed = self._safe_load(existing_payload)
            if parsed is not None and "created_at" in parsed:
                created_at = self._parse_datetime(parsed["created_at"])

        value = self._ensure_mapping(op.value)
        payload = json.dumps(
            {
                "value": value,
                "created_at": created_at.isoformat(),
                "updated_at": now.isoformat(),
            },
            separators=(",", ":"),
        )
        ttl_seconds = self._normalize_ttl(op.ttl)
        if ttl_seconds is not None:
            self._client.set(item_key, payload, ex=ttl_seconds)
        else:
            self._client.set(item_key, payload)

        self._client.sadd(self._namespaces_key, self._namespace_token(namespace))
        self._client.sadd(self._namespace_members_key(namespace), key)

    def _handle_get(self, op: GetOp) -> Item | None:
        """Load an item from Redis based on the supplied :class:`GetOp`."""

        namespace = tuple(op.namespace)
        key = str(op.key)
        payload = self._client.get(self._item_key(namespace, key))
        if payload is None:
            self._cleanup_membership(namespace, key)
            return None
        parsed = self._safe_load(payload)
        if parsed is None:
            self._cleanup_membership(namespace, key)
            return None
        return self._materialize_item(namespace, key, parsed)

    def _handle_search(self, op: SearchOp) -> list[SearchItem]:
        """Return all items whose namespaces match the provided prefix."""

        namespace_prefix = tuple(op.namespace_prefix)
        matches: list[SearchItem] = []
        for namespace in self._iter_matching_namespaces(namespace_prefix):
            members_key = self._namespace_members_key(namespace)
            for raw_key in self._client.smembers(members_key):
                key = self._decode(raw_key)
                item = self._handle_get(GetOp(namespace, key, op.refresh_ttl))
                if item is None:
                    continue
                if not self._matches_filter(item, op.filter):
                    continue
                matches.append(
                    SearchItem(
                        namespace=namespace,
                        key=item.key,
                        value=item.value,
                        created_at=item.created_at,
                        updated_at=item.updated_at,
                        score=None,
                    )
                )
        offset = op.offset or 0
        limit = op.limit or len(matches)
        return matches[offset : offset + limit]

    def _handle_list_namespaces(self, op: ListNamespacesOp) -> list[tuple[str, ...]]:
        """List namespaces honoring the constraints from ``op``."""

        namespaces = []
        for namespace in self._iter_all_namespaces():
            if op.match_conditions and not self._matches_conditions(namespace, op.match_conditions):
                continue
            namespaces.append(namespace)

        namespaces.sort()
        if op.max_depth is not None:
            namespaces = [namespace[: op.max_depth] for namespace in namespaces]

        offset = op.offset or 0
        limit = op.limit or len(namespaces)
        return namespaces[offset : offset + limit]

    # ------------------------------------------------------------------
    # Utility helpers
    # ------------------------------------------------------------------

    def _iter_all_namespaces(self) -> list[tuple[str, ...]]:
        """Enumerate every namespace currently tracked by the store."""

        tokens = self._client.smembers(self._namespaces_key)
        return [self._token_to_namespace(self._decode(token)) for token in tokens]

    def _iter_matching_namespaces(self, prefix: Sequence[str]) -> list[tuple[str, ...]]:
        """Return namespaces whose label sequence matches ``prefix``."""

        return [namespace for namespace in self._iter_all_namespaces() if self._matches_prefix(namespace, prefix)]

    def _matches_prefix(self, namespace: Sequence[str], prefix: Sequence[str]) -> bool:
        """Evaluate whether ``namespace`` starts with ``prefix`` (supporting ``*``)."""

        if not prefix:
            return True
        if len(prefix) > len(namespace):
            return False
        for index, label in enumerate(prefix):
            if label != "*" and namespace[index] != label:
                return False
        return True

    def _matches_conditions(self, namespace: Sequence[str], conditions: Sequence[MatchCondition]) -> bool:
        """Validate namespace filters for :class:`ListNamespacesOp`."""

        for condition in conditions:
            if condition.match_type == "prefix":
                if not self._matches_prefix(namespace, condition.path):
                    return False
            elif condition.match_type == "suffix":
                if len(condition.path) > len(namespace):
                    return False
                offset = len(namespace) - len(condition.path)
                for index, label in enumerate(condition.path):
                    if label != "*" and namespace[offset + index] != label:
                        return False
            else:
                msg = f"Unsupported match type: {condition.match_type}"
                raise NotImplementedError(msg)
        return True

    def _token_to_namespace(self, token: str) -> tuple[str, ...]:
        """Convert stored namespace tokens back into tuples."""

        if not token:
            return tuple()
        return tuple(token.split("/"))

    def _safe_load(self, payload: Any) -> dict[str, Any] | None:
        """Deserialize stored JSON payloads safely."""

        try:
            if isinstance(payload, bytes):
                payload = payload.decode("utf-8")
            return json.loads(payload)
        except json.JSONDecodeError:
            return None

    def _cleanup_membership(self, namespace: Sequence[str], key: str) -> None:
        """Remove empty namespaces from the membership index."""

        members_key = self._namespace_members_key(namespace)
        if self._client.srem(members_key, key):
            if not self._client.smembers(members_key):
                self._client.srem(self._namespaces_key, self._namespace_token(namespace))

    def _materialize_item(self, namespace: Sequence[str], key: str, data: dict[str, Any]) -> Item:
        """Create an :class:`Item` instance from stored metadata."""

        value = self._ensure_mapping(data.get("value", {}))
        created_at = self._parse_datetime(data.get("created_at", datetime.now(UTC).isoformat()))
        updated_at = self._parse_datetime(data.get("updated_at", datetime.now(UTC).isoformat()))
        return Item(
            value=value,
            key=str(key),
            namespace=tuple(namespace),
            created_at=created_at,
            updated_at=updated_at,
        )

    def _matches_filter(self, item: Item, filter_: dict[str, Any] | None) -> bool:
        """Evaluate value-based filtering for :class:`SearchOp`."""

        if not filter_:
            return True
        for field, expected in filter_.items():
            if item.value.get(field) != expected:
                return False
        return True

    def _ensure_mapping(self, value: Any) -> dict[str, Any]:
        """Ensure store values are dictionaries as required by LangGraph."""

        if isinstance(value, dict):
            return value
        msg = f"RedisStore requires dictionary payloads. Got {type(value)}"
        raise TypeError(msg)

    def _parse_datetime(self, value: Any) -> datetime:
        """Parse ISO 8601 timestamps into timezone-aware ``datetime`` objects."""

        if isinstance(value, datetime):
            return value.astimezone(UTC)
        if isinstance(value, str):
            try:
                parsed = datetime.fromisoformat(value)
            except ValueError as exc:
                raise ValueError(f"Invalid datetime format: {value}") from exc
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=UTC)
            return parsed.astimezone(UTC)
        msg = f"Unsupported datetime representation: {value!r}"
        raise TypeError(msg)

    def _normalize_ttl(self, ttl: float | None) -> int | None:
        """Convert LangGraph TTL minutes into Redis seconds."""

        if ttl is None:
            return None
        return int(timedelta(minutes=ttl).total_seconds())
