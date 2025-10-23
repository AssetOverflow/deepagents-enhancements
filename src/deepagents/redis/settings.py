"""Configuration helpers for Redis-backed capabilities.

The helper types defined here abstract how the rest of the codebase interacts
with ``redis``.  They make it possible to configure Redis via connection URLs
or pre-instantiated clients without forcing the runtime dependency when Redis
is not needed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - optional dependency for type checkers
    import redis


@dataclass(slots=True)
class RedisSettings:
    """Settings for establishing Redis connections.

    Attributes:
        url: Redis connection URL. Required when a client is not supplied.
        prefix: Namespace prefix applied to all keys managed by DeepAgents.
        client: Optional pre-configured Redis client. When provided, ``url`` is
            ignored.
        decode_responses: Whether to decode responses as ``str`` instead of
            returning ``bytes``. Defaults to ``False`` to preserve binary
            payloads.
        socket_timeout: Optional per-operation socket timeout in seconds.
        socket_connect_timeout: Optional timeout for establishing new
            connections.
        retry_on_timeout: Whether redis-py should retry commands that timed out.
        health_check_interval: Interval in seconds for sending health checks on
            idle connections. ``0`` disables health checks.
        extra_kwargs: Additional keyword arguments forwarded to
            :meth:`redis.Redis.from_url`.
    """

    url: str | None = None
    prefix: str = "deepagents"
    client: Any | None = None
    decode_responses: bool = False
    socket_timeout: float | None = None
    socket_connect_timeout: float | None = None
    retry_on_timeout: bool = True
    health_check_interval: float = 0.0
    extra_kwargs: dict[str, Any] = field(default_factory=dict)

    def connection_kwargs(self) -> dict[str, Any]:
        """Materialize connection kwargs for :func:`create_redis_client`.

        Returns:
            Keyword arguments compatible with :meth:`redis.Redis.from_url`.
        """

        kwargs: dict[str, Any] = {
            "decode_responses": self.decode_responses,
            "retry_on_timeout": self.retry_on_timeout,
        }
        if self.socket_timeout is not None:
            kwargs["socket_timeout"] = self.socket_timeout
        if self.socket_connect_timeout is not None:
            kwargs["socket_connect_timeout"] = self.socket_connect_timeout
        if self.health_check_interval is not None:
            kwargs["health_check_interval"] = self.health_check_interval
        kwargs.update(self.extra_kwargs)
        return kwargs


def create_redis_client(settings: RedisSettings) -> Any:
    """Create or reuse a Redis client based on provided settings.

    Args:
        settings: Structured Redis configuration produced by :class:`RedisSettings`.

    Returns:
        A :mod:`redis` client ready for use by cache and store adapters.

    Raises:
        ModuleNotFoundError: If the ``redis`` dependency is unavailable and a
            client instance is not provided.
        ValueError: If no connection URL is supplied when a client is not
            pre-instantiated.
    """

    if settings.client is not None:
        return settings.client
    if settings.url is None:
        msg = "RedisSettings.url must be provided when no client is supplied"
        raise ValueError(msg)
    try:
        import redis  # type: ignore[import-not-found]
    except ModuleNotFoundError as exc:  # pragma: no cover - exercised in integration
        msg = (
            "The 'redis' package is required to create a Redis client. "
            "Install it or provide an instantiated client via RedisSettings.client."
        )
        raise ModuleNotFoundError(msg) from exc
    kwargs = settings.connection_kwargs()
    return redis.Redis.from_url(settings.url, **kwargs)
