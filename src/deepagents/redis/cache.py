"""Redis-backed cache implementation."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from typing import Any

from langgraph.cache.base import BaseCache, FullKey, Namespace


class RedisCache(BaseCache[Any]):
    """Cache adapter that stores serialized payloads in Redis."""

    def __init__(
        self,
        client: Any,
        *,
        prefix: str = "deepagents:cache",
        default_ttl_seconds: int | None = None,
        serde: Any | None = None,
    ) -> None:
        super().__init__(serde=serde)
        self._client = client
        self._prefix = prefix.rstrip(":")
        self._default_ttl_seconds = default_ttl_seconds

    def _format_key(self, full_key: FullKey) -> str:
        namespace, key = full_key
        if namespace:
            namespace_segment = ":".join(namespace)
            return f"{self._prefix}:{namespace_segment}:{key}"
        return f"{self._prefix}:{key}"

    def _deserialize(self, payload: Any) -> Any:
        if payload is None:
            return None
        if isinstance(payload, bytes):
            payload = payload.decode("utf-8")
        return self.serde.loads_typed(payload)

    def _normalize_ttl(self, ttl: int | None) -> int | None:
        if ttl is not None:
            return ttl
        return self._default_ttl_seconds

    def get(self, keys: Sequence[FullKey]) -> dict[FullKey, Any]:
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
        return await asyncio.get_running_loop().run_in_executor(None, self.get, list(keys))

    def set(self, pairs: Mapping[FullKey, tuple[Any, int | None]]) -> None:
        for full_key, (value, ttl) in pairs.items():
            redis_key = self._format_key(full_key)
            payload = self.serde.dumps_typed(value)
            ttl_seconds = self._normalize_ttl(ttl)
            if ttl_seconds is not None:
                self._client.set(redis_key, payload, ex=int(ttl_seconds))
            else:
                self._client.set(redis_key, payload)

    async def aset(self, pairs: Mapping[FullKey, tuple[Any, int | None]]) -> None:
        await asyncio.get_running_loop().run_in_executor(None, self.set, dict(pairs))

    def _iter_namespace_keys(self, namespace: Namespace | None) -> list[str]:
        pattern = f"{self._prefix}:*"
        if namespace is not None:
            if namespace:
                pattern = f"{self._prefix}:{':'.join(namespace)}:*"
            else:
                pattern = f"{self._prefix}:*"
        return [self._decode_key(key) for key in self._client.scan_iter(match=pattern)]

    def _decode_key(self, key: Any) -> str:
        if isinstance(key, bytes):
            return key.decode("utf-8")
        return str(key)

    def clear(self, namespaces: Sequence[Namespace] | None = None) -> None:
        if namespaces is None:
            keys = self._iter_namespace_keys(None)
        else:
            keys = []
            for namespace in namespaces:
                keys.extend(self._iter_namespace_keys(namespace))
        if keys:
            self._client.delete(*keys)

    async def aclear(self, namespaces: Sequence[Namespace] | None = None) -> None:
        await asyncio.get_running_loop().run_in_executor(None, self.clear, namespaces)
