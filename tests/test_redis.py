from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from fnmatch import fnmatch
from typing import Any, Iterable, Sequence

import pytest

from deepagents.graph import create_deep_agent
from deepagents.redis.cache import RedisCache
from deepagents.redis.settings import RedisSettings
from deepagents.redis.store import RedisStore
from langgraph.store.base import ListNamespacesOp


class FakeRedisClient:
    """Minimal in-memory Redis stand-in for tests."""

    def __init__(self) -> None:
        self._kv: dict[str, Any] = {}
        self._sets: dict[str, set[str]] = {}
        self._expirations: dict[str, datetime] = {}

    # ---------------------------- Key-Value -----------------------------

    def set(self, key: str, value: Any, ex: int | None = None) -> bool:
        self._kv[key] = value
        if ex is not None:
            self._expirations[key] = datetime.now(UTC) + timedelta(seconds=ex)
        else:
            self._expirations.pop(key, None)
        return True

    def get(self, key: str) -> Any:
        if self._is_expired(key):
            self._kv.pop(key, None)
            return None
        return self._kv.get(key)

    def mget(self, keys: Sequence[str]) -> list[Any]:
        return [self.get(key) for key in keys]

    def delete(self, *keys: str) -> int:
        removed = 0
        for key in keys:
            if key in self._kv:
                del self._kv[key]
                removed += 1
            if key in self._sets:
                removed += len(self._sets.pop(key))
            self._expirations.pop(key, None)
        return removed

    def expire(self, key: str, ttl: int) -> bool:
        if key not in self._kv:
            return False
        self._expirations[key] = datetime.now(UTC) + timedelta(seconds=ttl)
        return True

    def scan_iter(self, match: str | None = None) -> Iterable[str]:
        for key in list(self._kv.keys()):
            if self._is_expired(key):
                continue
            if match is None or fnmatch(key, match):
                yield key

    # ----------------------------- Sets --------------------------------

    def sadd(self, key: str, *members: str) -> int:
        store = self._sets.setdefault(key, set())
        before = len(store)
        store.update(members)
        return len(store) - before

    def srem(self, key: str, *members: str) -> int:
        store = self._sets.get(key)
        if not store:
            return 0
        removed = 0
        for member in members:
            if member in store:
                store.remove(member)
                removed += 1
        if not store:
            self._sets.pop(key, None)
        return removed

    def smembers(self, key: str) -> set[str]:
        return set(self._sets.get(key, set()))

    # ----------------------------- Helpers -----------------------------

    def _is_expired(self, key: str) -> bool:
        expiry = self._expirations.get(key)
        if expiry is None:
            return False
        if datetime.now(UTC) >= expiry:
            self._expirations.pop(key, None)
            return True
        return False


class TestRedisCache:
    def test_round_trip(self) -> None:
        client = FakeRedisClient()
        cache = RedisCache(client, prefix="test-cache")
        key = (("agent",), "payload")
        cache.set({key: ("value", None)})
        assert cache.get([key])[key] == "value"

    def test_clear_namespace(self) -> None:
        client = FakeRedisClient()
        cache = RedisCache(client, prefix="test-cache")
        key = (("agent",), "payload")
        cache.set({key: ("value", None)})
        cache.clear([("agent",)])
        assert cache.get([key]) == {}

    def test_async_paths(self) -> None:
        client = FakeRedisClient()
        cache = RedisCache(client, prefix="async-cache")
        key = (("agent",), "payload")
        asyncio.run(cache.aset({key: ("value", None)}))
        result = asyncio.run(cache.aget([key]))
        assert result[key] == "value"
        asyncio.run(cache.aclear())
        assert asyncio.run(cache.aget([key])) == {}


class TestRedisStore:
    def test_put_get_and_search(self) -> None:
        client = FakeRedisClient()
        store = RedisStore(client, prefix="test-store")
        namespace = ("filesystem",)
        payload = {
            "content": ["hello"],
            "created_at": "2024-01-01T00:00:00+00:00",
            "modified_at": "2024-01-01T00:00:00+00:00",
        }
        key = "/report.md"

        store.put(namespace, key, payload)
        item = store.get(namespace, key)
        assert item is not None
        assert item.value["content"] == ["hello"]

        results = store.search(namespace)
        assert any(result.key == key for result in results)

    def test_list_namespaces(self) -> None:
        client = FakeRedisClient()
        store = RedisStore(client, prefix="test-store")
        store.put(("filesystem",), "/a.txt", {"content": ["a"], "created_at": "1", "modified_at": "1"})
        store.put(("workspace", "filesystem"), "/b.txt", {"content": ["b"], "created_at": "1", "modified_at": "1"})

        namespaces = store.batch([
            ListNamespacesOp(match_conditions=None, max_depth=None, limit=10, offset=0),
        ])[0]
        assert ("filesystem",) in namespaces
        assert ("workspace", "filesystem") in namespaces


def test_create_deep_agent_autowires_redis_resources() -> None:
    client = FakeRedisClient()
    settings = RedisSettings(client=client, prefix="spec")
    agent = create_deep_agent(
        redis_settings=settings,
        enable_redis_cache=True,
        use_longterm_memory=True,
    )
    assert isinstance(agent.store, RedisStore)
