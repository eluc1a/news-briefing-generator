import json
import re
from typing import Protocol


class LLMProvider(Protocol):
    name: str
    model: str

    async def summarize(self, system: str, user: str) -> dict: ...
    async def count_tokens(self, text: str) -> int: ...


_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def parse_json_response(raw: str) -> dict:
    cleaned = _FENCE.sub("", raw).strip()
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ValueError(f"LLM response was not valid JSON: {exc}") from exc
    for key in ("headline", "body"):
        if key not in data:
            raise ValueError(f"LLM response missing required key: {key}")
    return {"headline": data["headline"], "body": data["body"]}


def build_provider(settings) -> "LLMProvider":
    from jina_clone.config import _PROVIDER_KEY
    from jina_clone.summarizer.claude import ClaudeProvider
    from jina_clone.summarizer.openai import OpenAIProvider
    from jina_clone.summarizer.gemini import GeminiProvider
    from jina_clone.summarizer.openrouter import OpenRouterProvider

    key_name = _PROVIDER_KEY.get(settings.llm_provider)
    if key_name is None:
        raise ValueError(f"Unknown provider: {settings.llm_provider}")
    api_key = settings.api_keys.get(key_name)
    if not api_key:
        raise ValueError(f"{key_name} is required for LLM_PROVIDER={settings.llm_provider}")

    if settings.llm_provider == "claude":
        return ClaudeProvider(api_key, settings.llm_model)
    if settings.llm_provider == "openai":
        return OpenAIProvider(api_key, settings.llm_model)
    if settings.llm_provider == "gemini":
        return GeminiProvider(api_key, settings.llm_model)
    if settings.llm_provider == "openrouter":
        provider_routing: dict | None = None
        if settings.openrouter_provider_order:
            provider_routing = {
                "order": list(settings.openrouter_provider_order),
                "allow_fallbacks": settings.openrouter_allow_fallbacks,
            }
        return OpenRouterProvider(
            api_key,
            settings.llm_model,
            provider_routing=provider_routing,
            app_url=settings.openrouter_app_url or None,
            app_title=settings.openrouter_app_title or None,
        )
    raise ValueError(f"Unknown provider: {settings.llm_provider}")
