from jina_clone.briefing.feed import render_page_html


def _record() -> dict:
    # Degraded record renders without a digest fixture; the button is in
    # the masthead, independent of the body.
    return {
        "date": "2026-06-15",
        "edition": "morning",
        "edition_label": "Morning",
        "date_label": "Sun Jun 15",
        "generated_at": "2026-06-15T08:45:00-04:00",
        "degraded": True,
        "digest": None,
        "headlines": [],
    }


def test_page_has_broadsheet_button():
    html = render_page_html(_record())
    assert "https://themorningfox.com" in html
    assert 'class="broadsheet-link"' in html
    # Button lives in the masthead header, before the body content.
    assert html.index("broadsheet-link") < html.index("</header>")
