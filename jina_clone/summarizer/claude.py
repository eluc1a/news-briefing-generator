from anthropic import AsyncAnthropic

from jina_clone.summarizer.providers import parse_json_response


class ClaudeProvider:
    name = "claude"

    def __init__(self, api_key: str, model: str | None = None):
        self.model = model or "claude-sonnet-4-6"
        self._client = AsyncAnthropic(api_key=api_key)

    async def summarize(self, system: str, user: str) -> dict:
        response = await self._client.messages.create(
            model=self.model,
            max_tokens=4096,
            system=[
                {
                    "type": "text",
                    "text": system,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": user}],
        )
        text = "".join(
            block.text for block in response.content if block.type == "text"
        )
        return parse_json_response(text)

    async def count_tokens(self, text: str) -> int:
        response = await self._client.messages.count_tokens(
            model=self.model,
            messages=[{"role": "user", "content": text}],
        )
        return response.input_tokens
