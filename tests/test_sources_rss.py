from datetime import datetime
from pathlib import Path

from jina_clone.sources.rss import parse_feed


def test_parse_feed_yields_entries():
    xml = Path("tests/fixtures/simon-willison.atom").read_text()
    items = parse_feed(xml)
    assert [i.url for i in items] == [
        "https://example.com/posts/1",
        "https://example.com/posts/2",
    ]
    assert isinstance(items[0].published, datetime)
    assert items[0].published.tzinfo is not None
