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


def test_page_has_dark_mode_toggle():
    html = render_page_html(_record())
    # Pre-paint theme script + meta, mirroring the main site (web/index.html).
    assert '<meta name="color-scheme" content="light dark">' in html
    assert 'localStorage.getItem("theme")' in html
    # Toggle button and the dark CSS-variable override it switches.
    assert '<button id="theme-toggle"' in html
    assert ':root[data-theme="dark"]' in html
    # Pre-paint script must run before the toggle button renders.
    assert html.index('document.documentElement.dataset.theme') < html.index(
        '<button id="theme-toggle"'
    )
