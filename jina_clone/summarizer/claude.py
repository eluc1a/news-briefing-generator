import logging

from anthropic import AsyncAnthropic

from jina_clone.summarizer.providers import parse_json_response


_log = logging.getLogger(__name__)


class ClaudeProvider:
    name = "claude"

    def __init__(self, api_key: str, model: str | None = None):
        self.model = model or "claude-sonnet-4-6"
        self._client = AsyncAnthropic(api_key=api_key)

    async def _call(self, system: str, user: str) -> str:
        response = await self._client.messages.create(
            model=self.model,
            max_tokens=16_384,
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
        _log.info(
            "claude usage: input=%d output=%d cache_read=%d cache_creation=%d",
            u.input_tokens,
            u.output_tokens,
            getattr(u, "cache_read_input_tokens", 0) or 0,
            getattr(u, "cache_creation_input_tokens", 0) or 0,
        )
        return "".join(
            block.text for block in response.content if block.type == "text"
        )

    async def summarize(self, system: str, user: str) -> dict:
        text = await self._call(system, user)
        try:
            return parse_json_response(text)
        except ValueError as first_err:
            retry_user = (
                f"{user}\n\nYour previous response was not valid JSON: "
                f"{first_err}\nEmit a single valid JSON object only, with "
                f'"headline" and "body" fields. Escape all newlines and '
                f'quotes inside string values.'
            )
            text2 = await self._call(system, retry_user)
            return parse_json_response(text2)

    async def count_tokens(self, text: str) -> int:
        response = await self._client.messages.count_tokens(
            model=self.model,
            messages=[{"role": "user", "content": text}],
        )
        return response.input_tokens
