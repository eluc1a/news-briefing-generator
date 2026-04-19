import asyncio

import tiktoken
from openai import AsyncOpenAI

from jina_clone.summarizer.providers import parse_json_response


class OpenAIProvider:
    name = "openai"

    def __init__(self, api_key: str, model: str | None = None):
        self.model = model or "gpt-4o"
        self._client = AsyncOpenAI(api_key=api_key)
        try:
            self._encoding = tiktoken.encoding_for_model(self.model)
        except KeyError:
            self._encoding = tiktoken.get_encoding("cl100k_base")

    async def summarize(self, system: str, user: str) -> dict:
        response = await self._client.chat.completions.create(
            model=self.model,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return parse_json_response(response.choices[0].message.content or "")

    async def count_tokens(self, text: str) -> int:
        return await asyncio.to_thread(lambda: len(self._encoding.encode(text)))
