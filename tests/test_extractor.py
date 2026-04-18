from pathlib import Path

from jina_clone.extractor.core import extract_from_html


def test_extract_from_html_returns_title_and_text():
    html = Path("tests/fixtures/article.html").read_text()
    result = extract_from_html(html)
    assert "The Real Title" in result["title"]
    assert "First paragraph" in result["text"]
    assert "junk nav" not in result["text"]
    assert "junk footer" not in result["text"]


def test_extract_from_html_truncates_to_max_length():
    html = Path("tests/fixtures/article.html").read_text()
    result = extract_from_html(html, max_length=50)
    assert len(result["text"]) <= 50
