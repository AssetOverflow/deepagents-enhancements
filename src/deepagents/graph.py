"""Deepagents come with planning, filesystem, and subagents."""

from collections.abc import Callable, Sequence
from typing import Any

from langchain.agents import create_agent
from langchain.agents.middleware import HumanInTheLoopMiddleware, InterruptOnConfig, TodoListMiddleware
from langchain.agents.middleware.summarization import SummarizationMiddleware
from langchain.agents.middleware.types import AgentMiddleware
from langchain.agents.structured_output import ResponseFormat
from langchain_anthropic import ChatAnthropic
from langchain_anthropic.middleware import AnthropicPromptCachingMiddleware
from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool
from langgraph.cache.base import BaseCache
from langgraph.graph.state import CompiledStateGraph
from langgraph.store.base import BaseStore
from langgraph.types import Checkpointer

from deepagents.middleware.filesystem import FilesystemMiddleware
from deepagents.middleware.patch_tool_calls import PatchToolCallsMiddleware
from deepagents.middleware.subagents import CompiledSubAgent, SubAgent, SubAgentMiddleware
from deepagents.redis import RedisCache, RedisSettings, RedisStore, create_redis_client

BASE_AGENT_PROMPT = "In order to complete the objective that the user asks of you, you have access to a number of standard tools."


def get_default_model() -> ChatAnthropic:
    """Get the default model for deep agents.

    Returns:
        ChatAnthropic instance configured with Claude Sonnet 4.
    """
    return ChatAnthropic(
        model_name="claude-sonnet-4-5-20250929",
        max_tokens=20000,
    )


def create_deep_agent(
    model: str | BaseChatModel | None = None,
    tools: Sequence[BaseTool | Callable | dict[str, Any]] | None = None,
    *,
    system_prompt: str | None = None,
    middleware: Sequence[AgentMiddleware] = (),
    subagents: list[SubAgent | CompiledSubAgent] | None = None,
    response_format: ResponseFormat | None = None,
    context_schema: type[Any] | None = None,
    checkpointer: Checkpointer | None = None,
    store: BaseStore | None = None,
    use_longterm_memory: bool = False,
    interrupt_on: dict[str, bool | InterruptOnConfig] | None = None,
    debug: bool = False,
    name: str | None = None,
    cache: BaseCache | None = None,
    redis_settings: RedisSettings | str | None = None,
    enable_redis_cache: bool = False,
    enable_redis_store: bool | None = None,
    redis_cache_default_ttl_seconds: int | None = None,
) -> CompiledStateGraph:
    """Create a deep agent.

    This agent will by default have access to a tool to write todos (write_todos),
    four file editing tools: write_file, ls, read_file, edit_file, and a tool to call
    subagents.

    Redis integration is optional and configured via ``redis_settings``.  When
    provided, callers can opt into Redis-backed caching and/or the Redis-backed
    long-term store without manually instantiating the adapters.

    Args:
        tools: The tools the agent should have access to.
        system_prompt: The additional instructions the agent should have. Will go in
            the system prompt.
        middleware: Additional middleware to apply after standard middleware.
        model: The model to use.
        subagents: The subagents to use. Each subagent should be a dictionary with the
            following keys:
                - `name`
                - `description` (used by the main agent to decide whether to call the
                  sub agent)
                - `prompt` (used as the system prompt in the subagent)
                - (optional) `tools`
                - (optional) `model` (either a LanguageModelLike instance or dict
                  settings)
                - (optional) `middleware` (list of AgentMiddleware)
        response_format: A structured output response format to use for the agent.
        context_schema: The schema of the deep agent.
        checkpointer: Optional checkpointer for persisting agent state between runs.
        store: Optional store for persisting longterm memories.
        use_longterm_memory: Whether to use longterm memory - you must provide a store
            in order to use longterm memory.
        interrupt_on: Optional Dict[str, bool | InterruptOnConfig] mapping tool names to
            interrupt configs.
        debug: Whether to enable debug mode. Passed through to create_agent.
        name: The name of the agent. Passed through to create_agent.
        cache: The cache to use for the agent. Passed through to create_agent.
        redis_settings: Connection settings or URL for Redis-backed capabilities.
            When a string is supplied it is interpreted as a Redis connection URL;
            otherwise provide an instance of :class:`~deepagents.redis.RedisSettings`.
        enable_redis_cache: Whether to automatically configure a Redis cache when
            ``redis_settings`` are provided and ``cache`` is not supplied.
        enable_redis_store: Whether to create a Redis-backed store when
            ``redis_settings`` are provided and ``store`` is not supplied. Defaults
            to ``use_longterm_memory`` when ``None``.
        redis_cache_default_ttl_seconds: Default TTL in seconds for Redis cache
            entries when a TTL is not specified by the caller.

    Returns:
        A configured deep agent.
    """
    if model is None:
        model = get_default_model()

    redis_client = None
    redis_prefix = "deepagents"
    if redis_settings is not None:
        if isinstance(redis_settings, str):
            redis_settings = RedisSettings(url=redis_settings)
        elif not isinstance(redis_settings, RedisSettings):
            msg = "redis_settings must be a RedisSettings instance or connection URL"
            raise TypeError(msg)
        redis_client = create_redis_client(redis_settings)
        redis_prefix = redis_settings.prefix.rstrip(":") or "deepagents"

    if redis_client is not None and cache is None and enable_redis_cache:
        cache = RedisCache(
            redis_client,
            prefix=f"{redis_prefix}:cache",
            default_ttl_seconds=redis_cache_default_ttl_seconds,
        )

    store_to_use = store
    desired_store = enable_redis_store
    if desired_store is None:
        desired_store = use_longterm_memory
    if redis_client is not None and store_to_use is None and desired_store:
        store_to_use = RedisStore(redis_client, prefix=f"{redis_prefix}:store")

    deepagent_middleware = [
        TodoListMiddleware(),
        FilesystemMiddleware(
            long_term_memory=use_longterm_memory,
        ),
        SubAgentMiddleware(
            default_model=model,
            default_tools=tools,
            subagents=subagents if subagents is not None else [],
            default_middleware=[
                TodoListMiddleware(),
                FilesystemMiddleware(
                    long_term_memory=use_longterm_memory,
                ),
                SummarizationMiddleware(
                    model=model,
                    max_tokens_before_summary=170000,
                    messages_to_keep=6,
                ),
                AnthropicPromptCachingMiddleware(unsupported_model_behavior="ignore"),
                PatchToolCallsMiddleware(),
            ],
            default_interrupt_on=interrupt_on,
            general_purpose_agent=True,
        ),
        SummarizationMiddleware(
            model=model,
            max_tokens_before_summary=170000,
            messages_to_keep=6,
        ),
        AnthropicPromptCachingMiddleware(unsupported_model_behavior="ignore"),
        PatchToolCallsMiddleware(),
    ]
    if interrupt_on is not None:
        deepagent_middleware.append(HumanInTheLoopMiddleware(interrupt_on=interrupt_on))
    if middleware is not None:
        deepagent_middleware.extend(middleware)

    return create_agent(
        model,
        system_prompt=system_prompt + "\n\n" + BASE_AGENT_PROMPT if system_prompt else BASE_AGENT_PROMPT,
        tools=tools,
        middleware=deepagent_middleware,
        response_format=response_format,
        context_schema=context_schema,
        checkpointer=checkpointer,
        store=store_to_use,
        debug=debug,
        name=name,
        cache=cache,
    ).with_config({"recursion_limit": 1000})
