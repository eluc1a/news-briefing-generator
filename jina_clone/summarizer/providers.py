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
