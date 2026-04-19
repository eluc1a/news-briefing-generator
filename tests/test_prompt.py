from jina_clone.summarizer.prompt import build_system_prompt, build_user_prompt


def _fake_tokens(text: str) -> int:
    # 1 "token" per 4 chars — deterministic and fine for tests.
    return len(text) // 4


async def _count(text: str) -> int:
    return _fake_tokens(text)


async def test_build_user_prompt_includes_all_articles_under_cap():
    articles = [
        {"source": "Src A", "title": "T1", "link": "http://x/1", "content": "c1"},
        {"source": "Src B", "title": "T2", "link": "http://x/2", "content": "c2"},
    ]
    prompt, included = await build_user_prompt(
        articles, count_tokens=_count, per_article_cap=4000, token_cap=50_000,
    )
    assert "http://x/1" in prompt
    assert "http://x/2" in prompt
    assert "T1" in prompt and "c1" in prompt
    assert [a["link"] for a in included] == ["http://x/2", "http://x/1"]


async def test_build_user_prompt_truncates_oldest_first_when_over_token_cap():
    articles = [
        {"source": "s", "title": f"T{i}", "link": f"http://x/{i}",
         "content": "x" * 1000}
        for i in range(50)
    ]
    prompt, included = await build_user_prompt(
        articles, count_tokens=_count, per_article_cap=1000, token_cap=1_250,
    )
    # newest kept, oldest dropped
    assert included[0]["link"] == "http://x/49"
    assert _fake_tokens(prompt) <= 1_250


async def test_build_user_prompt_caps_each_article_body():
    articles = [{"source": "s", "title": "t", "link": "http://a/1", "content": "x" * 10_000}]
    prompt, included = await build_user_prompt(
        articles, count_tokens=_count, per_article_cap=100, token_cap=200_000,
    )
    assert prompt.count("x") <= 100


def test_build_system_prompt_contains_category_and_contract():
    prompt = build_system_prompt("politics")
    assert "politics-related" in prompt
    assert "headline" in prompt.lower()
    assert "body" in prompt.lower()
