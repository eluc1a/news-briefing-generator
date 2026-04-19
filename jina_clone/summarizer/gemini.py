from google import genai
from google.genai import types

from jina_clone.summarizer.providers import parse_json_response


class GeminiProvider:
    name = "gemini"

    def __init__(self, api_key: str, model: str | None = None):
        self.model = model or "gemini-3.1-flash-lite-preview"
        self._client = genai.Client(api_key=api_key)

    async def summarize(self, system: str, user: str) -> dict:
        response = await self._client.aio.models.generate_content(
            model=self.model,
            contents=user,
            config=types.GenerateContentConfig(
                system_instruction=system,
                response_mime_type="application/json",
            ),
        )
        return parse_json_response(response.text or "")

    async def count_tokens(self, text: str) -> int:
        response = await self._client.aio.models.count_tokens(
            model=self.model, contents=text,
        )
        return response.total_tokens
