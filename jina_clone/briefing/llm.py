import logging
import os
import re
from typing import Protocol

from anthropic import AsyncAnthropic
from openai import AsyncOpenAI


_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)
_log = logging.getLogger(__name__)

DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-4-6"
DEFAULT_OPENROUTER_MODEL = "deepseek/deepseek-v4-pro"
MAX_TOKENS = 4096


class BriefingLLM(Protocol):
    name: str
    model: str

    async def call(self, system: str, user: str) -> str: ...


class AnthropicBriefingLLM:
    name = "claude"

    def __init__(self, api_key: str, model: str | None = None):
        self.model = model or DEFAULT_ANTHROPIC_MODEL
        self._client = AsyncAnthropic(api_key=api_key)

    async def call(self, system: str, user: str) -> str:
        from jina_clone.briefing import generator as _gen

        response = await self._client.messages.create(
            model=self.model,
            max_tokens=MAX_TOKENS,
            system=[
                {
                    "type": "text",
                    "text": system,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": user}],
        )
        u = response.usage
        entry = {
            "input": u.input_tokens,
            "output": u.output_tokens,
            "cache_read": getattr(u, "cache_read_input_tokens", 0) or 0,
            "cache_creation": getattr(u, "cache_creation_input_tokens", 0) or 0,
        }
        _gen._USAGE.append(entry)
        _log.info(
            "briefing claude call: input=%d output=%d cache_read=%d cache_creation=%d",
            entry["input"], entry["output"], entry["cache_read"], entry["cache_creation"],
        )
        text = "".join(
            block.text for block in response.content if block.type == "text"
        )
        return _FENCE.sub("", text).strip()


class OpenRouterBriefingLLM:
    name = "openrouter"

    def __init__(
        self,
        api_key: str,
        model: str | None = None,
        provider_routing: dict | None = None,
        app_url: str | None = None,
        app_title: str | None = None,
    ):
        self.model = model or DEFAULT_OPENROUTER_MODEL
        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url="https://openrouter.ai/api/v1",
        )
        self._provider_routing = provider_routing or None
        self._extra_headers: dict[str, str] = {}
        if app_url:
            self._extra_headers["HTTP-Referer"] = app_url
        if app_title:
            self._extra_headers["X-OpenRouter-Title"] = app_title

    async def call(self, system: str, user: str) -> str:
        from jina_clone.briefing import generator as _gen

        kwargs: dict = {
            "model": self.model,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        if self._provider_routing:
            kwargs["extra_body"] = {"provider": self._provider_routing}
        if self._extra_headers:
            kwargs["extra_headers"] = self._extra_headers
        response = await self._client.chat.completions.create(**kwargs)
        u = response.usage
        entry = {
            "input": u.prompt_tokens if u else 0,
            "output": u.completion_tokens if u else 0,
            "cache_read": 0,
            "cache_creation": 0,
        }
        _gen._USAGE.append(entry)
        _log.info(
            "briefing openrouter call: input=%d output=%d",
            entry["input"], entry["output"],
        )
        text = response.choices[0].message.content or ""
        return _FENCE.sub("", text).strip()


_SUPPORTED = {"claude", "openrouter"}


def build_briefing_llm(settings) -> BriefingLLM:
    """Build the briefing LLM adapter selected by settings.llm_provider.

    Briefing supports `claude` and `openrouter` only. Other providers
    that the (deprecated) summarizer accepts (`openai`, `gemini`) are
    rejected here with a clear error.
    """
    provider = settings.llm_provider
    if provider not in _SUPPORTED:
        raise ValueError(
            f"briefing supports {sorted(_SUPPORTED)} only; got {provider!r}"
        )

    if provider == "claude":
        api_key = settings.api_keys.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError(
                "ANTHROPIC_API_KEY is required for LLM_PROVIDER=claude"
            )
        return AnthropicBriefingLLM(api_key, settings.llm_model)

    api_key = settings.api_keys.get("OPENROUTER_API_KEY")
    if not api_key:
        raise ValueError(
            "OPENROUTER_API_KEY is required for LLM_PROVIDER=openrouter"
        )
    provider_routing: dict | None = None
    if settings.openrouter_provider_order:
        provider_routing = {
            "order": list(settings.openrouter_provider_order),
            "allow_fallbacks": settings.openrouter_allow_fallbacks,
        }
    return OpenRouterBriefingLLM(
        api_key,
        settings.llm_model,
        provider_routing=provider_routing,
        app_url=settings.openrouter_app_url or None,
        app_title=settings.openrouter_app_title or None,
    )


def build_briefing_llm_from_env() -> BriefingLLM:
    from jina_clone.config import Settings

    return build_briefing_llm(Settings.from_env())
