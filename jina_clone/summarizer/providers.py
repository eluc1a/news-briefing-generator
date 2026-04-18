import json
import re
from typing import Protocol


class LLMProvider(Protocol):
    name: str
    model: str

    async def summarize(self, system: str, user: str) -> dict: ...


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
    from jina_clone.summarizer.claude import ClaudeProvider
    from jina_clone.summarizer.openai import OpenAIProvider
    from jina_clone.summarizer.gemini import GeminiProvider

    if settings.llm_provider == "claude":
        return ClaudeProvider(settings.api_keys["ANTHROPIC_API_KEY"], settings.llm_model)
    if settings.llm_provider == "openai":
        return OpenAIProvider(settings.api_keys["OPENAI_API_KEY"], settings.llm_model)
    if settings.llm_provider == "gemini":
        return GeminiProvider(settings.api_keys["GEMINI_API_KEY"], settings.llm_model)
    raise ValueError(f"Unknown provider: {settings.llm_provider}")
