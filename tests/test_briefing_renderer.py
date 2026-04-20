from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from jina_clone.briefing.live_data import weather_glyph
from jina_clone.briefing.renderer import render_pdf
from jina_clone.briefing.schema import Briefing


def _make_env(tmpl_dir):
    """Build a Jinja2 Environment matching the renderer, with the
    `weather_glyph` filter registered. Every manual-render test in this
    file uses this helper so adding future filters only touches one
    spot."""
    env = Environment(
        loader=FileSystemLoader(str(tmpl_dir)),
        autoescape=select_autoescape(["html", "j2"]),
    )
    env.filters["weather_glyph"] = weather_glyph
    return env


FIXTURE = Path("jina_clone/briefing/fixtures/sample_briefing.json")


def test_render_pdf_writes_valid_pdf(tmp_path):
    briefing = Briefing.model_validate_json(FIXTURE.read_text())
    out = tmp_path / "briefing.pdf"
    render_pdf(
        briefing,
        out,
        generated_at="08:11 ET",
        iso_date="2026-04-18",
    )
    assert out.exists()
    data = out.read_bytes()
    assert data.startswith(b"%PDF-")
    assert len(data) > 4096


def test_render_pdf_is_exactly_two_pages(tmp_path):
    """The briefing must render as exactly 2 letter pages, no more."""
    import pypdf
    briefing = Briefing.model_validate_json(FIXTURE.read_text())
    out = tmp_path / "briefing.pdf"
    render_pdf(briefing, out, generated_at="08:11 ET", iso_date="2026-04-18")
    reader = pypdf.PdfReader(str(out))
    assert len(reader.pages) == 2


def test_rendered_html_contains_panel_item():
    """The template must render each panel's `also` entries as .panel-item blocks."""
    briefing = Briefing.model_validate_json(FIXTURE.read_text())
    tmpl_dir = Path("jina_clone/briefing/templates")
    env = _make_env(tmpl_dir)
    tmpl = env.get_template("briefing.html.j2")
    html_str = tmpl.render(
        **briefing.model_dump(),
        generated_at="08:11 ET",
        iso_date="2026-04-18",
    )
    # 4 panels × at least 3 also items = ≥ 12 .panel-item occurrences.
    assert html_str.count('class="panel-item"') >= 12
    # Ink-wasting cream background must be gone.
    assert "#fcfaf4" not in html_str


def test_rendered_html_uses_briefing_title():
    import json

    data = json.loads(FIXTURE.read_text())
    data["title"] = "The Evening Fox"
    briefing = Briefing.model_validate(data)
    tmpl_dir = Path("jina_clone/briefing/templates")
    env = _make_env(tmpl_dir)
    tmpl = env.get_template("briefing.html.j2")
    html_str = tmpl.render(
        **briefing.model_dump(),
        generated_at="20:11 ET",
        iso_date="2026-04-18",
    )
    assert html_str.count("The Evening Fox") >= 3
    assert "The Morning Fox" not in html_str


def test_rendered_html_has_no_forced_page_break():
    """The template must not force a page break between main content and briefs."""
    briefing = Briefing.model_validate_json(FIXTURE.read_text())
    tmpl_dir = Path("jina_clone/briefing/templates")
    env = _make_env(tmpl_dir)
    tmpl = env.get_template("briefing.html.j2")
    html_str = tmpl.render(
        **briefing.model_dump(),
        generated_at="08:11 ET",
        iso_date="2026-04-18",
    )
    assert "page-break-after: always" not in html_str


def test_rendered_html_respects_include_extras_flag():
    """data_point and on_this_day sections must be omittable via include_extras=False."""
    briefing = Briefing.model_validate_json(FIXTURE.read_text())
    tmpl_dir = Path("jina_clone/briefing/templates")
    env = _make_env(tmpl_dir)
    tmpl = env.get_template("briefing.html.j2")

    # Default render — extras present.
    html_with = tmpl.render(
        **briefing.model_dump(),
        generated_at="08:11 ET",
        iso_date="2026-04-18",
    )
    assert "Data point of the day" in html_with
    assert "On this day" in html_with

    # Explicit off — extras omitted.
    html_without = tmpl.render(
        **briefing.model_dump(),
        generated_at="08:11 ET",
        iso_date="2026-04-18",
        include_extras=False,
    )
    assert "Data point of the day" not in html_without
    assert "On this day" not in html_without


def test_render_drops_extras_on_overflow(tmp_path, caplog):
    """If content overflows to a 3rd page, re-render without data_point/on_this_day."""
    import logging
    import pypdf

    briefing = Briefing.model_validate_json(FIXTURE.read_text())
    # Inflate each brief so the first render with extras spills to 3 pages,
    # but dropping extras brings it back under 2 pages. (Inflating the lead
    # body instead doesn't exercise the safety net — lead-body overflow
    # occupies its own page independent of whether extras are rendered.)
    # Note: with 4 `also` items per panel (Task 9 density bump) we need a
    # smaller bloat factor — 10 repetitions overflows but recovers; 15 does not.
    bloat = " ".join(["Additional filler content."] * 10)
    briefing = briefing.model_copy(update={
        "briefs": [
            br.model_copy(update={"body": br.body + " " + bloat})
            for br in briefing.briefs
        ],
    })

    out = tmp_path / "overflow.pdf"
    with caplog.at_level(logging.WARNING, logger="jina_clone.briefing.renderer"):
        render_pdf(briefing, out, generated_at="08:11 ET", iso_date="2026-04-18")

    # The safety-net warning must fire — this pins the contract so the test
    # can't silently degrade if WeasyPrint's layout tightens in a future
    # version and the overflow branch stops being reachable.
    assert any("re-rendering" in r.message for r in caplog.records)

    reader = pypdf.PdfReader(str(out))
    assert len(reader.pages) == 2
    # Extras must be gone on the overflow path. We assert on the section
    # headers rather than on data_point.value / on_this_day.year_and_title
    # because those strings can appear organically in the lead body (e.g.
    # the fixture's lead mentions "10^25 FLOPs" alongside the data point).
    text = "".join(page.extract_text() for page in reader.pages)
    assert "Data point of the day" not in text
    assert "On this day" not in text


def test_render_keeps_extras_when_fits(tmp_path):
    """Happy path: fixture fits on 2 pages, extras are present."""
    import pypdf

    briefing = Briefing.model_validate_json(FIXTURE.read_text())
    out = tmp_path / "normal.pdf"
    render_pdf(briefing, out, generated_at="08:11 ET", iso_date="2026-04-18")

    reader = pypdf.PdfReader(str(out))
    assert len(reader.pages) == 2
    text = "".join(page.extract_text() for page in reader.pages)
    assert briefing.data_point.value in text


def test_renders_hourly_band():
    """Template must render all 4 hourly slots with time labels + glyphs."""
    briefing = Briefing.model_validate_json(FIXTURE.read_text())
    tmpl_dir = Path("jina_clone/briefing/templates")
    env = _make_env(tmpl_dir)
    tmpl = env.get_template("briefing.html.j2")
    html_str = tmpl.render(
        **briefing.model_dump(),
        generated_at="08:11 ET",
        iso_date="2026-04-20",
    )
    # Four hourly slot containers.
    assert html_str.count('class="hourly-slot"') == 4
    # Each of the four sample time labels must appear.
    for slot in briefing.hourly.slots:
        assert slot.time_label in html_str
    # The `Daylight` label replaced `Pollen`.
    assert "Daylight" in html_str
    assert "Pollen" not in html_str


def test_render_pdf_fits_two_pages_with_hourly_band(tmp_path):
    """Adding the hourly band must not push the briefing past 2 pages."""
    import pypdf
    briefing = Briefing.model_validate_json(FIXTURE.read_text())
    out = tmp_path / "briefing.pdf"
    render_pdf(briefing, out, generated_at="08:11 ET", iso_date="2026-04-20")
    reader = pypdf.PdfReader(str(out))
    assert len(reader.pages) == 2


def test_renders_markets_block():
    """Sidebar must carry all 6 market cells."""
    briefing = Briefing.model_validate_json(FIXTURE.read_text())
    tmpl_dir = Path("jina_clone/briefing/templates")
    env = _make_env(tmpl_dir)
    tmpl = env.get_template("briefing.html.j2")
    html_str = tmpl.render(
        **briefing.model_dump(),
        generated_at="08:11 ET",
        iso_date="2026-04-20",
    )
    # 6 rows of market data.
    assert html_str.count('class="sym"') == 6
    # All six expected symbols present.
    for sym in ["SPY", "QQQ", "TQQQ", "BTC", "10Y", "CPI"]:
        assert f">{sym}<" in html_str
    assert "tabular-nums" in html_str


def test_render_pdf_fits_two_pages_with_full_density(tmp_path):
    """Regression guard for the live-data + density work: with 4 also
    per panel, 6 briefs, hourly band, markets block, and extras (data
    point + on this day) all included, the rendered PDF is exactly 2
    pages. This is the load-bearing fit-test."""
    import pypdf
    briefing = Briefing.model_validate_json(FIXTURE.read_text())
    # Sanity: fixture is at full density.
    for panel in briefing.panels:
        assert len(panel.also) == 4
    assert len(briefing.briefs) == 6
    assert len(briefing.hourly.slots) == 4
    assert len(briefing.markets.items) == 6

    out = tmp_path / "briefing.pdf"
    render_pdf(briefing, out, generated_at="08:11 ET", iso_date="2026-04-20")
    reader = pypdf.PdfReader(str(out))
    assert len(reader.pages) == 2

