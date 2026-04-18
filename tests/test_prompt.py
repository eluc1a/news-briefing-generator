from jina_clone.summarizer.prompt import SYSTEM_PROMPT, build_user_prompt


def test_build_user_prompt_includes_all_articles_under_cap():
    articles = [
        {"source": "Src A", "title": "T1", "link": "http://x/1", "content": "c1"},
        {"source": "Src B", "title": "T2", "link": "http://x/2", "content": "c2"},
    ]
    prompt, included = build_user_prompt(articles, per_article_cap=4000, total_cap=200_000)
    assert "http://x/1" in prompt
    assert "http://x/2" in prompt
    assert "T1" in prompt and "c1" in prompt
    assert [a["link"] for a in included] == ["http://x/2", "http://x/1"]


def test_build_user_prompt_truncates_oldest_first_when_over_total_cap():
    articles = [
        {"source": "s", "title": f"T{i}", "link": f"http://x/{i}",
         "content": "x" * 1000}
        for i in range(50)
    ]
    prompt, included = build_user_prompt(articles, per_article_cap=1000, total_cap=5_000)
    # newest kept, oldest dropped
    assert included[0]["link"] == "http://x/49"
    assert len(prompt) <= 5_000


def test_build_user_prompt_caps_each_article_body():
    articles = [{"source": "s", "title": "t", "link": "http://a/1", "content": "x" * 10_000}]
    prompt, included = build_user_prompt(articles, per_article_cap=100, total_cap=200_000)
    # body in prompt should be truncated
    assert prompt.count("x") <= 100


def test_system_prompt_is_stable():
    assert "headline" in SYSTEM_PROMPT.lower()
    assert "body" in SYSTEM_PROMPT.lower()
