"""Redis-backed cache implementation.

This module exposes :class:`RedisCache`, a concrete implementation of
``langgraph``'s :class:`~langgraph.cache.base.BaseCache` interface that stores
serialized payloads inside a Redis instance.  The adapter intentionally keeps
its public surface area aligned with the base class while providing a small set
of conveniences around namespaced key generation and TTL normalization.

Because ``BaseCache`` performs serialization through the provided ``serde``
instance, the implementation focuses on orchestration around Redis rather than
payload encoding.  This makes the cache safe to reuse across agents regardless
of how they persist their data.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from typing import Any

from langgraph.cache.base import BaseCache, FullKey, Namespace


class RedisCache(BaseCache[Any]):
    """Cache adapter that persists entries in Redis.

    The cache stores entries using a hierarchical namespace schema, e.g.
    ``deepagents:cache:namespace:key``.  All reads and writes are performed via
    simple ``GET``/``SET`` operations (and their multi-key variants) to remain
    compatible with the vast majority of Redis deployments.
    """

    def __init__(
        self,
        client: Any,
        *,
        prefix: str = "deepagents:cache",
        default_ttl_seconds: int | None = None,
        serde: Any | None = None,
    ) -> None:
        """Instantiate the cache adapter.

        Args:
            client: A :mod:`redis` compatible client exposing ``mget`` and
                ``set`` operations.
            prefix: Key prefix applied to every entry managed by the cache.
            default_ttl_seconds: Fallback TTL (in seconds) used when callers do
                not supply a TTL.
            serde: Serializer implementation supplied to ``BaseCache``.
        """

        super().__init__(serde=serde)
        self._client = client
        self._prefix = prefix.rstrip(":")
        self._default_ttl_seconds = default_ttl_seconds

    def _format_key(self, full_key: FullKey) -> str:
        """Convert a ``FullKey`` into a namespaced Redis key."""

        namespace, key = full_key
        if namespace:
            namespace_segment = ":".join(namespace)
            return f"{self._prefix}:{namespace_segment}:{key}"
        return f"{self._prefix}:{key}"

    def _deserialize(self, payload: Any) -> Any:
        """Deserialize values returned by Redis into cache payloads."""

        if payload is None:
            return None
        if isinstance(payload, bytes):
            payload = payload.decode("utf-8")
        return self.serde.loads_typed(payload)

    def _normalize_ttl(self, ttl: int | None) -> int | None:
        """Resolve the effective TTL for an entry."""

        if ttl is not None:
            return ttl
        return self._default_ttl_seconds

    def get(self, keys: Sequence[FullKey]) -> dict[FullKey, Any]:
        """Retrieve multiple entries from the cache.

        Args:
            keys: Full cache keys, including namespace information.

        Returns:
            A mapping of the subset of ``keys`` that are present in Redis to
            their deserialized payloads.
        """

        redis_keys = [self._format_key(full_key) for full_key in keys]
        if not redis_keys:
            return {}
        values = self._client.mget(redis_keys)
        result: dict[FullKey, Any] = {}
        for full_key, value in zip(keys, values, strict=False):
            deserialized = self._deserialize(value)
            if deserialized is not None:
                result[full_key] = deserialized
        return result

    async def aget(self, keys: Sequence[FullKey]) -> dict[FullKey, Any]:
        """Asynchronous counterpart to :meth:`get`."""

        return await asyncio.get_running_loop().run_in_executor(None, self.get, list(keys))

    def set(self, pairs: Mapping[FullKey, tuple[Any, int | None]]) -> None:
        """Persist multiple entries in Redis.

        Args:
            pairs: Mapping of full keys to ``(value, ttl_seconds)`` tuples.
        """

        for full_key, (value, ttl) in pairs.items():
            redis_key = self._format_key(full_key)
            payload = self.serde.dumps_typed(value)
            ttl_seconds = self._normalize_ttl(ttl)
            if ttl_seconds is not None:
                self._client.set(redis_key, payload, ex=int(ttl_seconds))
            else:
                self._client.set(redis_key, payload)

    async def aset(self, pairs: Mapping[FullKey, tuple[Any, int | None]]) -> None:
        """Asynchronous counterpart to :meth:`set`."""

        await asyncio.get_running_loop().run_in_executor(None, self.set, dict(pairs))

    def _iter_namespace_keys(self, namespace: Namespace | None) -> list[str]:
        """Enumerate Redis keys matching a namespace filter."""

        pattern = f"{self._prefix}:*"
        if namespace is not None:
            if namespace:
                pattern = f"{self._prefix}:{':'.join(namespace)}:*"
            else:
                pattern = f"{self._prefix}:*"
        return [self._decode_key(key) for key in self._client.scan_iter(match=pattern)]

    def _decode_key(self, key: Any) -> str:
        """Normalize Redis key representations to ``str``."""

        if isinstance(key, bytes):
            return key.decode("utf-8")
        return str(key)

    def clear(self, namespaces: Sequence[Namespace] | None = None) -> None:
        """Remove cache entries.

        Args:
            namespaces: Optional collection of namespace filters to clear.  When
                omitted, the entire cache namespace (``self._prefix``) is purged.
        """

        if namespaces is None:
            keys = self._iter_namespace_keys(None)
        else:
            keys = []
            for namespace in namespaces:
                keys.extend(self._iter_namespace_keys(namespace))
        if keys:
            self._client.delete(*keys)

    async def aclear(self, namespaces: Sequence[Namespace] | None = None) -> None:
        """Asynchronous counterpart to :meth:`clear`."""

        await asyncio.get_running_loop().run_in_executor(None, self.clear, namespaces)
