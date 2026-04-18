from pathlib import Path

from jina_clone.sources.scrape import parse_index


def test_parse_index_resolves_relative_urls_and_filters_by_selector():
    html = Path("tests/fixtures/hn-index.html").read_text()
    items = parse_index(
        html,
        base_url="https://news.ycombinator.com/",
        selector=".titleline > a",
    )
    assert [i.url for i in items] == [
        "https://blog.example.com/post-a",
        "https://news.ycombinator.com/relative-path",
    ]
    assert items[0].published is None
