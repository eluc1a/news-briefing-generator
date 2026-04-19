from typing import Awaitable, Callable


def build_system_prompt(category: str) -> str:
    return (
        f"You are summarizing {category}-related articles for a daily brief.\n"
        f"\n"
        f"Your output must be a single JSON object with two fields:\n"
        f'  - "headline": a concise, informative one-line title (under 80 characters)\n'
        f'  - "body": a markdown-formatted summary grouped by theme, with bulleted\n'
        f"    one-sentence takeaways. Each bullet should include an inline markdown\n"
        f"    link back to the source article's URL.\n"
        f"\n"
        f"Do not include any text outside the JSON object.\n"
    )


def _render(article: dict, per_article_cap: int) -> str:
    body = (article.get("content") or "")[:per_article_cap]
    return (
        f"---\n"
        f"source: {article.get('source')}\n"
        f"title: {article.get('title')}\n"
        f"url: {article.get('link')}\n"
        f"\n{body}\n"
    )


CountTokens = Callable[[str], Awaitable[int]]


async def build_user_prompt(
    articles: list[dict],
    *,
    count_tokens: CountTokens,
    per_article_cap: int = 4000,
    token_cap: int = 850_000,
) -> tuple[str, list[dict]]:
    """Returns (prompt_text, included_articles).

    Articles are assumed oldest-first. Starts with all articles (newest
    first in the rendered prompt) and drops oldest one at a time until
    the real token count reported by the provider is <= token_cap.
    Typical case is a single count_tokens call.
    """
    selected = list(reversed(articles))
    prompt = "".join(_render(a, per_article_cap) for a in selected)
    while selected:
        tokens = await count_tokens(prompt)
        if tokens <= token_cap:
            break
        selected.pop()
        prompt = "".join(_render(a, per_article_cap) for a in selected)
    return prompt, selected
