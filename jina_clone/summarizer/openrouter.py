import asyncio

import tiktoken
from openai import AsyncOpenAI

from jina_clone.summarizer.providers import parse_json_response


class OpenRouterProvider:
    name = "openrouter"

    def __init__(
        self,
        api_key: str,
        model: str | None = None,
        provider_routing: dict | None = None,
        app_url: str | None = None,
        app_title: str | None = None,
    ):
        self.model = model or "deepseek/deepseek-v4-pro"
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
        # OpenRouter routes to many upstreams; cl100k_base is a reasonable
        # token-count approximation for prompt-cap budgeting across them.
        self._encoding = tiktoken.get_encoding("cl100k_base")

    async def summarize(self, system: str, user: str) -> dict:
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
        return parse_json_response(response.choices[0].message.content or "")

    async def count_tokens(self, text: str) -> int:
        return await asyncio.to_thread(lambda: len(self._encoding.encode(text)))
