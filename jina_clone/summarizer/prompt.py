SYSTEM_PROMPT = """You are summarizing AI-related articles for a daily brief.

Your output must be a single JSON object with two fields:
  - "headline": a concise, informative one-line title (under 80 characters)
  - "body": a markdown-formatted summary grouped by theme, with bulleted
    one-sentence takeaways. Each bullet should include an inline markdown
    link back to the source article's URL.

Do not include any text outside the JSON object.
"""


def _render(article: dict, per_article_cap: int) -> str:
    body = (article.get("content") or "")[:per_article_cap]
    return (
        f"---\n"
        f"source: {article.get('source')}\n"
        f"title: {article.get('title')}\n"
        f"url: {article.get('link')}\n"
        f"\n{body}\n"
    )


def build_user_prompt(
    articles: list[dict],
    *,
    per_article_cap: int = 4000,
    total_cap: int = 200_000,
) -> tuple[str, list[dict]]:
    """Returns (prompt_text, included_articles).

    Articles are assumed oldest-first; if over the total cap, drop the
    oldest until it fits. `included_articles` is what was actually fed
    to the LLM — the summarize job uses this to know which links to
    mark summarized.
    """
    # Work newest-first: reverse, greedily include until total_cap reached,
    # return in newest-first order (included[0] is always the newest article).
    reversed_articles = list(reversed(articles))
    selected: list[dict] = []
    total = 0
    for article in reversed_articles:
        block = _render(article, per_article_cap)
        if total + len(block) > total_cap:
            break
        selected.append(article)
        total += len(block)
    prompt = "".join(_render(a, per_article_cap) for a in selected)
    return prompt, selected
